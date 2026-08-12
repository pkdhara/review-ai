"""
Agent 5: Security Agent
Checks for OWASP Top 10, injection flaws, hardcoded secrets, auth gaps.
"""

from app.agents.base_agent import BaseAgent
from app.agents.state import ReviewState


SYSTEM_PROMPT = """
You are a Senior Application Security Engineer (APPSEC).
Analyze the provided code diff for security vulnerabilities.

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
  "cwe": "CWE-XX or OWASP-AX:2021"
}]

Only flag genuine vulnerabilities. Return ONLY the JSON array.
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
                findings.append(self._make_finding(
                    severity=f.get("severity", "high"),
                    title=f.get("title", "Security vulnerability"),
                    description=f.get("description", ""),
                    recommendation=f.get("recommendation", ""),
                    review_comment=f.get("review_comment", ""),
                    file_path=f.get("file_path"),
                    line_number=f.get("line_number"),
                    evidence=f.get("evidence"),
                ))
            logs.append(self._log(state, f"Found {len(raw_findings)} security issues"))
        except Exception as exc:
            logs.append(self._log(state, f"Agent error: {exc}", "error"))

        return {**state, "findings": findings, "logs": logs, "current_agent": self.name, "progress_percent": 66}
