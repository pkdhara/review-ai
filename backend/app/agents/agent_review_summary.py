"""
Agent 8: Review Summary Agent
Aggregates all findings, decouples PR findings from recommendations, computes risk score,
generates the executive summary, and produces LLM-written PR comments for each finding.

PR COMMENT ARCHITECTURE:
  - PR comments are generated in ONE single LLM call (same call as the summary).
  - The LLM writes one comment per finding, mapped by finding_id.
  - If the LLM omits a finding or fails entirely, the deterministic
    generate_finding_pr_comment() fallback is used — no extra LLM calls.
  - The LLM acts as a PRESENTATION LAYER ONLY: it cannot modify severity,
    classification, risk, origin, or affected_by_pr.
"""

import json
from collections import Counter
from typing import Dict, List, Any

from app.agents.base_agent import BaseAgent
from app.agents.state import FindingDict, ReviewState
from app.agents.pr_comment_generator import generate_finding_pr_comment
from app.agents.risk_calculator import (
    calculate_pr_risk_score,
    get_pr_defects_and_recommendations,
)


SYSTEM_PROMPT = """
You are a Principal Engineer conducting a final PR review.
You will produce TWO things:

1. An executive summary.
2. A list of individual PR comments — one short, respectful, ready-to-paste comment per finding.

=== OUTPUT SCHEMA ===
Return ONLY a JSON object with this exact schema:

{
  "executive_summary": "...",
  "risk_assessment": "...",
  "top_issues": ["issue title 1", "issue title 2"],
  "positive_observations": ["..."],
  "must_fix_before_merge": ["finding id or title"],
  "overall_recommendation": "APPROVE | REQUEST_CHANGES | NEEDS_DISCUSSION",
  "pr_comments": [
    {
      "finding_id": "<id provided in input>",
      "pr_comment": "<1-3 sentence respectful, specific PR comment>"
    }
  ]
}

=== PR COMMENT RULES ===
For each finding in pr_comments:
- Write exactly ONE short (1-3 sentence) comment per finding.
- The comment must be ready to paste directly into a PR/code-review tool.
- Be specific to this finding — reference the actual code element when helpful.
- Keep the tone professional and constructive.
- Use phrasing such as: "Could you please...", "Could you consider...", "It would be helpful to..."
- AVOID: "This is wrong", "You failed to", "Bad code", "You must fix".
- Do NOT mention: origin, classification, risk score, agent name, internal IDs, affected_by_pr.
- If origin is pre_existing: use "As a general improvement, could you consider..." — do NOT imply the PR introduced it.
- If classification is recommendation or category is refactoring: use softer phrasing ("Could you consider...").
- If category is security: briefly explain the security risk in plain terms.
- If category is test_coverage: use a concise suggestion like "Could you please add coverage for...".
- Base the comment ONLY on the provided finding data — do not invent facts.
- Return exactly one entry per supplied finding_id.

Be balanced and constructive. Return ONLY the JSON object, no markdown.
"""


