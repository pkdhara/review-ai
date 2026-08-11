"""
Agent 8: Review Summary Agent
Aggregates all findings, removes duplicates, computes risk score, and generates
the final executive summary.
"""

import json
from collections import Counter
from typing import Dict, List

from app.agents.base_agent import BaseAgent
from app.agents.state import FindingDict, ReviewState


SYSTEM_PROMPT = """
You are a Principal Engineer conducting a final PR review summary.
Given all findings from multiple specialized review agents, produce:

1. An executive summary (2-3 paragraphs) covering:
   - Overall assessment of the PR
   - Most critical issues that must be fixed
   - Positive observations
   - Overall recommendation

2. A risk assessment justifying the risk score.

Return a JSON object:
{
  "executive_summary": "...",
  "risk_assessment": "...",
  "top_issues": ["issue title 1", "issue title 2", ...],
  "positive_observations": ["..."],
  "must_fix_before_merge": ["finding id or title"],
  "overall_recommendation": "APPROVE | REQUEST_CHANGES | NEEDS_DISCUSSION"
}

Be balanced and constructive. Return ONLY the JSON object.
"""

SEVERITY_WEIGHTS = {
    "critical": 25,
    "high": 10,
    "medium": 4,
    "low": 1,
    "info": 0,
}


class ReviewSummaryAgent(BaseAgent):
    name = "review_summary"
    category = "summary"

    def _calculate_risk_score(self, findings: List[FindingDict]) -> float:
        """Calculate a 0–100 risk score based on finding severities."""
        raw = sum(SEVERITY_WEIGHTS.get(f.get("severity", "low"), 0) for f in findings)
        return min(100.0, round(raw, 1))

    async def run(self, state: ReviewState) -> ReviewState:
        logs = list(state.get("logs", []))
        findings = list(state.get("findings", []))
        logs.append(self._log(state, "Generating review summary"))

        risk_score = self._calculate_risk_score(findings)

        by_severity = Counter(f.get("severity", "low") for f in findings)
        by_category = Counter(f.get("category", "general") for f in findings)

        user_prompt = f"""
Pull Request: {state.get('pr_context', {}).get('pr_title', 'Unknown')}
Branch: {state.get('pr_context', {}).get('source_branch', 'Unknown')}
Total Findings: {len(findings)}
Risk Score: {risk_score}/100

Findings by Severity:
{json.dumps(dict(by_severity), indent=2)}

Findings by Category:
{json.dumps(dict(by_category), indent=2)}

Top Critical/High Findings:
{json.dumps(
    [{"title": f.get("title"), "severity": f.get("severity"), "category": f.get("category"), "description": f.get("description", "")[:200]}
     for f in findings if f.get("severity") in ("critical", "high")][:10],
    indent=2
)}
"""

        try:
            result = await self._invoke_llm_json(SYSTEM_PROMPT, user_prompt)
            llm_recommendation = result.get("overall_recommendation", "NEEDS_DISCUSSION")
        except Exception as exc:
            logs.append(self._log(state, f"Summary agent error: {exc}", "error"))
            result = {"executive_summary": "Summary generation failed.", "overall_recommendation": "NEEDS_DISCUSSION"}
            llm_recommendation = "NEEDS_DISCUSSION"

        # ── Deterministic recommendation override ─────────────────────────────
        # Rules are hard — the LLM cannot override them.
        has_critical = by_severity.get("critical", 0) > 0
        has_high     = by_severity.get("high", 0) > 0
        has_medium   = by_severity.get("medium", 0) > 0

        if has_critical or has_high:
            recommendation = "REQUEST_CHANGES"
        elif has_medium:
            # Any medium finding → at minimum NEEDS_DISCUSSION, never APPROVE
            recommendation = "NEEDS_DISCUSSION"
        else:
            # Only low/info findings — trust the LLM
            recommendation = llm_recommendation if llm_recommendation in (
                "APPROVE", "NEEDS_DISCUSSION", "REQUEST_CHANGES"
            ) else "APPROVE"

        summary: Dict = {
            "total_findings": len(findings),
            "findings_by_severity": dict(by_severity),
            "findings_by_category": dict(by_category),
            "risk_score": risk_score,
            "overall_recommendation": recommendation,
            **{k: v for k, v in result.items() if k != "overall_recommendation"},
        }

        logs.append(self._log(state, f"Review complete. Risk={risk_score}, Recommendation={recommendation}"))

        return {
            **state,
            "summary": summary,
            "logs": logs,
            "current_agent": self.name,
            "progress_percent": 100,
        }
