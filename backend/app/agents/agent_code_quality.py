"""
Agent 3: Code Quality Agent
Reviews clean code, SOLID, design patterns, Spring Boot and Angular concerns.
"""

from app.agents.base_agent import BaseAgent
from app.agents.state import ReviewState


SYSTEM_PROMPT = """
You are a Senior Software Engineer and Clean Code advocate.
Review the provided code diff (and optional targeted repository context) for quality and functional defects.

PROVENANCE & CONTEXT RULES:
- Review the PR diff first. Additional repository context is supplied ONLY because the changed code depends on these specific symbols. Use this context ONLY to validate the PR change. Do not search for unrelated issues in the supplied context.
- Distinguish evidence from diff vs evidence from targeted context vs inference.
- You MUST NOT assume or speculate ("the field is likely populated elsewhere"). You must verify concrete evidence such as missing SQL columns, missing setters/mappings, unpopulated domain fields, incorrect parameter passing, or broken callers.
- If evidence is insufficient to prove a defect, do NOT create a high/critical finding.
- Pre-existing issues not introduced or worsened by the PR MUST be classified as origin="pre_existing", classification="recommendation", affected_by_pr=false.

SEVERITY CALIBRATION RULE:
Normal code quality issues (readability, maintainability, complex inline expressions, poor naming, structural issues, minor code smells) MUST be MEDIUM severity at most (`severity: 'medium'`).
Only assign HIGH or CRITICAL if the issue causes an actual runtime failure, NPE, unpopulated data bug, data loss/corruption, or production crash.

Check the following:
1. Data Flow & Correctness — unpopulated getters/fields, missing database query columns/setters, broken method resolution.
2. Clean Code — meaningful names, single responsibility, small functions, no magic numbers.
3. SOLID Principles — SRP, OCP, LSP, ISP, DIP violations.
4. Design Patterns — missing or misused patterns.
5. Cyclomatic Complexity — overly complex methods or branches.
6. Layer Violations — cross-cutting concerns in wrong layers.
7. Dependency Management — inappropriate coupling, missing injection.

Return a JSON array of findings:
[{
  "severity": "high|medium|low",
  "title": "...",
  "description": "...",
  "evidence": "quote from diff or targeted context",
  "recommendation": "...",
  "review_comment": "ready-to-post markdown comment",
  "file_path": "...",
  "line_number": null_or_integer,
  "origin": "introduced_by_pr|modified_by_pr|worsened_by_pr|pre_existing",
  "classification": "finding|recommendation",
  "affected_by_pr": true_or_false
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

        ctx_info = self._prepare_agent_context(state)

        user_prompt = f"""
Changed files: {[self.get_file_path(f) for f in pr_context.get('changed_files', [])]}

Diff:
{diff}
{ctx_info['extra_prompt_text']}
"""

        try:
            raw_findings = await self._invoke_llm_json(
                SYSTEM_PROMPT,
                user_prompt,
                context_mode=ctx_info["context_mode"],
                repository_context=ctx_info["repository_context"],
                diff_chars=ctx_info["diff_chars"],
                context_chars=ctx_info["context_chars"],
                targeted_context_chars=ctx_info["targeted_context_chars"],
                targeted_files=ctx_info["targeted_files"],
                targeted_symbols=ctx_info["targeted_symbols"],
                dependency_triggers=ctx_info["dependency_triggers"],
                dependency_depth=ctx_info["dependency_depth"],
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
                        "concurrency", "integer overflow", "resource leak", "memory leak", "crash", "production failure", "panic", "vulnerability", "defect", "bug", "unpopulated", "missing column"
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
                    origin=f.get("origin"),
                    classification=f.get("classification"),
                    affected_by_pr=f.get("affected_by_pr"),
                ))
            logs.append(self._log(state, f"Found {len(raw_findings)} code quality issues"))
        except Exception as exc:
            logs.append(self._log(state, f"Agent error: {exc}", "error"))

        return {**state, "findings": findings, "logs": logs, "current_agent": self.name, "progress_percent": 42}
