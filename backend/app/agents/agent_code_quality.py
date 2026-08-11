"""
Agent 3: Code Quality Agent
Reviews clean code, SOLID, design patterns, Spring Boot and Angular concerns.
"""

from app.agents.base_agent import BaseAgent
from app.agents.state import ReviewState


SYSTEM_PROMPT = """
You are a Senior Software Engineer and Clean Code advocate.
Review the provided code diff for quality issues.

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
  "severity": "critical|high|medium|low|info",
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
        diff = pr_context.get("diff", "")[:20000]

        if not diff:
            return {**state, "logs": logs, "findings": findings, "current_agent": self.name, "progress_percent": 42}

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
                    title=f.get("title", "Code quality issue"),
                    description=f.get("description", ""),
                    recommendation=f.get("recommendation", ""),
                    review_comment=f.get("review_comment", ""),
                    file_path=f.get("file_path"),
                    line_number=f.get("line_number"),
                    evidence=f.get("evidence"),
                ))
            logs.append(self._log(state, f"Found {len(raw_findings)} code quality issues"))
        except Exception as exc:
            logs.append(self._log(state, f"Agent error: {exc}", "error"))

        return {**state, "findings": findings, "logs": logs, "current_agent": self.name, "progress_percent": 42}
