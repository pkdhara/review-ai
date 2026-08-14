"""
Deterministic fallback PR comment generator.

Used when:
  - The LLM batch call omits a finding
  - The LLM call fails entirely

Generates a short, respectful, ready-to-paste PR comment from existing
finding data without any additional LLM calls.

This is a PRESENTATION LAYER utility only.
It MUST NOT modify severity, classification, risk, origin, or affected_by_pr.
"""
from __future__ import annotations

from typing import Any, Dict


def generate_finding_pr_comment(finding: Dict[str, Any]) -> str:
    """
    Generate a concise, respectful PR comment from a finalized finding dict.
    Returns 1-3 sentence string suitable for pasting directly into a PR.
    """
    title = (finding.get("title") or "").strip()
    recommendation = (finding.get("recommendation") or "").strip()
    category = (finding.get("category") or "").lower()
    severity = (finding.get("severity") or "").lower()
    origin = (finding.get("origin") or "introduced_by_pr").lower()
    classification = (finding.get("classification") or "finding").lower()

    # Choose core action text — prefer recommendation, fall back to title
    core = recommendation if recommendation else title
    # Strip leading bullet/numbering
    import re
    core = re.sub(r"^\s*[-•*\d.]+\s*", "", core).strip()
    core = core.rstrip(".")

    # ── Prefix by classification / origin ────────────────────────────────────
    is_pre_existing = origin == "pre_existing"
    is_rec = classification == "recommendation" or category in ("refactoring",)

    if is_pre_existing:
        prefix = "As a general improvement, could you consider"
    elif is_rec or category == "refactoring":
        prefix = "Could you consider"
    elif category == "requirement":
        prefix = "Could you please verify that"
    else:
        prefix = "Could you please"

    # ── Build action phrase ───────────────────────────────────────────────────
    IMPERATIVE_VERBS = {
        "use", "add", "fix", "refactor", "extract", "handle", "check",
        "update", "replace", "remove", "ensure", "optimize", "parameterize",
        "validate", "convert", "implement", "verify", "avoid", "wrap",
        "move", "switch", "simplify", "migrate", "return", "limit",
    }
    words = core.split()
    if words and words[0].lower() in IMPERATIVE_VERBS:
        action = words[0].lower() + (" " + " ".join(words[1:]) if len(words) > 1 else "")
    elif category == "requirement":
        # e.g. "Could you please verify that the DC's FX setting is checked"
        action = core[0].lower() + core[1:] if core else "this requirement is met"
    else:
        action = core[0].lower() + core[1:] if core else "review this section"

    comment = f"{prefix} {action}?"

    # ── Append short rationale by category ───────────────────────────────────
    lower_title = title.lower()
    lower_rec = recommendation.lower()

    if category == "security":
        if "sql" in lower_title or "sql" in lower_rec or "inject" in lower_title:
            comment += " This would help prevent potential SQL injection risks."
        else:
            comment += " This will help improve the security of this component."
    elif category == "sql_performance" or "n+1" in lower_title or "performance" in lower_title:
        comment += " This will reduce database query overhead."
    elif category == "test_coverage":
        pass  # Keep test comments short — the request says "short"
    elif "null" in lower_title or "nullpointer" in lower_title or "npe" in lower_title:
        comment += " This would avoid a potential runtime NullPointerException."

    return comment.strip()
