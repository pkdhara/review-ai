"""
LangGraph Workflow Orchestrator — Parallel Edition
Builds and executes the multi-agent review pipeline with safe concurrency.

Parallelization strategy
─────────────────────────
Stage 1  (parallel I/O fetch)
  ├── Bitbucket PR fetch
  └── Jira fetch
  ↓  merge_fetch  (single merged ReviewState)

Stage 2  (sequential setup)
  └── Worktree / Code Context

Stage 3  (parallel analysis — asyncio.gather)
  ├── requirement_extraction      ← uses jira_context
  ├── code_quality                ← uses pr_context
  ├── sql_performance             ← uses pr_context
  ├── security                    ← uses pr_context
  ├── refactoring                 ← uses pr_context
  └── test_coverage               ← uses pr_context
  ↓  merge_analysis

Stage 4  (sequential — needs extraction output)
  └── requirement_validation
  └── review_summary              ← needs all findings

Security: All Bitbucket/Jira operations remain READ-ONLY.
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, START, StateGraph

from app.agents.agent_code_quality import CodeQualityAgent
from app.agents.agent_refactoring import RefactoringAgent
from app.agents.agent_requirement_extraction import RequirementExtractionAgent
from app.agents.agent_requirement_validation import RequirementValidationAgent
from app.agents.agent_review_summary import ReviewSummaryAgent
from app.agents.agent_security import SecurityAgent
from app.agents.agent_sql_performance import SqlPerformanceAgent
from app.agents.agent_test_coverage import TestCoverageAgent
from app.agents.state import ReviewState
from app.core.logging import get_logger
from app.core.review_logger import ReviewAuditLogger
from app.services.bitbucket_service import BitbucketService
from app.services.code_context_service import CodeContextService
from app.services.jira_service import JiraService
from app.services.read_only_services import BitbucketReadService, JiraReadService

log = get_logger(__name__)


# ── Independent analysis agents (can run in parallel) ────────────────────────
_PARALLEL_ANALYSIS_AGENTS = [
    (RequirementExtractionAgent, "requirement_extraction", 35),
    (CodeQualityAgent,           "code_quality",           42),
    (SqlPerformanceAgent,        "sql_performance",        50),
    (SecurityAgent,              "security",               58),
    (RefactoringAgent,           "refactoring",            65),
    (TestCoverageAgent,          "test_coverage",          72),
]

# ── Sequential agents that must run after the parallel batch ─────────────────
_SEQUENTIAL_AGENTS = [
    (RequirementValidationAgent, "requirement_validation", 80),
    (ReviewSummaryAgent,         "review_summary",         95),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_entry(agent: str, message: str, level: str = "info") -> dict:
    return {"timestamp": _now_iso(), "agent": agent, "message": message, "level": level}


class ReviewWorkflow:
    """
    Orchestrates the review pipeline using LangGraph + asyncio.gather for concurrency.
    Progress callbacks publish state changes to Redis for SSE streaming.
    """

    def __init__(
        self,
        review_id: str,
        workspace: str,
        repo_slug: str,
        pr_number: int,
        jira_key: Optional[str],
        bitbucket_token: str,
        jira_base_url: str,
        jira_email: str,
        jira_token: str,
        ai_provider: str,
        ai_key: str,
        progress_callback: Optional[Callable] = None,
    ):
        self.settings = {
            "review_id": review_id,
            "workspace": workspace,
            "repo_slug": repo_slug,
            "pr_number": pr_number,
            "jira_key": jira_key,
            "bitbucket_access_token": bitbucket_token,
            "bitbucket_workspace": workspace,
            "jira_base_url": jira_base_url,
            "jira_email": jira_email,
            "jira_api_token": jira_token,
            "ai_provider": ai_provider,
            "ai_key": ai_key,
        }
        self.progress_callback = progress_callback
        self._agents_config = self.settings
        self._audit = ReviewAuditLogger(review_id)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _emit(self, state: dict) -> None:
        if self.progress_callback:
            try:
                await self.progress_callback(state)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # Node 1: parallel_fetch  (Bitbucket ‖ Jira)
    # ─────────────────────────────────────────────────────────────────────────
    async def _parallel_fetch(self, state: ReviewState) -> ReviewState:
        """
        Executes Bitbucket PR fetch and Jira issue fetch concurrently.
        Results are safely merged. A failure in one branch does not discard
        the successful result from the other.
        """
        stage_t0 = time.monotonic()
        logs = list(state.get("logs", []))

        pr_num = self.settings.get('pr_number', 'unknown')
        logs.append(_log_entry("orchestrator", f"Starting Bitbucket fetch for PR {pr_num}"))

        # We know the jira_key is pre-extracted from initial state/settings
        jira_key_for_log = (state.get("pr_context") or {}).get("jira_key") or self.settings.get("jira_key")
        if jira_key_for_log:
            logs.append(_log_entry("orchestrator", f"Starting Jira fetch for {jira_key_for_log}"))
        else:
            logs.append(_log_entry("orchestrator", "Skipping Jira fetch (no jira_key found)"))

        await self._emit({**state, "logs": logs, "current_agent": "pr_fetch", "progress_percent": 3})

        async def _fetch_bb() -> tuple[dict, float, Optional[str]]:
            t0 = time.monotonic()
            self._audit.log_workflow_event("pr_fetch_started", data={
                "workspace": self.settings.get("workspace"),
                "repo_slug": self.settings.get("repo_slug"),
                "pr_number": self.settings.get("pr_number"),
            })
            try:
                base_bb = BitbucketService(
                    access_token=self.settings.get("bitbucket_access_token", ""),
                    workspace=self.settings.get("bitbucket_workspace"),
                    review_id=self.settings.get("review_id"),
                    email=self.settings.get("jira_email"),
                )
                svc = BitbucketReadService(base_bb)
                pr_info = state.get("pr_context") or {}
                ws = pr_info.get("workspace") or self.settings.get("bitbucket_workspace", "")
                repo = pr_info.get("repo_slug", "")
                pr_num = pr_info.get("pr_number", 0)

                if (state.get("pr_context") or {}).get("pr_url"):
                    ws, repo, pr_num = BitbucketService.parse_pr_url(state["pr_context"]["pr_url"])

                ctx = await svc.build_pr_context(ws, repo, pr_num)
                dur = time.monotonic() - t0
                self._audit.log_workflow_event("pr_fetch_completed", data={
                    "pr_title": ctx.get("pr_title"),
                    "jira_key": ctx.get("jira_key"),
                    "files_changed": len(ctx.get("changed_files", [])),
                    "diff_chars": len(ctx.get("diff", "")),
                    "duration_s": round(dur, 3),
                })
                return ctx, dur, None
            except Exception as exc:
                dur = time.monotonic() - t0
                self._audit.log_workflow_event("pr_fetch_failed", error=str(exc))
                return {}, dur, str(exc)

        async def _fetch_jira(bb_task: asyncio.Task) -> tuple[dict, float, Optional[str]]:
            """
            Runs concurrently with Bitbucket fetch unless the jira_key is unknown,
            in which case it awaits the PR fetch first to extract the key.
            """
            t0 = time.monotonic()
            jira_key = (
                (state.get("pr_context") or {}).get("jira_key")
                or self.settings.get("jira_key")
            )
            
            # Wait for PR fetch to finish if we don't know the Jira key yet
            if not jira_key:
                try:
                    pr_ctx, _, _ = await bb_task
                    jira_key = pr_ctx.get("jira_key")
                except Exception:
                    pass

            if not jira_key:
                self._audit.log_workflow_event("jira_fetch_skipped", data={"reason": "no_jira_key"})
                return {}, time.monotonic() - t0, None

            jira_base_url = self.settings.get("jira_base_url", "")
            jira_api_token = self.settings.get("jira_api_token", "")

            if not jira_base_url or not jira_api_token:
                self._audit.log_workflow_event(
                    "jira_fetch_skipped",
                    data={"jira_key": jira_key, "reason": "unconfigured_credentials"},
                )
                return {}, time.monotonic() - t0, None

            self._audit.log_workflow_event("jira_fetch_started", data={"jira_key": jira_key})
            try:
                base_jira = JiraService(
                    base_url=jira_base_url,
                    email=self.settings.get("jira_email", ""),
                    api_token=jira_api_token,
                    review_id=self.settings.get("review_id"),
                )
                svc = JiraReadService(base_jira)
                jira_ctx = await svc.extract_issue_context(jira_key)
                dur = time.monotonic() - t0
                self._audit.log_workflow_event("jira_fetch_completed", data={
                    "jira_key": jira_key,
                    "summary": jira_ctx.get("summary"),
                    "ac_count": len(jira_ctx.get("acceptance_criteria", [])),
                    "duration_s": round(dur, 3),
                })
                return jira_ctx, dur, None
            except Exception as exc:
                dur = time.monotonic() - t0
                self._audit.log_workflow_event("jira_fetch_failed", error=str(exc), data={"jira_key": jira_key})
                return {}, dur, str(exc)

        # ── Run fetches ─────────────────────────────────────
        bb_task = asyncio.create_task(_fetch_bb())
        jira_task = asyncio.create_task(_fetch_jira(bb_task))
        
        (pr_ctx, bb_dur, bb_err), (jira_ctx, jira_dur, jira_err) = await asyncio.gather(
            bb_task,
            jira_task,
        )

        parallel_dur = time.monotonic() - stage_t0  # wall-clock = max(bb, jira)

        # ── Build merged logs ─────────────────────────────────────────────────
        if bb_err:
            logs.append(_log_entry("orchestrator", f"Bitbucket fetch failed ({bb_dur:.2f}s): {bb_err}", "error"))
        else:
            logs.append(_log_entry(
                "orchestrator",
                f"PR '{pr_ctx.get('pr_title', '')}' fetched in {bb_dur:.2f}s. Jira key: {pr_ctx.get('jira_key', 'not found')}",
            ))

        if jira_err:
            logs.append(_log_entry("orchestrator", f"Jira fetch failed ({jira_dur:.2f}s): {jira_err}", "warning"))
        elif jira_ctx:
            logs.append(_log_entry(
                "orchestrator",
                f"Jira issue fetched in {jira_dur:.2f}s: {jira_ctx.get('summary', '')}",
            ))
        else:
            logs.append(_log_entry("orchestrator", f"Jira fetch skipped ({jira_dur:.2f}s)", "warning"))

        logs.append(_log_entry(
            "orchestrator",
            f"Parallel fetch complete — Bitbucket: {bb_dur:.2f}s | Jira: {jira_dur:.2f}s | Wall-clock: {parallel_dur:.2f}s",
        ))

        self._audit.log_workflow_event("parallel_fetch_completed", data={
            "bitbucket_duration_s": round(bb_dur, 3),
            "jira_duration_s": round(jira_dur, 3),
            "parallel_wall_clock_s": round(parallel_dur, 3),
            "bitbucket_error": bb_err,
            "jira_error": jira_err,
        })

        # ── Merge: Bitbucket pr_context wins; Jira jira_context added alongside ──
        merged_pr_ctx = pr_ctx if pr_ctx else (state.get("pr_context") or {})
        # If Bitbucket found a jira_key in the PR title and jira was fetched in
        # parallel using the pre-known key, just use what we have — no duplication.
        new_state = {
            **state,
            "pr_context": merged_pr_ctx,
            "jira_context": jira_ctx if jira_ctx else (state.get("jira_context") or {}),
            "logs": logs,
            "current_agent": "jira_fetch",
            "progress_percent": 10,
        }
        if bb_err and not pr_ctx:
            new_state["error"] = bb_err

        await self._emit(new_state)
        return new_state

    # ─────────────────────────────────────────────────────────────────────────
    # Node 2: code_context  (sequential — needs pr_context from fetch)
    # ─────────────────────────────────────────────────────────────────────────
    async def _setup_code_context(self, state: ReviewState) -> ReviewState:
        logs = list(state.get("logs", []))
        review_id = state.get("review_id", self.settings.get("review_id", ""))
        pr_context = state.get("pr_context") or {}
        repo_slug = state.get("repo_slug") or pr_context.get("repo_slug", "")
        workspace = state.get("workspace") or pr_context.get("workspace", "")

        pr_data = pr_context.get("pr_data") or {}
        source_commit = (
            pr_data.get("source", {}).get("commit", {}).get("hash")
            or pr_context.get("source_commit")
            or pr_context.get("source_branch")
            or "HEAD"
        )
        source_branch = (
            pr_data.get("source", {}).get("branch", {}).get("name")
            or pr_context.get("source_branch")
        )
        diff_text = pr_context.get("diff", "")
        changed_files = pr_context.get("changed_files", [])

        logs.append(_log_entry(
            "orchestrator",
            f"Setting up code context for commit '{source_commit[:8] if len(source_commit) >= 8 else source_commit}'",
        ))
        await self._emit({**state, "logs": logs, "current_agent": "code_context", "progress_percent": 12})

        t0 = time.monotonic()
        context_svc = CodeContextService(review_id)
        ctx_result = await context_svc.initialize_review_context(
            workspace=workspace,
            repo_slug=repo_slug,
            source_commit=source_commit,
            diff_text=diff_text,
            changed_files=changed_files,
            source_branch=source_branch,
        )
        ctx_dur = time.monotonic() - t0

        code_context_state = {
            "repo_path": context_svc.cache.get("worktree_path", ""),
            "worktree_path": ctx_result.get("worktree_path", ""),
            "source_commit": source_commit,
            "target_commit": pr_data.get("destination", {}).get("commit", {}).get("hash", ""),
            "has_local_context": ctx_result.get("has_local_context", False),
            "indexed_classes_count": ctx_result.get("indexed_classes_count", 0),
            "changed_methods_count": ctx_result.get("changed_methods_count", 0),
            "error": ctx_result.get("error"),
        }

        logs.append(_log_entry(
            "orchestrator",
            f"Code context ready in {ctx_dur:.2f}s — "
            f"{ctx_result.get('indexed_classes_count', 0)} classes indexed, "
            f"{ctx_result.get('changed_methods_count', 0)} changed methods",
            "info" if ctx_result.get("has_local_context") else "warning",
        ))

        self._audit.log_workflow_event("code_context_ready", data={
            "duration_s": round(ctx_dur, 3),
            "indexed_classes": ctx_result.get("indexed_classes_count", 0),
            "changed_methods": ctx_result.get("changed_methods_count", 0),
            "has_local_context": ctx_result.get("has_local_context", False),
        })

        new_state = {
            **state,
            "code_context": code_context_state,
            "logs": logs,
            "current_agent": "code_context",
            "progress_percent": 15,
        }
        await self._emit(new_state)
        return new_state

    # ─────────────────────────────────────────────────────────────────────────
    # Node 3: parallel_analysis  (6 agents concurrently via asyncio.gather)
    # ─────────────────────────────────────────────────────────────────────────
    async def _parallel_analysis(self, state: ReviewState) -> ReviewState:
        """
        Runs the 6 independent analysis agents concurrently.
        Each agent receives the same input state and returns its own partial state.
        Findings are merged (union) and logs are concatenated.
        """
        audit = self._audit
        agents_config = self._agents_config
        review_id = self.settings.get("review_id", "")

        logs = list(state.get("logs", []))
        logs.append(_log_entry(
            "orchestrator",
            f"Starting {len(_PARALLEL_ANALYSIS_AGENTS)} analysis agents in parallel",
        ))
        await self._emit({**state, "logs": logs, "current_agent": "code_quality", "progress_percent": 20})

        # ── Pre-flight LLM Provider Health Check ─────────────────────────────
        provider_name = os.environ.get("LLM_PROVIDER", "openai").strip().lower()
        if provider_name == "antigravity":
            try:
                import httpx
                async with httpx.AsyncClient(timeout=3.0) as client:
                    h_resp = await client.get("http://127.0.0.1:8899/health")
                    if h_resp.status_code == 200:
                        log.info("antigravity.bridge.healthy", review_id=review_id, daemon_port=h_resp.json().get("daemon_port"))
                    else:
                        log.warning("antigravity.bridge.degraded", status_code=h_resp.status_code)
            except Exception as h_err:
                log.error("antigravity.bridge.unreachable", error=str(h_err))

        stage_t0 = time.monotonic()
        agent_timings: dict[str, float] = {}

        async def _run_agent(agent_class, agent_name: str, pct: int) -> dict:
            t0 = time.monotonic()
            try:
                agent = agent_class(agents_config)
                result = await agent.run(state)
                dur = time.monotonic() - t0
                agent_timings[agent_name] = dur
                log.info(
                    f"agent.{agent_name}.done",
                    duration_s=round(dur, 3),
                    review_id=review_id,
                )
                return result
            except Exception as exc:  # noqa: BLE001
                dur = time.monotonic() - t0
                agent_timings[agent_name] = dur
                err_msg = str(exc)
                log.error(f"agent.{agent_name}.failed", message=err_msg, review_id=review_id)
                audit.log_workflow_event("agent_error", data={"agent": agent_name, "error": err_msg})
                # Return minimal partial state so merge doesn't fail
                return {
                    **state,
                    "agent_errors": {**dict(state.get("agent_errors") or {}), agent_name: err_msg},
                    "logs": list(state.get("logs") or []) + [
                        _log_entry(agent_name, f"Agent failed: {err_msg}", "error")
                    ],
                }

        results = await asyncio.gather(*[
            _run_agent(cls, name, pct)
            for cls, name, pct in _PARALLEL_ANALYSIS_AGENTS
        ])

        parallel_dur = time.monotonic() - stage_t0

        # ── Merge findings (union) ─────────────────────────────────────────────
        merged_findings: list = list(state.get("findings") or [])
        merged_logs: list = list(state.get("logs") or [])
        merged_errors: dict = dict(state.get("agent_errors") or {})
        merged_requirements: list = list(state.get("requirements") or [])
        merged_extracted: dict = dict(state.get("extracted_requirements") or {})

        seen_finding_ids: set = set()
        for r in results:
            for f in (r.get("findings") or []):
                fid = (f.get("title", ""), f.get("file_path", ""), f.get("agent_name", ""))
                if fid not in seen_finding_ids:
                    seen_finding_ids.add(fid)
                    merged_findings.append(f)

            for entry in (r.get("logs") or []):
                if entry not in merged_logs:
                    merged_logs.append(entry)

            merged_errors.update(r.get("agent_errors") or {})

            # Capture requirement_extraction output specifically
            if r.get("requirements"):
                merged_requirements = r["requirements"]
            if r.get("extracted_requirements"):
                merged_extracted = r["extracted_requirements"]

        # Timing summary log
        timing_lines = " | ".join(
            f"{name}: {agent_timings.get(name, 0):.2f}s"
            for _, name, _ in _PARALLEL_ANALYSIS_AGENTS
        )
        merged_logs.append(_log_entry(
            "orchestrator",
            f"Parallel analysis complete in {parallel_dur:.2f}s (wall-clock). Agents: {timing_lines}",
        ))

        self._audit.log_workflow_event("parallel_analysis_completed", data={
            "wall_clock_s": round(parallel_dur, 3),
            "agent_timings": {k: round(v, 3) for k, v in agent_timings.items()},
            "total_findings_after_merge": len(merged_findings),
        })

        new_state = {
            **state,
            "findings": merged_findings,
            "logs": merged_logs,
            "agent_errors": merged_errors,
            "requirements": merged_requirements,
            "extracted_requirements": merged_extracted,
            "current_agent": "security",
            "progress_percent": 75,
        }
        await self._emit(new_state)
        return new_state

    # ─────────────────────────────────────────────────────────────────────────
    # Node 4+5: sequential_finalize  (requirement_validation → review_summary)
    # ─────────────────────────────────────────────────────────────────────────
    async def _sequential_finalize(self, state: ReviewState) -> ReviewState:
        """
        Runs requirement_validation then review_summary sequentially because each
        depends on the prior agent's findings output.
        """
        current_state = state
        audit = self._audit
        agents_config = self._agents_config
        review_id = self.settings.get("review_id", "")

        for agent_class, agent_name, pct in _SEQUENTIAL_AGENTS:
            t0 = time.monotonic()
            try:
                agent = agent_class(agents_config)
                agent_res = await agent.run(current_state)
                # Merge output safely to prevent partial dict returns from clearing existing state
                current_state = {**current_state, **agent_res}
                dur = time.monotonic() - t0
                log.info(f"agent.{agent_name}.done", duration_s=round(dur, 3), review_id=review_id)
                audit.log_workflow_event(f"agent_{agent_name}_completed", data={
                    "duration_s": round(dur, 3),
                    "findings_count": len(current_state.get("findings") or []),
                })
                if self.progress_callback:
                    await self._emit({**current_state, "current_agent": agent_name, "progress_percent": pct})
            except Exception as exc:  # noqa: BLE001
                dur = time.monotonic() - t0
                err_msg = str(exc)
                log.error(f"agent.{agent_name}.failed", message=err_msg, review_id=review_id)
                audit.log_workflow_event("agent_error", data={"agent": agent_name, "error": err_msg})
                agent_errors = dict(current_state.get("agent_errors") or {})
                agent_errors[agent_name] = err_msg
                current_state = {
                    **current_state,
                    "agent_errors": agent_errors,
                    "logs": list(current_state.get("logs") or []) + [
                        _log_entry(agent_name, f"Agent failed: {err_msg}", "error")
                    ],
                    "error": err_msg,
                    "current_agent": agent_name,
                    "progress_percent": pct,
                }
                await self._emit(current_state)

        return current_state

    # ─────────────────────────────────────────────────────────────────────────
    # Build LangGraph
    # ─────────────────────────────────────────────────────────────────────────
    def build_graph(self) -> StateGraph:
        builder = StateGraph(ReviewState)

        builder.add_node("parallel_fetch",    self._parallel_fetch)
        builder.add_node("code_context",      self._setup_code_context)
        builder.add_node("parallel_analysis", self._parallel_analysis)
        builder.add_node("finalize",          self._sequential_finalize)

        builder.add_edge(START,              "parallel_fetch")
        builder.add_edge("parallel_fetch",   "code_context")
        builder.add_edge("code_context",     "parallel_analysis")
        builder.add_edge("parallel_analysis","finalize")
        builder.add_edge("finalize",         END)

        return builder.compile()

    # ─────────────────────────────────────────────────────────────────────────
    # Execute
    # ─────────────────────────────────────────────────────────────────────────
    async def execute(self, initial_state: Optional[ReviewState] = None) -> ReviewState:
        """Run the full review pipeline and return the final state."""
        review_id = self.settings.get("review_id", "")
        total_t0 = time.monotonic()

        if initial_state is None:
            initial_state = ReviewState(
                review_id=review_id,
                workspace=self.settings["workspace"],
                repo_slug=self.settings["repo_slug"],
                bitbucket_token=self.settings["bitbucket_access_token"],
                jira_base_url=self.settings["jira_base_url"],
                jira_email=self.settings["jira_email"],
                jira_token=self.settings["jira_api_token"],
                ai_provider=self.settings["ai_provider"],
                ai_key=self.settings["ai_key"],
                pr_context={
                    "pr_number": self.settings["pr_number"],
                    "workspace": self.settings["workspace"],
                    "repo_slug": self.settings["repo_slug"],
                    "jira_key": self.settings.get("jira_key"),
                },
                jira_context={},
                findings=[],
                logs=[],
                requirements=[],
                extracted_requirements={},
                current_agent="",
                progress_percent=0,
                progress_callback=self.progress_callback,
            )

        graph = self.build_graph()
        context_svc = CodeContextService(review_id)
        try:
            final_state = await graph.ainvoke(initial_state)
            total_dur = time.monotonic() - total_t0

            # Surface critical agent failures
            agent_errors = final_state.get("agent_errors") or {}
            critical_agents = {"parallel_fetch", "pr_fetch", "requirement_extraction", "code_quality", "security"}
            critical_failures = {k: v for k, v in agent_errors.items() if k in critical_agents}
            if critical_failures:
                raise RuntimeError(
                    f"Critical agent(s) failed: {'; '.join(f'{a}: {e}' for a, e in critical_failures.items())}"
                )

            # Emit timing summary
            self._audit.log_workflow_event("review_completed", data={
                "total_duration_s": round(total_dur, 3),
                "total_findings": len(final_state.get("findings") or []),
                "agent_errors": list(agent_errors.keys()),
            })
            log.info(
                "review.pipeline.complete",
                review_id=review_id,
                total_duration_s=round(total_dur, 3),
                total_findings=len(final_state.get("findings") or []),
            )

            return final_state
        finally:
            cleanup_t0 = time.monotonic()
            await context_svc.cleanup()
            self._audit.log_workflow_event("worktree_cleanup", data={
                "cleanup_duration_s": round(time.monotonic() - cleanup_t0, 3),
            })
