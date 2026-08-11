"""
Agent 6: Refactoring Agent
Identifies refactoring opportunities and suggests design patterns.
"""

from app.agents.base_agent import BaseAgent
from app.agents.state import ReviewState


SYSTEM_PROMPT = """
You are a Senior Software Architect specializing in clean code and design patterns.
Analyze the provided code diff for refactoring opportunities.

Identify the following issues:

HIGH priority:
- God classes (>200 lines, >10 public methods, multiple responsibilities)
- Long methods (>30 lines or >5 cyclomatic complexity)
- Deep nesting (>3 levels of if/for/while)
- Duplicate logic across multiple methods or files

MEDIUM priority:
- Poor abstraction (implementation details leaking through interfaces)
- Missing design patterns where they would simplify code:
  * Strategy Pattern — for swappable algorithms or behavior
  * Factory/Builder Pattern — for complex object construction
  * Observer Pattern — for event-driven code
  * Command Pattern — for undo/redo or queued operations
  * Decorator Pattern — for augmenting behavior without subclassing
- Primitive obsession (using primitives where Value Objects would be clearer)
- Data clumps (same group of parameters appearing together repeatedly)

LOW priority:
- Dead code or commented-out code
- Inconsistent naming conventions
- Missing or misleading comments
- Over-engineering (unnecessary abstractions)

For each finding:
- Reference the specific code
- Provide a concrete refactored version if applicable

Return a JSON array:
[{
  "severity": "high|medium|low",
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
        diff = pr_context.get("diff", "")[:20000]

        if not diff:
            return {**state, "logs": logs, "findings": findings, "current_agent": self.name, "progress_percent": 75}

        user_prompt = f"""
Changed files: {[self.get_file_path(f) for f in pr_context.get('changed_files', [])]}

Diff:
{diff}
{self._get_class_structures_prompt(state)}
{self._get_changed_methods_prompt(state)}
"""

        try:
            raw_findings = await self._invoke_llm_json(SYSTEM_PROMPT, user_prompt)
            for f in raw_findings:
                findings.append(self._make_finding(
                    severity=f.get("severity", "medium"),
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
