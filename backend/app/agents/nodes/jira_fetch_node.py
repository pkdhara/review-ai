"""Node 2 — Fetch Jira issue data."""
from __future__ import annotations
import re
from datetime import datetime, timezone
from app.agents.state import JiraContext, ReviewState
from app.core.logging import get_logger
from app.services.jira_service import JiraService

log = get_logger(__name__)


async def fetch_jira_node(state: ReviewState) -> dict:
    logs = list(state.get("logs", []))
    jira_key = (
        state.get("pr_context", {}).get("jira_key")
        or state.get("jira_context", {}).get("jira_key")
    )
    if not jira_key:
        entry = _log("jira_fetch", "No Jira key found — skipping Jira fetch.", "warning")
        logs.append(entry)
        return {"logs": logs, "current_agent": "jira_fetch", "progress_percent": 18}

    jira_url   = state.get("jira_base_url", "")
    jira_email = state.get("jira_email", "")
    jira_token = state.get("jira_token", "")

    try:
        jira = JiraService(base_url=jira_url, email=jira_email, api_token=jira_token)
        issue = await jira.get_issue(jira_key)

        # Extract acceptance criteria from description
        acs = _extract_acceptance_criteria(issue.get("fields", {}).get("description", ""))

        jira_context: JiraContext = {
            "jira_key":   jira_key,
            "issue_type": issue["fields"].get("issuetype", {}).get("name", ""),
            "summary":    issue["fields"].get("summary", ""),
            "description": _render_adf(issue["fields"].get("description")),
            "acceptance_criteria": acs,
            "technical_notes": "",
            "priority": issue["fields"].get("priority", {}).get("name", ""),
            "status":   issue["fields"].get("status", {}).get("name", ""),
            "labels":   issue["fields"].get("labels", []),
            "story_points": issue["fields"].get("story_points") or issue["fields"].get("customfield_10016"),
        }

        entry = _log("jira_fetch", f"Fetched Jira {jira_key}: {jira_context['summary']}", "info")
        logs.append(entry)
        return {"jira_context": jira_context, "logs": logs, "current_agent": "jira_fetch", "progress_percent": 18}

    except Exception as exc:
        err_msg = str(exc)
        if "404" in err_msg or (hasattr(exc, "response") and getattr(exc.response, "status_code", None) == 404):
            err_msg = f"Jira issue '{jira_key}' not found (404)."
        elif "401" in err_msg or (hasattr(exc, "response") and getattr(exc.response, "status_code", None) == 401):
            err_msg = "Jira authentication failed (401 Unauthorized). Please check your Jira email and API token in System Settings."
        elif "403" in err_msg or (hasattr(exc, "response") and getattr(exc.response, "status_code", None) == 403):
            err_msg = f"Jira access forbidden (403). Account does not have permission for issue '{jira_key}'."

        log.error("node.fetch_jira.failed", jira_key=jira_key, error=err_msg)
        entry = _log("jira_fetch", f"Jira fetch failed: {err_msg}", "warning")
        logs.append(entry)
        errors = {**(state.get("agent_errors") or {}), "jira_fetch": err_msg}
        return {"logs": logs, "agent_errors": errors, "current_agent": "jira_fetch", "progress_percent": 18}


def _extract_acceptance_criteria(description: str | dict | None) -> list[str]:
    if not description:
        return []
    if isinstance(description, dict):
        description = _render_adf(description)
    lines = description.splitlines()
    acs, in_ac = [], False
    for line in lines:
        stripped = line.strip()
        if re.search(r"acceptance criteria", stripped, re.IGNORECASE):
            in_ac = True
            continue
        if in_ac:
            if stripped.startswith(("-", "*", "•", "AC")):
                acs.append(stripped.lstrip("-*•").strip())
            elif stripped and not stripped[0].isdigit():
                break  # end of AC section
    return acs[:20]


def _render_adf(description) -> str:
    """Minimal Atlassian Document Format → plain text."""
    if not description or isinstance(description, str):
        return description or ""
    parts = []
    for block in description.get("content", []):
        for inline in block.get("content", []):
            if inline.get("type") == "text":
                parts.append(inline.get("text", ""))
        parts.append("\n")
    return "".join(parts).strip()


def _log(agent: str, message: str, level: str) -> dict:
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "agent": agent, "message": message, "level": level}
