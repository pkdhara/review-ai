"""
Analysis agents — one class per agent, all extending BaseAgent.
Agents 1-8: req_extraction, req_validation, code_quality,
            sql_performance, security, refactoring, test_coverage, review_summary.

All are invoked as LangGraph node functions via their .run() coroutine.
"""
from __future__ import annotations
from datetime import datetime, timezone
from app.agents.base_agent import BaseAgent
from app.agents.state import ReviewState


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(agent: str, msg: str, level: str = "info") -> dict:
    return {"timestamp": _now(), "agent": agent, "message": msg, "level": level}


# ── Agent 1 — Requirement Extraction ─────────────────────────────────────────

SYSTEM_REQ_EXTRACT = """You are a senior business analyst.
Extract structured requirements from the Jira story provided.
Return ONLY a JSON array of requirement objects:
[{"id": "AC-1", "type": "functional|non-functional", "description": "...", "priority": "must|should|could", "testable": true}]"""


class RequirementExtractionAgent(BaseAgent):
    name     = "req_extraction"
    category = "requirement"

    async def run(self, state: ReviewState) -> dict:
        logs = list(state.get("logs", []))
        jira = self._jira_context()
        if not jira:
            logs.append(_log(self.name, "No Jira context — skipping.", "warning"))
            return {"logs": logs, "requirements": [], "current_agent": self.name, "progress_percent": 26}

        user_prompt = f"""Jira Story: {jira.get('jira_key')} — {jira.get('summary')}
Description: {jira.get('description', '')[:3000]}
Acceptance Criteria:
{chr(10).join(f'- {ac}' for ac in jira.get('acceptance_criteria', []))}"""

        try:
            raw = await self._invoke_llm_json(SYSTEM_REQ_EXTRACT, user_prompt)
            requirements = raw if isinstance(raw, list) else raw.get("requirements", [])
            logs.append(_log(self.name, f"Extracted {len(requirements)} requirements."))
            return {"requirements": requirements, "logs": logs, "current_agent": self.name, "progress_percent": 26}
        except Exception as exc:
            logs.append(_log(self.name, f"Failed: {exc}", "error"))
            return {"logs": logs, "requirements": [], "agent_errors": {**(state.get("agent_errors") or {}), self.name: str(exc)}, "progress_percent": 26}


# ── Agent 2 — Requirement Validation ─────────────────────────────────────────

SYSTEM_REQ_VALID = """You are a senior QA engineer.
Compare the code diff against the extracted requirements. Identify gaps, violations, and missing implementations.
Return ONLY a JSON array of findings:
[{"severity": "critical|high|medium|low", "title": "...", "description": "...", "requirement_id": "AC-N",
  "evidence": "code snippet", "recommendation": "...", "review_comment": "..."}]"""


class RequirementValidationAgent(BaseAgent):
    name     = "req_validation"
    category = "requirement"

    async def run(self, state: ReviewState) -> dict:
        logs  = list(state.get("logs", []))
        reqs  = self._requirements()
        diff  = self._truncate_diff(10000)
        if not reqs or not diff:
            logs.append(_log(self.name, "Insufficient input — skipping.", "warning"))
            return {"logs": logs, "current_agent": self.name, "progress_percent": 34}

        user_prompt = f"""Requirements:
{chr(10).join(f'- [{r.get("id")}] {r.get("description")}' for r in reqs[:20])}

Code Diff (first 10k chars):
{diff}"""

        return await self._run_analysis(state, user_prompt, logs, 34)


# ── Agent 3 — Code Quality ────────────────────────────────────────────────────

SYSTEM_CODE_QUALITY = """You are a principal software engineer.
Review the code diff for quality issues: SOLID violations, code smells, coupling, naming, complexity, DRY violations.
Return ONLY a JSON array of findings:
[{"severity": "critical|high|medium|low|info", "title": "...", "description": "...",
  "file_path": "...", "line_number": null, "evidence": "...", "recommendation": "...", "review_comment": "...", "category": "code_quality"}]"""


