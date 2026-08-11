"""
Abstract base agent — shared LLM access, logging, finding factory.
All analysis agents extend this class.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.state import FindingDict, LogEntry, ReviewState
from app.core.logging import get_logger
from app.core.review_logger import ReviewAuditLogger

log = get_logger(__name__)

# Severity ordering for sorting
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


class BaseAgent:
    name: str = "base"
    category: str = "general"

    def __init__(self, settings: dict) -> None:
        """Accept a settings dict (as provided by ReviewWorkflow._make_agent_node)."""
        from app.core.config import settings as app_settings
        self._settings = settings
        self._review_id = settings.get("review_id", "")
        self._ai_provider = settings.get("ai_provider") or getattr(app_settings, "AI_PROVIDER", "gemini")
        self._ai_key = settings.get("ai_key", "")
        self._audit = ReviewAuditLogger(self._review_id)

    # ── LLM ─────────────────────────────────────────────────────────────────


    def _get_llm_provider(self):
        from app.agents.llm_provider import get_llm_provider
        
        pr_context = self._state.get("pr_context") if hasattr(self, "_state") else None
        worktree_path = None
        if pr_context and isinstance(pr_context, dict):
            worktree_path = pr_context.get("worktree_path")
            
        return get_llm_provider(
            ai_provider=self._ai_provider,
            ai_key=self._ai_key,
            worktree_path=worktree_path
        )

    async def _invoke_llm_json(
        self,
        system_prompt: str,
        user_prompt: str,
        retries: int = 2,
    ) -> Any:
        """Invoke LLM and parse JSON from the response. Retries on failure."""
        import time
        from app.agents.llm_provider import LLMResponse
        
        provider = self._get_llm_provider()
        
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response: LLMResponse = await provider.invoke(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.05,
                    json_mode=True
                )
                
                if response.error:
                    raise Exception(response.error)
                    
                text = response.content
                # Strip markdown code fences if present
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()
                result = json.loads(text)

                ctx_svc = self._get_code_context_service({"review_id": self._review_id})
                ctx_usage = ctx_svc.get_usage_metrics() if ctx_svc else {}

                self._audit.log_agent_call(
                    self.name,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    raw_response=response.content,
                    parsed_result=result,
                    findings_count=len(result) if isinstance(result, list) else 0,
                    duration_ms=response.duration_ms,
                    ai_provider=response.provider,
                    model=response.model,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    total_tokens=response.total_tokens,
                    cached_input_tokens=response.cached_input_tokens,
                    usage_available=response.usage_available,
                    estimated_cost=response.estimated_cost,
                    code_context_usage=ctx_usage,
                )
                return result
            except json.JSONDecodeError as e:
                last_error = e
                self._log_warning(f"Analysis failed: JSON parse error (attempt {attempt + 1}): {e}")
            except Exception as e:
                last_error = e
                self._log_error(f"LLM call failed (attempt {attempt + 1}): {e}")
                if attempt == retries:
                    ctx_svc = self._get_code_context_service({"review_id": self._review_id})
                    ctx_usage = ctx_svc.get_usage_metrics() if ctx_svc else {}
                    
                    actual_provider = (
                        response.provider if ('response' in locals() and response and response.provider)
                        else getattr(provider, 'ai_provider', os.environ.get("LLM_PROVIDER", "antigravity"))
                    )
                    actual_model = (
                        response.model if ('response' in locals() and response and response.model)
                        else getattr(provider, 'model', "gemini-3.6-flash")
                    )
                    
                    self._audit.log_agent_call(
                        self.name,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        error=str(e),
                        duration_ms=0,
                        ai_provider=actual_provider,
                        model=actual_model,
                        input_tokens=(len(system_prompt) + len(user_prompt)) // 4,
                        output_tokens=0,
                        total_tokens=(len(system_prompt) + len(user_prompt)) // 4,
                        code_context_usage=ctx_usage,
                    )
                    raise

        raise ValueError(f"Failed to parse LLM JSON after {retries + 1} attempts: {last_error}")

    # ── Finding factory ──────────────────────────────────────────────────────

    def _make_finding(
        self,
        severity: str,
        title: str,
        description: str,
        recommendation: str,
        review_comment: str,
        category: Optional[str] = None,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
        line_number_end: Optional[int] = None,
        evidence: Optional[str] = None,
        confidence_score: Optional[float] = None,
        tags: Optional[list[str]] = None,
    ) -> FindingDict:
        return FindingDict(
            review_id=self._review_id,
            agent_name=self.name,
            severity=severity,
            category=category or self.category,
            file_path=file_path,
            line_number=line_number,
            line_number_end=line_number_end,
            title=title,
            description=description,
            evidence=evidence,
            recommendation=recommendation,
            review_comment=review_comment,
            confidence_score=confidence_score,
            tags=tags or [],
        )

    def _findings_from_llm(self, raw: list[dict]) -> list[FindingDict]:
        """Convert raw LLM output list to FindingDict list, validating fields."""
        findings: list[FindingDict] = []
        valid_severities = {"critical", "high", "medium", "low", "info"}
        for item in raw:
            sev = str(item.get("severity", "medium")).lower()
            if sev not in valid_severities:
                sev = "medium"
            findings.append(self._make_finding(
                severity=sev,
                title=item.get("title", "Untitled finding")[:500],
                description=item.get("description", ""),
                recommendation=item.get("recommendation", ""),
                review_comment=item.get("review_comment") or item.get("description", ""),
                category=item.get("category", self.category),
                file_path=item.get("file_path"),
                line_number=item.get("line_number"),
                line_number_end=item.get("line_number_end"),
                evidence=item.get("evidence"),
                confidence_score=item.get("confidence_score"),
                tags=item.get("tags", []),
            ))
        return findings

    # ── Logging helpers ──────────────────────────────────────────────────────

    def _make_log(self, message: str, level: str = "info") -> LogEntry:
        return LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent=self.name,
            message=message,
            level=level,
        )

    def _log_info(self, message: str) -> LogEntry:
        entry = self._make_log(message, "info")
        log.info(f"agent.{self.name}", message=message, review_id=self._review_id)
        return entry

    def _log_warning(self, message: str) -> LogEntry:
        entry = self._make_log(message, "warning")
        log.warning(f"agent.{self.name}", message=message, review_id=self._review_id)
        return entry

    def _log_error(self, message: str) -> LogEntry:
        entry = self._make_log(message, "error")
        log.error(f"agent.{self.name}", message=message, review_id=self._review_id)
        return entry

    def _log(self, state_or_msg, message: Optional[str] = None, level: str = "info") -> LogEntry:
        """Compatibility helper: _log(state, msg, level) or _log(msg, level)."""
        if message is None:
            # called as _log(message) or _log(message, level)
            actual_message = state_or_msg if isinstance(state_or_msg, str) else str(state_or_msg)
            actual_level = level
        else:
            # called as _log(state, message, level)
            actual_message = message
            actual_level = level
        return self._make_log(actual_message, actual_level)

    # ── State helpers ────────────────────────────────────────────────────────

    @staticmethod
    def get_file_path(f: dict) -> str:
        """Null-safe extraction of file path from Bitbucket diffstat item or raw dict."""
        if not isinstance(f, dict):
            return ""
        if "path" in f and isinstance(f["path"], str):
            return f["path"]
        new_obj = f.get("new") or {}
        if isinstance(new_obj, dict) and new_obj.get("path"):
            return new_obj["path"]
        old_obj = f.get("old") or {}
        if isinstance(old_obj, dict) and old_obj.get("path"):
            return old_obj["path"]
        return ""

    def _pr_diff(self, state: Optional[dict] = None) -> str:
        ctx = (state or {}).get("pr_context") or {}
        return (ctx or {}).get("diff", "")

    def _files_changed(self, state: Optional[dict] = None) -> list[dict]:
        ctx = (state or {}).get("pr_context") or {}
        return (ctx or {}).get("files_changed", [])

    def _jira_context(self, state: Optional[dict] = None) -> dict:
        return (state or {}).get("jira_context") or {}

    def _requirements(self, state: Optional[dict] = None) -> list[dict]:
        return (state or {}).get("requirements") or []

    def _get_code_context_service(self, state: Optional[dict] = None):
        """Returns the CodeContextService instance for the current review."""
        from app.services.code_context_service import CodeContextService
        review_id = (state or {}).get("review_id") or self._settings.get("review_id", "")
        return CodeContextService(review_id)

    def _get_class_structures_prompt(self, state: Optional[dict] = None) -> str:
        """
        Formatted string containing class/component structures (without method bodies)
        for changed files (Java, TypeScript, Angular) to provide cheap architectural context to LLMs.
        """
        svc = self._get_code_context_service(state)
        structures = svc.cache.get("class_structures", {})
        if not structures:
            return ""

        output = ["\n--- CLASS & COMPONENT STRUCTURES (NO METHOD BODIES) ---"]
        seen_files = set()
        for key, struct in structures.items():
            file_path = struct.get("file_path", key)
            if file_path in seen_files:
                continue
            seen_files.add(file_path)

            output.append(f"File: {file_path}")
            output.append(f"Class/Component: {struct.get('class')} ({struct.get('kind', 'class')})")

            decos = struct.get("decorators") or struct.get("annotations")
            if decos:
                output.append(f"Decorators: {', '.join(decos)}")

            if struct.get("selector"):
                output.append(f"Selector: {struct.get('selector')}")
            if struct.get("template_url"):
                output.append(f"TemplateUrl: {struct.get('template_url')}")

            if struct.get("template_content"):
                tmpl_text = struct["template_content"]
                if len(tmpl_text) > 1500:
                    tmpl_text = tmpl_text[:1500] + "\n... (truncated template content)"
                output.append("Template HTML:")
                output.append(tmpl_text)

            if struct.get("extends"):
                output.append(f"Extends: {struct.get('extends')}")
            if struct.get("implements"):
                output.append(f"Implements: {', '.join(struct.get('implements'))}")

            injected = struct.get("injected_dependencies", [])
            if injected:
                output.append(f"Injected Dependencies: {', '.join(injected[:10])}")

            fields = struct.get("fields", [])
            if fields:
                output.append("Fields/Properties:")
                for f in fields[:15]:
                    f_decos = f" ({', '.join(f.get('decorators'))})" if f.get("decorators") else ""
                    output.append(f"  - {f.get('visibility')} {f.get('name')}: {f.get('type')}{f_decos}")

            methods = struct.get("methods", [])
            if methods:
                output.append("Method Signatures:")
                for m in methods[:25]:
                    params = ", ".join(m.get("parameters", []))
                    output.append(f"  - {m.get('visibility')} {m.get('name')}({params}): {m.get('returnType')}")
            output.append("")

        return "\n".join(output)

    def _get_changed_methods_prompt(self, state: Optional[dict] = None) -> str:
        """
        Formatted string containing exact implementation bodies of modified/added methods.
        """
        svc = self._get_code_context_service(state)
        changed_methods = svc.cache.get("changed_methods", [])
        if not changed_methods:
            return ""

        output = ["\n--- CHANGED METHODS IMPLEMENTATIONS ---"]
        for cm in changed_methods:
            output.append(f"Class: {cm.get('class_name')} | Method: {cm.get('method_name')} ({cm.get('file_path')})")
            if cm.get("implementation"):
                output.append(cm.get("implementation"))
            output.append("--------------------------------------------------")

        return "\n".join(output)

    def _max_findings(self) -> int:
        return int(self._settings.get("max_findings_per_agent", 10))

    def _truncate_diff(self, diff: str, max_chars: int = 12000) -> str:
        return diff[:max_chars] + "\n...[truncated]" if len(diff) > max_chars else diff
