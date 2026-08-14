"""
Agent 7: Test Coverage Agent
Analyzes test coverage gaps and recommends missing test scenarios.
Note: Test coverage checks are NOT performed for TypeScript (.ts) files as per project policy.
"""

from app.agents.base_agent import BaseAgent
from app.agents.state import ReviewState


SYSTEM_PROMPT = """
You are a Senior QA Engineer and Test Automation expert.
Analyze the provided code changes (and optional targeted repository context) and identify test coverage gaps.

PROVENANCE & CONTEXT RULES:
- Review the PR diff first. Additional repository context is supplied ONLY because the changed code depends on these specific symbols. Use this context ONLY to validate the PR change. Do not search for unrelated issues in the supplied context.
- Distinguish evidence from diff vs evidence from targeted context vs inference.
- Pre-existing issues not introduced or worsened by the PR MUST be classified as origin="pre_existing", classification="recommendation", affected_by_pr=false.

IMPORTANT CLASSIFICATION RULE:
Test coverage recommendations (missing unit tests, integration tests, edge case tests) are engineering recommendations (`classification: 'recommendation'`).
They should NOT be treated as PR defects unless the absence of a test directly causes a demonstrable runtime defect or regression.

DO NOT check or report missing test coverage for TypeScript (.ts), Angular, HTML, or CSS files. Ignore all frontend TypeScript file changes.

Review backend/Java code changes:
1. Are new Java methods/classes covered by unit tests?
2. Are edge cases and boundary conditions tested?
3. Are error paths and exception scenarios tested?
4. Are there missing integration tests?
5. Has backend code been added without any corresponding tests?
6. Is the test quality adequate (meaningful assertions, proper mocking)?

For Spring Boot / Java:
- Missing @Test for service/repository methods
- Missing MockMvc tests for new endpoints
- Missing exception scenario tests

Return a JSON array:
[{
  "severity": "medium",
  "title": "Missing test: ...",
  "description": "What is not tested and why it matters",
  "evidence": "The untested code",
  "recommendation": "Suggested test scenario with example",
  "review_comment": "Ready-to-post Bitbucket markdown comment",
  "file_path": "...",
  "line_number": null_or_integer,
  "suggested_test_type": "unit|integration|e2e",
  "origin": "pre_existing",
  "classification": "recommendation",
  "affected_by_pr": false
}]

Return ONLY the JSON array.
"""


class TestCoverageAgent(BaseAgent):
    name = "test_coverage"
    category = "test_coverage"

    async def run(self, state: ReviewState) -> ReviewState:
        logs = list(state.get("logs", []))
        findings = list(state.get("findings", []))
        logs.append(self._log(state, "Analyzing test coverage"))

        pr_context = state.get("pr_context") or {}
        diff = pr_context.get("diff", "")
        changed_files = [self.get_file_path(f) for f in pr_context.get("changed_files", [])]

        if not diff:
            return {**state, "logs": logs, "findings": findings, "current_agent": self.name, "progress_percent": 85}

        # Filter out TypeScript and frontend files from test coverage analysis
        non_ts_files = [
            f for f in changed_files
            if not (f.endswith(".ts") or f.endswith(".tsx") or f.endswith(".html") or f.endswith(".css") or f.endswith(".scss"))
        ]

        if not non_ts_files and changed_files:
            logs.append(self._log(state, "Only TypeScript/frontend files changed — skipping test coverage check."))
            return {**state, "logs": logs, "findings": findings, "current_agent": self.name, "progress_percent": 85}

        ctx_info = self._prepare_agent_context(state)

        user_prompt = f"""
Changed files (excluding TypeScript/frontend files):
{chr(10).join(non_ts_files)}

Diff:
{diff}
{ctx_info['extra_prompt_text']}

Note: Ignore all TypeScript (.ts, .tsx, .spec.ts) files and frontend component changes. Only report test coverage issues for backend/Java changes.
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
                fp = f.get("file_path", "") or ""
                # Skip any findings targeting TypeScript files
                if fp.endswith(".ts") or fp.endswith(".tsx") or fp.endswith(".html"):
                    continue

                sev = f.get("severity", "medium")
                if sev not in ("critical", "high", "medium", "low", "info"):
                    sev = "medium"
                findings.append(self._make_finding(
                    severity=sev,
                    title=f.get("title", "Missing test coverage"),
                    description=f.get("description", ""),
                    recommendation=f.get("recommendation", ""),
                    review_comment=f.get("review_comment", ""),
                    file_path=f.get("file_path"),
                    line_number=f.get("line_number"),
                    evidence=f.get("evidence"),
                    classification="recommendation",
                    origin="pre_existing",
                    affected_by_pr=False,
                ))
            logs.append(self._log(state, f"Found {len(raw_findings)} test coverage gaps"))
        except Exception as exc:
            logs.append(self._log(state, f"Agent error: {exc}", "error"))

        return {**state, "findings": findings, "logs": logs, "current_agent": self.name, "progress_percent": 85}