class CodeQualityAgent(BaseAgent):
    name     = "code_quality"
    category = "code_quality"

    async def run(self, state: ReviewState) -> dict:
        logs = list(state.get("logs", []))
        return await self._run_analysis(state, f"Code Diff:\n{self._truncate_diff(12000)}", logs, 42)


# ── Agent 4 — SQL Performance ─────────────────────────────────────────────────

SYSTEM_SQL = """You are a database performance expert.
Scan the diff for SQL anti-patterns: SELECT *, N+1 queries, missing indexes, unbound queries, Cartesian products, missing pagination.
Return ONLY a JSON array of findings:
[{"severity": "critical|high|medium|low|info", "title": "...", "description": "...",
  "file_path": "...", "line_number": null, "evidence": "SQL snippet", "recommendation": "...", "review_comment": "...", "category": "sql_performance"}]"""


class SqlPerformanceAgent(BaseAgent):
    name     = "sql_performance"
    category = "sql_performance"

    async def run(self, state: ReviewState) -> dict:
        logs = list(state.get("logs", []))
        # Only run if SQL-related files exist
        files = self._files_changed()
        sql_files = [f for f in files if any(ext in f.get("path","") for ext in (".sql", "dao", "repository", "mapper", "query", "jpa"))]
        if not sql_files and "select" not in self._pr_diff().lower():
            logs.append(_log(self.name, "No SQL patterns detected — skipping.", "info"))
            return {"logs": logs, "current_agent": self.name, "progress_percent": 50}
        return await self._run_analysis(state, f"Code Diff:\n{self._truncate_diff(12000)}", logs, 50)


# ── Agent 5 — Security ────────────────────────────────────────────────────────

SYSTEM_SECURITY = """You are an application security expert (OWASP Top 10).
Review the code diff for security vulnerabilities: SQL injection, XSS, insecure auth, hardcoded secrets, IDOR, SSRF, path traversal, insecure deserialization.
Return ONLY a JSON array of findings:
[{"severity": "critical|high|medium|low|info", "title": "...", "description": "...",
  "file_path": "...", "line_number": null, "evidence": "...", "recommendation": "...", "review_comment": "...",
  "owasp_category": "A01-A10", "category": "security"}]"""


class SecurityAgent(BaseAgent):
    name     = "security"
    category = "security"

    async def run(self, state: ReviewState) -> dict:
        logs = list(state.get("logs", []))
        return await self._run_analysis(state, f"Code Diff:\n{self._truncate_diff(12000)}", logs, 58)


# ── Agent 6 — Refactoring ─────────────────────────────────────────────────────

SYSTEM_REFACTORING = """You are a software architecture expert.
Identify refactoring opportunities: god classes, long methods (>30 lines), deep nesting (>4 levels), pattern misuse, dead code, feature envy.
Return ONLY a JSON array of findings:
[{"severity": "medium|low|info", "title": "...", "description": "...",
  "file_path": "...", "line_number": null, "evidence": "...", "recommendation": "...", "review_comment": "...", "category": "refactoring"}]"""


class RefactoringAgent(BaseAgent):
    name     = "refactoring"
    category = "refactoring"

    async def run(self, state: ReviewState) -> dict:
        logs = list(state.get("logs", []))
        return await self._run_analysis(state, f"Code Diff:\n{self._truncate_diff(10000)}", logs, 66)


# ── Agent 7 — Test Coverage ───────────────────────────────────────────────────

SYSTEM_TEST = """You are a senior QA engineer and TDD practitioner.
Review the code diff for testing gaps: missing unit tests, untested edge cases, no integration tests for new endpoints, missing mock setup.
Return ONLY a JSON array of findings:
[{"severity": "high|medium|low|info", "title": "...", "description": "...",
  "file_path": "...", "recommendation": "...", "review_comment": "...", "category": "test_coverage"}]"""


