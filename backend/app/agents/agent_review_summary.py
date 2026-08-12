"""
Agent 8: Review Summary Agent
Aggregates all findings, decouples PR findings from recommendations, computes risk score,
and generates the final executive summary.
"""

import json
from collections import Counter
from typing import Dict, List

from app.agents.base_agent import BaseAgent
from app.agents.state import FindingDict, ReviewState


SYSTEM_PROMPT = """
You are a Principal Engineer conducting a final PR review summary.
Given all findings from multiple specialized review agents (divided into PR Findings/Defects and Pre-existing Recommendations), produce:

1. An executive summary (2-3 paragraphs) covering:
   - Overall assessment of the PR
   - Most critical PR defects that must be fixed
   - Key recommendations/pre-existing technical debt advisories
   - Positive observations
   - Overall recommendation

2. A risk assessment justifying the risk score (which is calculated ONLY from PR-introduced/modified defects).

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

from app.agents.risk_calculator import (
    calculate_pr_risk_score,
    get_pr_defects_and_recommendations,
)


class ReviewSummaryAgent(BaseAgent):
    name = "review_summary"
    category = "summary"

    async def run(self, state: ReviewState) -> ReviewState:
        logs = list(state.get("logs", []))
        all_findings = list(state.get("findings", []))
        logs.append(self._log(state, "Generating review summary"))

        # Decouple PR defects vs Recommendations using central risk calculator rules
        pr_defects, recommendations = get_pr_defects_and_recommendations(all_findings)

        # Calculate deterministic risk score ONLY from PR defects
        risk_score = calculate_pr_risk_score(all_findings)

        by_severity_defects = Counter(f.get("severity", "low") for f in pr_defects)
        by_category_defects = Counter(f.get("category", "general") for f in pr_defects)
        by_severity_recs = Counter(f.get("severity", "low") for f in recommendations)

        user_prompt = f"""
Pull Request: {state.get('pr_context', {}).get('pr_title', 'Unknown')}
Branch: {state.get('pr_context', {}).get('source_branch', 'Unknown')}
Total PR Defects: {len(pr_defects)}
Total Recommendations (Pre-existing/Advisories): {len(recommendations)}
PR Risk Score: {risk_score}/100

PR Defects by Severity:
{json.dumps(dict(by_severity_defects), indent=2)}

Recommendations by Severity:
{json.dumps(dict(by_severity_recs), indent=2)}

Top Critical/High PR Defects:
{json.dumps(
    [{"title": f.get("title"), "severity": f.get("severity"), "category": f.get("category"), "description": f.get("description", "")[:200]}
     for f in pr_defects if f.get("severity") in ("critical", "high")][:10],
    indent=2
)}
"""

        try:
            result = await self._invoke_llm_json(
                SYSTEM_PROMPT,
                user_prompt,
                context_mode="findings_only",
                repository_context=False,
                diff_chars=0,
                context_chars=0,
            )
            llm_recommendation = result.get("overall_recommendation", "NEEDS_DISCUSSION")
        except Exception as exc:
            logs.append(self._log(state, f"Summary agent error: {exc}", "error"))
            result = {"executive_summary": "Summary generation failed.", "overall_recommendation": "NEEDS_DISCUSSION"}
            llm_recommendation = "NEEDS_DISCUSSION"

        # ── Deterministic recommendation override ─────────────────────────────
        # Rules apply strictly to PR Defects (NOT pre-existing recommendations)
        has_critical = by_severity_defects.get("critical", 0) > 0
        has_high     = by_severity_defects.get("high", 0) > 0
        has_medium   = by_severity_defects.get("medium", 0) > 0

        if has_critical or has_high:
            recommendation = "REQUEST_CHANGES"
        elif has_medium:
            recommendation = "NEEDS_DISCUSSION"
        else:
            recommendation = llm_recommendation if llm_recommendation in (
                "APPROVE", "NEEDS_DISCUSSION", "REQUEST_CHANGES"
            ) else "APPROVE"

        summary: Dict = {
            "total_findings": len(all_findings),
            "pr_defects_count": len(pr_defects),
            "recommendations_count": len(recommendations),
            "findings_by_severity": dict(by_severity_defects),
            "findings_by_category": dict(by_category_defects),
            "recommendations_by_severity": dict(by_severity_recs),
            **{k: v for k, v in result.items() if k not in ("overall_recommendation", "risk_score")},
            "risk_score": risk_score,
            "overall_recommendation": recommendation,
        }

        logs.append(self._log(state, f"Review complete. Risk={risk_score}, Recommendation={recommendation}"))

        return {
            **state,
            "summary": summary,
            "logs": logs,
            "current_agent": self.name,
            "progress_percent": 100,
        }