class ReviewSummaryAgent(BaseAgent):
    name = "review_summary"
    category = "summary"

    async def run(self, state: ReviewState) -> ReviewState:
        logs = list(state.get("logs", []))
        all_findings = list(state.get("findings", []))
        logs.append(self._log(state, "Generating review summary and per-finding PR comments"))

        # Build a local index → finding mapping for LLM correlation.
        # We use a simple positional key like "fi_0", "fi_1" ONLY inside the LLM prompt.
        # We NEVER write these keys into the actual finding dicts to avoid corrupting UUID fields.
        idx_to_finding: Dict[str, Any] = {f"fi_{i}": f for i, f in enumerate(all_findings)}

        # Decouple PR defects vs Recommendations using central risk calculator rules
        pr_defects, recommendations = get_pr_defects_and_recommendations(all_findings)

        # Calculate deterministic risk score ONLY from PR defects (unchanged by PR comment logic)
        risk_score = calculate_pr_risk_score(all_findings)

        by_severity_defects = Counter(f.get("severity", "low") for f in pr_defects)
        by_category_defects = Counter(f.get("category", "general") for f in pr_defects)
        by_severity_recs = Counter(f.get("severity", "low") for f in recommendations)

        # Minimal finding representation for the LLM — only what it needs to write the comment.
        # NOTE: severity/classification/risk are sent READ-ONLY for context; the LLM is instructed
        # not to modify them and they are never taken back from the LLM response.
        findings_for_llm = [
            {
                "finding_id": llm_key,          # local index key — never persisted
                "title": f.get("title"),
                "category": f.get("category"),
                "severity": f.get("severity"),
                "origin": f.get("origin", "introduced_by_pr"),
                "classification": f.get("classification", "finding"),
                "file_path": f.get("file_path"),
                "line_number": f.get("line_number"),
                "description": (f.get("description") or "")[:300],
                "recommendation": (f.get("recommendation") or "")[:300],
            }
            for llm_key, f in idx_to_finding.items()
        ]

        user_prompt = f"""
Pull Request: {state.get('pr_context', {}).get('pr_title', 'Unknown')}
Branch: {state.get('pr_context', {}).get('source_branch', 'Unknown')}
Total PR Defects: {len(pr_defects)}
Total Recommendations (Pre-existing/Advisories): {len(recommendations)}
Calculated PR Risk Score: {risk_score}/100

PR Defects by Severity:
{json.dumps(dict(by_severity_defects), indent=2)}

Recommendations by Severity:
{json.dumps(dict(by_severity_recs), indent=2)}

Top Critical/High PR Defects:
{json.dumps(
    [{"title": f.get("title"), "severity": f.get("severity"), "category": f.get("category"),
      "description": (f.get("description") or "")[:150]}
     for f in pr_defects if f.get("severity") in ("critical", "high")][:8],
    indent=2
)}

Findings requiring individual PR comments (ALL findings — write one comment per finding_id):
{json.dumps(findings_for_llm, indent=2)}
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
            pr_comments_raw: List[Dict] = result.get("pr_comments", []) or []
        except Exception as exc:
            logs.append(self._log(state, f"Summary agent LLM error: {exc}", "error"))
            result = {
                "executive_summary": "Summary generation failed.",
                "overall_recommendation": "NEEDS_DISCUSSION",
            }
            llm_recommendation = "NEEDS_DISCUSSION"
            pr_comments_raw = []

        # ── Map LLM pr_comments back to authoritative findings — read ONLY text ───
        # We NEVER take back severity/classification/risk from the LLM response.
        comment_map: Dict[str, str] = {}
        if isinstance(pr_comments_raw, list):
            for item in pr_comments_raw:
                if isinstance(item, dict):
                    fid = str(item.get("finding_id") or "").strip()
                    txt = str(item.get("pr_comment") or "").strip()
                    if fid and txt:
                        comment_map[fid] = txt

        # Apply comments to findings using the local index map — authoritative finding dicts untouched
        for llm_key, f in idx_to_finding.items():
            if llm_key in comment_map:
                f["pr_comment"] = comment_map[llm_key]
            elif not f.get("pr_comment"):
                f["pr_comment"] = generate_finding_pr_comment(f)

        # ── Deterministic recommendation override (unchanged logic) ───────────
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
            **{k: v for k, v in result.items()
               if k not in ("overall_recommendation", "risk_score", "pr_comments")},
            "risk_score": risk_score,
            "overall_recommendation": recommendation,
        }

        logs.append(self._log(
            state,
            f"Review complete. Risk={risk_score}, Recommendation={recommendation}, "
            f"PR comments generated={len(comment_map)} LLM / "
            f"{len(all_findings) - len(comment_map)} fallback"
        ))

        return {
            **state,
            "findings": all_findings,
            "summary": summary,
            "logs": logs,
            "current_agent": self.name,
            "progress_percent": 100,
        }
