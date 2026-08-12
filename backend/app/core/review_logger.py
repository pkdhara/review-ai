"""
Per-review audit logger.

Writes a structured newline-delimited JSON (JSONL) log file for every PR review:
    /app/logs/reviews/{review_id}.log

Each line is a JSON object with:
    timestamp, event, source (bitbucket|jira|agent|workflow), and relevant payload.

Usage:
    logger = ReviewAuditLogger(review_id)
    logger.log_bitbucket_call("get_pull_request", request={...}, response={...})
    logger.log_jira_call("get_issue", request={...}, response={...})
    logger.log_agent_call("code_quality", prompt="...", response="...", findings=[...])
    logger.log_workflow_event("pr_fetch_started", data={...})
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Logs directory — mounted as a volume or written inside the container
_LOGS_DIR = Path(os.environ.get("REVIEW_LOGS_DIR", "/app/logs/reviews"))


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


class ReviewAuditLogger:
    """Writes structured per-review audit logs to a JSONL file."""

    def __init__(self, review_id: str) -> None:
        self.review_id = review_id
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self._path = _LOGS_DIR / f"{review_id}.log"

    # ── Internal writer ───────────────────────────────────────────────────────

    def _write(self, record: dict) -> None:
        record.setdefault("timestamp", _now())
        record["review_id"] = self.review_id
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass  # never crash the workflow because of logging

    # ── Bitbucket ─────────────────────────────────────────────────────────────

    def log_bitbucket_call(
        self,
        operation: str,
        *,
        request: Optional[dict] = None,
        response: Any = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        self._write({
            "event": "bitbucket_call",
            "source": "bitbucket",
            "operation": operation,
            "request": request or {},
            "response_summary": _summarise(response),
            "error": error,
            "duration_ms": duration_ms,
        })

    # ── Jira ──────────────────────────────────────────────────────────────────

    def log_jira_call(
        self,
        operation: str,
        *,
        request: Optional[dict] = None,
        response: Any = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        self._write({
            "event": "jira_call",
            "source": "jira",
            "operation": operation,
            "request": request or {},
            "response_summary": _summarise(response),
            "error": error,
            "duration_ms": duration_ms,
        })

    # ── Agent / LLM ───────────────────────────────────────────────────────────

    def log_agent_call(
        self,
        agent_name: str,
        *,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        raw_response: Optional[str] = None,
        parsed_result: Any = None,
        findings_count: int = 0,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
        ai_provider: Optional[str] = None,
        model: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        cached_input_tokens: Optional[int] = None,
        usage_available: Optional[bool] = None,
        estimated_cost: Optional[float] = None,
        code_context_usage: Optional[dict] = None,
        **kwargs: Any,
    ) -> None:
        sys_chars = len(system_prompt or "")
        usr_chars = len(user_prompt or "")
        self._write({
            "event": "agent_call",
            "source": "agent",
            "agent": agent_name,
            "provider": ai_provider,
            "ai_provider": ai_provider,
            "model": model,
            "context_mode": kwargs.get("context_mode", "diff_only"),
            "repository_context": kwargs.get("repository_context", False),
            "diff_chars": kwargs.get("diff_chars", 0),
            "context_chars": kwargs.get("context_chars", 0),
            "system_prompt_chars": sys_chars,
            "user_prompt_chars": usr_chars,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cached_input_tokens": cached_input_tokens,
            "usage_available": usage_available,
            "estimated_cost": estimated_cost,
            "duration_ms": duration_ms,
            "findings_count": findings_count,
            "error": error,
            "user_prompt_preview": (user_prompt or "")[:200],
            "raw_response_preview": (raw_response or "")[:300],
            "code_context_usage": code_context_usage or {},
        })

    # ── Workflow events ───────────────────────────────────────────────────────

    def log_workflow_event(
        self,
        event: str,
        data: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        self._write({
            "event": event,
            "source": "workflow",
            "data": data or {},
            "error": error,
        })


# ── Helpers ───────────────────────────────────────────────────────────────────

def _summarise(obj: Any, max_chars: int = 2000) -> Any:
    """Return a compact summary of an API response for logging."""
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj[:max_chars] + ("…" if len(obj) > max_chars else "")
    if isinstance(obj, dict):
        # Return top-level keys + size info rather than full response
        size = len(json.dumps(obj, default=str))
        preview = {k: v for k, v in list(obj.items())[:10]}
        return {"_keys": list(obj.keys()), "_size_chars": size, "_preview": preview}
    if isinstance(obj, list):
        return {"_type": "list", "_len": len(obj), "_first": obj[0] if obj else None}
    return str(obj)[:max_chars]
