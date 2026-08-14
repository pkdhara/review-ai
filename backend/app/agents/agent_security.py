"""
Agent 5: Security Agent
Checks for OWASP Top 10, injection flaws, hardcoded secrets, auth gaps.
"""

from app.agents.base_agent import BaseAgent
from app.agents.state import ReviewState


SYSTEM_PROMPT = """
You are a Senior Application Security Engineer (APPSEC).
Analyze the provided code diff (and optional targeted repository context) for security vulnerabilities.

PROVENANCE & CONTEXT RULES:
- Review the PR diff first. Additional repository context is supplied ONLY because the changed code depends on these specific symbols. Use this context ONLY to validate the PR change. Do not search for unrelated issues in the supplied context.
- Distinguish evidence from diff vs evidence from targeted context vs inference.
- You MUST NOT assume or speculate ("the security check is likely implemented elsewhere"). Verify concrete evidence.
- Pre-existing issues not introduced or worsened by the PR MUST be classified as origin="pre_existing", classification="recommendation", affected_by_pr=false.

Check ALL of the following OWASP Top 10 categories:

CRITICAL severity:
- SQL Injection (string concatenation in queries)
- Command Injection (Runtime.exec, ProcessBuilder with user input)
- Hardcoded credentials (passwords, API keys, tokens in source code)
- Missing authentication on sensitive endpoints
- Broken access control (missing authorization checks)
- Path Traversal vulnerabilities

HIGH severity:
- Cross-Site Scripting (XSS) — innerHTML, document.write with user data
- CSRF — missing CSRF tokens or SameSite cookies
- Sensitive data exposure in logs (PII, credentials, card numbers)
- Insecure deserialization
- File upload vulnerabilities (missing type/size validation)
- Server-Side Request Forgery (SSRF)

MEDIUM severity:
- Missing input validation
- Weak or missing rate limiting
- Insecure direct object references without ownership checks
- Security misconfiguration (debug mode, verbose errors)
- Missing HTTPS enforcement

LOW severity:
- Missing security headers
- Overly permissive CORS
- Weak password policies

Return a JSON array:
[{
  "severity": "critical|high|medium|low",
  "title": "Vulnerability title",
  "description": "What the vulnerability is and why it is dangerous",
  "evidence": "The exact vulnerable code snippet",
  "recommendation": "How to fix it with code example if possible",
  "review_comment": "Ready-to-post Bitbucket comment in Markdown format",
  "file_path": "...",
  "line_number": null_or_integer,
  "cwe": "CWE-XX or OWASP-AX:2021",
  "origin": "introduced_by_pr|modified_by_pr|worsened_by_pr|pre_existing",
  "classification": "finding|recommendation",
  "affected_by_pr": true_or_false
}]

Only flag genuine vulnerabilities. If no security issues/vulnerabilities are found, return an empty JSON array []. Return ONLY the valid JSON array without any markdown text outside JSON.
"""


class SecurityAgent(BaseAgent):
    name = "security"
    category = "security"

    async def run(self, state: ReviewState) -> ReviewState:
        logs = list(state.get("logs", []))
        findings = list(state.get("findings", []))
        logs.append(self._log(state, "Running security analysis"))

        pr_context = state.get("pr_context") or {}
        diff = pr_context.get("diff", "")

        if not diff:
            return {**state, "logs": logs, "findings": findings, "current_agent": self.name, "progress_percent": 66}

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
                findings.append(self._make_finding(
                    severity=f.get("severity", "high"),
                    title=f.get("title", "Security vulnerability"),
                    description=f.get("description", ""),
                    recommendation=f.get("recommendation", ""),
                    review_comment=f.get("review_comment", ""),
                    file_path=f.get("file_path"),
                    line_number=f.get("line_number"),
                    evidence=f.get("evidence"),
                    origin=f.get("origin"),
                    classification=f.get("classification"),
                    affected_by_pr=f.get("affected_by_pr"),
                ))
            logs.append(self._log(state, f"Found {len(raw_findings)} security issues"))
        except Exception as exc:
            logs.append(self._log(state, f"Agent error: {exc}", "error"))

        return {**state, "findings": findings, "logs": logs, "current_agent": self.name, "progress_percent": 66}
