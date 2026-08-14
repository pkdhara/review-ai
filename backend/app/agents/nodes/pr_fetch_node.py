"""Node 1 — Fetch PR diff and metadata from Bitbucket."""
from __future__ import annotations
import re
from app.agents.state import PRContext, ReviewState
from app.core.logging import get_logger
from app.services.bitbucket_service import BitbucketService

log = get_logger(__name__)


async def fetch_pr_node(state: ReviewState) -> dict:
    logs = list(state.get("logs", []))
    workspace  = state["workspace"]
    repo_slug  = state["repo_slug"]
    pr_number  = int(state.get("pr_context", {}).get("pr_number", 0)) or 0
    bb_token   = state.get("bitbucket_token", "")

    log.info("node.fetch_pr", workspace=workspace, repo=repo_slug, pr=pr_number)

    try:
        bb = BitbucketService(workspace=workspace, access_token=bb_token)
        pr_data = await bb.get_pr(repo_slug, pr_number)
        diff    = await bb.get_diff(repo_slug, pr_number, pr_data=pr_data)

        # Extract Jira key from branch name or title
        jira_key = _extract_jira_key(
            pr_data.get("source", {}).get("branch", {}).get("name", ""),
            pr_data.get("title", ""),
        )

        pr_context: PRContext = {
            "pr_number": pr_number,
            "pr_title":  pr_data.get("title", ""),
            "pr_url":    pr_data.get("links", {}).get("html", {}).get("href", ""),
            "source_branch": pr_data.get("source", {}).get("branch", {}).get("name", ""),
            "target_branch": pr_data.get("destination", {}).get("branch", {}).get("name", ""),
            "author":    pr_data.get("author", {}).get("display_name", ""),
            "description": pr_data.get("description", ""),
            "diff":      diff,
            "files_changed": _parse_files(diff),
            "jira_key":  jira_key,
        }

        commits_count = len(pr_data.get("commits", [])) if isinstance(pr_data.get("commits"), list) else 0
        entry = {
            "timestamp": _now(),
            "agent": "pr_fetch",
            "message": f"Fetched PR #{pr_number} — {commits_count} commit(s) found, {len(diff)} bytes diff",
            "level": "info",
        }
        logs.append(entry)
        return {"pr_context": pr_context, "logs": logs, "current_agent": "pr_fetch", "progress_percent": 10}

    except Exception as exc:
        log.error("node.fetch_pr.failed", error=str(exc))
        entry = {"timestamp": _now(), "agent": "pr_fetch", "message": f"PR fetch failed: {exc}", "level": "error"}
        logs.append(entry)
        return {"logs": logs, "agent_errors": {**(state.get("agent_errors") or {}), "pr_fetch": str(exc)},
                "pr_context": {"pr_number": pr_number, "diff": "", "files_changed": []}}


def _extract_jira_key(branch: str, title: str) -> str | None:
    pattern = r"([A-Z][A-Z0-9]+-\d+)"
    for text in (branch, title):
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return None


def _parse_files(diff: str) -> list[dict]:
    files = []
    for block in diff.split("diff --git ")[1:]:
        lines = block.splitlines()
        if not lines:
            continue
        header = lines[0]  # a/path b/path
        parts  = header.split(" b/")
        path   = parts[-1].strip() if parts else header
        added  = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
        files.append({"path": path, "lines_added": added, "lines_removed": removed, "diff": "\n".join(lines[:200])})
    return files


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
