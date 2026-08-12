"""
Agent 3: Code Quality Agent
Reviews clean code, SOLID, design patterns, Spring Boot and Angular concerns.
"""

from app.agents.base_agent import BaseAgent
from app.agents.state import ReviewState


SYSTEM_PROMPT = """
You are a Senior Software Engineer and Clean Code advocate.
Review the provided code diff for quality issues.

SEVERITY CALIBRATION RULE:
Normal code quality issues (readability, maintainability, complex inline expressions, poor naming, structural issues, minor code smells) MUST be MEDIUM severity at most (`severity: 'medium'`).
Only assign HIGH or CRITICAL if the issue causes an actual runtime crash (e.g. NPE), data corruption, or production failure.

Check the following:
1. Clean Code — meaningful names, single responsibility, small functions, no magic numbers.
2. SOLID Principles — SRP, OCP, LSP, ISP, DIP violations.
3. Design Patterns — missing or misused patterns.
4. Cyclomatic Complexity — overly complex methods or branches.
5. Layer Violations — cross-cutting concerns in wrong layers.
6. Dependency Management — inappropriate coupling, missing injection.

For Spring Boot / Java code:
- Controller-Service-Repository boundary violations.
- Missing @Transactional annotations on write operations.
- Exception handling — swallowed exceptions, incorrect HTTP status codes.
- Missing validation (@Valid, @NotNull, @Size).

For Angular / TypeScript code:
- Component responsibilities (smart vs. dumb components).
- Service usage patterns.
- Memory leaks (missing unsubscribe/takeUntil).
- Missing OnPush change detection strategy.
- Direct DOM manipulation instead of Angular abstractions.
- Observable anti-patterns (nested subscribes, missing error handling).

Return a JSON array of findings:
[{
  "severity": "medium",
  "title": "...",
  "description": "...",
  "evidence": "quote from diff",
  "recommendation": "...",
  "review_comment": "ready-to-post markdown comment",
  "file_path": "...",
  "line_number": null_or_integer
}]

Return ONLY the JSON array.
"""


class CodeQualityAgent(BaseAgent):
    name = "code_quality"
    category = "code_quality"

    async def run(self, state: ReviewState) -> ReviewState:
        logs = list(state.get("logs", []))
        findings = list(state.get("findings", []))
        logs.append(self._log(state, "Reviewing code quality"))

        pr_context = state.get("pr_context") or {}
        diff = pr_context.get("diff", "")

        if not diff:
            return {**state, "logs": logs, "findings": findings, "current_agent": self.name, "progress_percent": 42}

        user_prompt = f"""
Changed files: {[self.get_file_path(f) for f in pr_context.get('changed_files', [])]}

Diff:
{diff}
"""

        try:
            raw_findings = await self._invoke_llm_json(
                SYSTEM_PROMPT,
                user_prompt,
                context_mode="diff_only",
                repository_context=False,
                diff_chars=len(diff),
                context_chars=0,
            )
            for f in raw_findings:
                sev = f.get("severity", "medium")
                impact = (f.get("impact_type") or f.get("defect_impact") or "none").lower()
                desc = (f.get("description") or "").lower() + " " + (f.get("title") or "").lower()
                
                # Check structured impact_type or technical bug indicators
                is_real_bug = (
                    impact in ("correctness", "runtime_failure", "data_integrity", "concurrency", "resource_exhaustion", "security", "production_failure")
                    or any(k in desc for k in [
                        "exception", "error", "npe", "nullpointer", "indexoutofbounds", "arithmeticexception",
                        "stackoverflow", "illegalstateexception", "illegalargumentexception", "concurrentmodificationexception",
                        "classcastexception", "outofmemory", "deadlock", "race condition", "data loss", "data corruption",
                        "concurrency", "integer overflow", "resource leak", "memory leak", "crash", "production failure", "panic", "vulnerability", "defect", "bug"
                    ])
                )
                if sev in ("high", "critical") and not is_real_bug:
                    sev = "medium"
                findings.append(self._make_finding(
                    severity=sev,
                    title=f.get("title", "Code quality issue"),
                    description=f.get("description", ""),
                    recommendation=f.get("recommendation", ""),
                    review_comment=f.get("review_comment", ""),
                    file_path=f.get("file_path"),
                    line_number=f.get("line_number"),
                    evidence=f.get("evidence"),
                    impact_type=impact if impact != "none" else None,
                ))
            logs.append(self._log(state, f"Found {len(raw_findings)} code quality issues"))
        except Exception as exc:
            logs.append(self._log(state, f"Agent error: {exc}", "error"))

        return {**state, "findings": findings, "logs": logs, "current_agent": self.name, "progress_percent": 42}
