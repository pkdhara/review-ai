"""
Agent 6: Refactoring Agent
Identifies refactoring opportunities and suggests design patterns.
"""

from app.agents.base_agent import BaseAgent
from app.agents.state import ReviewState


SYSTEM_PROMPT = """
You are a Senior Software Architect specializing in clean code and design patterns.
Analyze the provided code diff for refactoring opportunities.

SEVERITY CALIBRATION RULE:
Normal refactoring recommendations (duplicate code, duplicate validation logic, extract-method suggestions, simplifying complex code, design pattern suggestions) MUST be LOW severity (`severity: 'low'`).
Do NOT mark simple duplication or clean-up suggestions as HIGH or CRITICAL severity unless there is a demonstrable functional defect, security flaw, or crash.

Identify the following issues:

LOW priority (default for refactoring):
- Duplicate code or validation logic across methods or classes
- Extract-method or extract-service opportunities
- God classes (>200 lines, >10 public methods, multiple responsibilities)
- Long methods (>30 lines or >5 cyclomatic complexity)
- Deep nesting (>3 levels of if/for/while)
- Primitive obsession or missing design patterns (Strategy, Factory, Builder)
- Dead code or commented-out code
- Inconsistent naming conventions

For each finding:
- Reference the specific code
- Provide a concrete refactored version if applicable

Return a JSON array:
[{
  "severity": "low",
  "title": "...",
  "description": "...",
  "evidence": "The problematic code section",
  "recommendation": "Suggested refactoring with code example",
  "review_comment": "Ready-to-post Bitbucket markdown comment",
  "file_path": "...",
  "line_number": null_or_integer,
  "pattern_suggested": "Strategy|Factory|Builder|Observer|null"
}]

Return ONLY the JSON array.
"""


class RefactoringAgent(BaseAgent):
    name = "refactoring"
    category = "refactoring"

    async def run(self, state: ReviewState) -> ReviewState:
        logs = list(state.get("logs", []))
        findings = list(state.get("findings", []))
        logs.append(self._log(state, "Identifying refactoring opportunities"))

        pr_context = state.get("pr_context") or {}
        diff = pr_context.get("diff", "")

        if not diff:
            return {**state, "logs": logs, "findings": findings, "current_agent": self.name, "progress_percent": 75}

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
                sev = f.get("severity", "low")
                if sev in ("high", "critical"):
                    sev = "low"
                findings.append(self._make_finding(
                    severity=sev,
                    title=f.get("title", "Refactoring opportunity"),
                    description=f.get("description", ""),
                    recommendation=f.get("recommendation", ""),
                    review_comment=f.get("review_comment", ""),
                    file_path=f.get("file_path"),
                    line_number=f.get("line_number"),
                    evidence=f.get("evidence"),
                ))
            logs.append(self._log(state, f"Found {len(raw_findings)} refactoring opportunities"))
        except Exception as exc:
            logs.append(self._log(state, f"Agent error: {exc}", "error"))

        return {**state, "findings": findings, "logs": logs, "current_agent": self.name, "progress_percent": 75}