class TestCoverageAgent(BaseAgent):
    name     = "test_coverage"
    category = "test_coverage"

    async def run(self, state: ReviewState) -> dict:
        logs = list(state.get("logs", []))
        return await self._run_analysis(state, f"Code Diff:\n{self._truncate_diff(10000)}", logs, 74)


# ── Agent 8 — Review Summary ──────────────────────────────────────────────────

SYSTEM_SUMMARY = """You are a principal engineer writing an executive PR review summary.
Given the findings list, produce a structured summary.
Return ONLY JSON:
{"risk_score": 0-100, "overall_recommendation": "APPROVE|REQUEST_CHANGES|NEEDS_DISCUSSION",
 "executive_summary": "3-5 sentence summary for the PR author",
 "key_risks": ["..."], "strengths": ["..."]}"""


class ReviewSummaryAgent(BaseAgent):
    name     = "review_summary"
    category = "general"

    async def run(self, state: ReviewState) -> dict:
        logs     = list(state.get("logs", []))
        findings = state.get("findings", [])

        counts = {}
        for f in findings:
            counts[f.get("severity", "info")] = counts.get(f.get("severity", "info"), 0) + 1

        user_prompt = f"""PR: {state.get('pr_context', {}).get('pr_title', 'Unknown')}
Total findings: {len(findings)}
By severity: {counts}
Findings sample:
{chr(10).join(f'- [{f.get("severity").upper()}] {f.get("title")}' for f in findings[:30])}"""

        try:
            raw = await self._invoke_llm_json(SYSTEM_SUMMARY, user_prompt)
            summary = {
                "risk_score":              float(raw.get("risk_score", 50)),
                "overall_recommendation":  raw.get("overall_recommendation", "NEEDS_DISCUSSION"),
                "executive_summary":       raw.get("executive_summary", ""),
                "total_findings":          len(findings),
                "findings_by_severity":    counts,
                "findings_by_category":    self._count_by_category(findings),
            }
            logs.append(_log(self.name, f"Risk score: {summary['risk_score']}, Recommendation: {summary['overall_recommendation']}"))
            return {"summary": summary, "logs": logs, "current_agent": self.name, "progress_percent": 90}
        except Exception as exc:
            logs.append(_log(self.name, f"Summary failed: {exc}", "error"))
            return {"logs": logs, "current_agent": self.name, "progress_percent": 90,
                    "summary": {"risk_score": 50, "overall_recommendation": "NEEDS_DISCUSSION",
                                "executive_summary": "Summary generation failed.", "total_findings": len(findings)}}

    @staticmethod
    def _count_by_category(findings: list) -> dict:
        out: dict = {}
        for f in findings:
            cat = f.get("category", "general")
            out[cat] = out.get(cat, 0) + 1
        return out


# ── Shared helper on BaseAgent ────────────────────────────────────────────────

async def _run_analysis_impl(self: BaseAgent, state: ReviewState, user_prompt: str, logs: list, pct: int) -> dict:
    system = globals().get(f"SYSTEM_{self.name.upper()}", "Analyse the diff and return findings as JSON array.")
    try:
        raw = await self._invoke_llm_json(system, user_prompt)
        raw_list = raw if isinstance(raw, list) else raw.get("findings", [])
        new_findings = self._findings_from_llm(raw_list[:self._max_findings()])
        existing = list(state.get("findings", []))
        logs.append(_log(self.name, f"Found {len(new_findings)} issue(s)."))
        return {"findings": existing + new_findings, "logs": logs, "current_agent": self.name, "progress_percent": pct}
    except Exception as exc:
        logs.append(_log(self.name, f"Failed: {exc}", "error"))
        errors = {**(state.get("agent_errors") or {}), self.name: str(exc)}
        return {"logs": logs, "agent_errors": errors, "current_agent": self.name, "progress_percent": pct}


# Inject the shared helper into BaseAgent
BaseAgent._run_analysis = _run_analysis_impl
