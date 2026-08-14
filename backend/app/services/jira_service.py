"""
Jira API integration service.
Fetches story details, acceptance criteria, linked issues, and attachments.
"""

from typing import Any, Dict, List, Optional
import base64
import time

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.logging import get_logger
from app.core.review_logger import ReviewAuditLogger

logger = get_logger(__name__)


def _is_transient_jira_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        if 400 <= exc.response.status_code < 500:
            return False
    return True


# Jira uses ADF (Atlassian Document Format) for rich text fields.
# This helper recursively extracts plain text from ADF nodes.
def _extract_adf_text(node: Any, depth: int = 0) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        text_parts = []
        node_type = node.get("type", "")
        if node_type == "text":
            return node.get("text", "")
        for child in node.get("content", []):
            text_parts.append(_extract_adf_text(child, depth + 1))
        return "\n".join(p for p in text_parts if p)
    if isinstance(node, list):
        return "\n".join(_extract_adf_text(item, depth) for item in node)
    return ""


class JiraService:
    """Client for Jira Cloud REST API v3."""

    def __init__(self, base_url: str, email: str, api_token: str, review_id: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        credentials = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._audit = ReviewAuditLogger(review_id or "unknown")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(_is_transient_jira_error),
        reraise=True,
    )
    async def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        t0 = time.monotonic()
        url = f"{self.base_url}/rest/api/3{path}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers=self.headers, params=params)
                resp.raise_for_status()
                data = resp.json()
                self._audit.log_jira_call(
                    f"GET {path}",
                    request={"params": params},
                    response=data,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                return data
        except Exception as exc:
            self._audit.log_jira_call(
                f"GET {path}",
                request={"params": params},
                error=str(exc),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
            raise

    async def get_issue(self, issue_key: str) -> Dict:
        """Fetch a Jira issue with all fields."""
        data = await self._get(f"/issue/{issue_key}", params={"expand": "renderedFields,names,changelog"})
        return data

    async def get_issue_comments(self, issue_key: str) -> List[Dict]:
        """Fetch comments on a Jira issue."""
        data = await self._get(f"/issue/{issue_key}/comment")
        return (data or {}).get("comments", [])

    async def get_linked_issues(self, issue_key: str) -> List[Dict]:
        """Fetch issues linked to the given issue."""
        issue = await self.get_issue(issue_key) or {}
        fields = issue.get("fields") or {}
        links = fields.get("issuelinks") or []
        linked = []
        for link in links:
            if not isinstance(link, dict):
                continue
            linked_issue = link.get("outwardIssue") or link.get("inwardIssue") or {}
            li_fields = linked_issue.get("fields") or {}
            status_obj = li_fields.get("status") or {}
            type_obj = link.get("type") or {}
            if linked_issue:
                linked.append({
                    "key": linked_issue.get("key"),
                    "summary": li_fields.get("summary"),
                    "status": status_obj.get("name"),
                    "link_type": type_obj.get("name"),
                })
        return linked

    def _parse_acceptance_criteria(self, fields: Dict) -> List[str]:
        """
        Extract acceptance criteria from custom fields.
        Tries common field names used across Jira configurations.
        """
        fields = fields or {}
        # Common custom field IDs for AC
        candidate_field_keys = [
            "customfield_10016",  # common AC field
            "customfield_10014",
            "acceptance_criteria",
            "customfield_10020",
        ]
        for key in candidate_field_keys:
            value = fields.get(key)
            if value:
                if isinstance(value, str):
                    return [line.strip() for line in value.splitlines() if line.strip()]
                if isinstance(value, dict):
                    text = _extract_adf_text(value)
                    return [line.strip() for line in text.splitlines() if line.strip()]

        # Fall back: look for AC in description
        description = fields.get("description") or {}
        desc_text = _extract_adf_text(description)
        criteria = []
        in_ac_section = False
        for line in desc_text.splitlines():
            upper = line.upper()
            if "ACCEPTANCE CRITERIA" in upper or "ACCEPTANCE CRITERION" in upper:
                in_ac_section = True
                continue
            if in_ac_section:
                stripped = line.strip()
                if stripped.startswith(("-", "*", "•", "◦")) or (stripped and stripped[0].isdigit()):
                    criteria.append(stripped.lstrip("-*•◦0123456789. "))
                elif stripped and not stripped.startswith("#"):
                    if any(kw in upper for kw in ["GIVEN", "WHEN", "THEN", "AND", "BUT"]):
                        criteria.append(stripped)
        return criteria

    async def extract_issue_context(self, jira_key: str) -> Dict:
        """Alias for build_requirement_context to support read-only service interface."""
        return await self.build_requirement_context(jira_key)

    async def build_requirement_context(self, jira_key: str) -> Dict:
        """
        Aggregate all Jira data for the AI agents.
        Returns a structured dict with all requirement information.
        """
        logger.info("Fetching Jira issue", key=jira_key)
        issue = await self.get_issue(jira_key) or {}
        comments = await self.get_issue_comments(jira_key) or []
        linked = await self.get_linked_issues(jira_key) or []

        fields = issue.get("fields") or {}
        description_text = _extract_adf_text(fields.get("description") or {})
        acceptance_criteria = self._parse_acceptance_criteria(fields)

        # Technical Notes — look in description for a "Technical Notes" section
        technical_notes = []
        in_tech_section = False
        for line in description_text.splitlines():
            if "TECHNICAL NOTES" in line.upper() or "TECHNICAL DETAILS" in line.upper():
                in_tech_section = True
                continue
            if in_tech_section:
                stripped = line.strip()
                if stripped:
                    technical_notes.append(stripped)
                elif technical_notes:
                    break

        return {
            "jira_key": jira_key,
            "summary": fields.get("summary", ""),
            "status": fields.get("status", {}).get("name", ""),
            "priority": fields.get("priority", {}).get("name", ""),
            "issue_type": fields.get("issuetype", {}).get("name", ""),
            "description": description_text,
            "acceptance_criteria": acceptance_criteria,
            "technical_notes": technical_notes,
            "comments": [
                {
                    "author": c.get("author", {}).get("displayName", ""),
                    "body": _extract_adf_text(c.get("body", {})),
                    "created": c.get("created", ""),
                }
                for c in comments
            ],
            "linked_issues": linked,
            "labels": fields.get("labels", []),
            "components": [c.get("name") for c in fields.get("components", [])],
            "raw_fields": fields,
        }
