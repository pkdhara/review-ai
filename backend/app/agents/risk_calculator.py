"""
Central Risk Calculator & Finding Classifier Service
─────────────────────────────────────────────────────
Enforces deterministic, category-aware risk scoring for PR reviews.

Key Rules:
1. Only actual PR defects (introduced/modified/worsened by PR) contribute to PR risk score.
2. Pre-existing findings, recommendations, and test coverage findings contribute 0 to PR risk.
3. Category-aware weighting:
   - Security: 1.25x
   - Requirement Validation: 1.10x
   - SQL Performance: 1.00x
   - Code Quality: 0.75x
   - Refactoring: 0.50x
   - Test Coverage: 0.00x
4. Deduplication runs prior to risk calculation to prevent duplicate findings from inflating risk.
"""

from typing import List, Tuple, Dict, Any
from app.agents.state import FindingDict
from app.agents.deduplication import deduplicate_findings

# Base severity weights
SEVERITY_WEIGHTS: Dict[str, float] = {
    "critical": 25.0,
    "high": 12.0,
    "medium": 4.0,
    "low": 1.0,
    "info": 0.0,
}

# Category multipliers for PR defects
CATEGORY_MULTIPLIERS: Dict[str, float] = {
    "security": 1.25,
    "requirement": 1.10,
    "requirement_validation": 1.10,
    "sql_performance": 1.00,
    "code_quality": 0.75,
    "refactoring": 0.50,
    "test_coverage": 0.50,
    "general": 1.00,
}

PR_DEFECT_ORIGINS = {"introduced_by_pr", "modified_by_pr", "worsened_by_pr"}


def is_pr_defect(finding: FindingDict) -> bool:
    """
    Determines if a finding is an actual PR defect that contributes to risk score.
    Returns False for pre-existing issues, recommendations, and non-defect findings.
    """
    if not isinstance(finding, dict):
        return False

    classification = (finding.get("classification") or "").lower()
    if classification == "recommendation":
        return False

    affected = finding.get("affected_by_pr")
    if affected is False:
        return False

    origin = (finding.get("origin") or "").lower()
    if origin and origin not in PR_DEFECT_ORIGINS:
        return False

    return True


def calculate_finding_risk(finding: FindingDict) -> float:
    """
    Calculates the category-aware risk score contribution for a single finding.
    Returns 0.0 if the finding is not an actual PR defect.
    """
    if not is_pr_defect(finding):
        return 0.0

    severity = (finding.get("severity") or "medium").lower()
    base_weight = SEVERITY_WEIGHTS.get(severity, 4.0)

    category = (finding.get("category") or "general").lower()
    multiplier = CATEGORY_MULTIPLIERS.get(category, 1.0)

    return round(base_weight * multiplier, 2)


def get_pr_defects_and_recommendations(
    findings: List[FindingDict]
) -> Tuple[List[FindingDict], List[FindingDict]]:
    """
    Decouples a list of findings into PR defects vs recommendations/advisories.
    """
    pr_defects: List[FindingDict] = []
    recommendations: List[FindingDict] = []

    for f in findings:
        if is_pr_defect(f):
            pr_defects.append(f)
        else:
            recommendations.append(f)

    return pr_defects, recommendations


def calculate_pr_risk_score(findings: List[FindingDict]) -> float:
    """
    Calculates the deterministic PR risk score (0.0 to 100.0) from a list of findings.
    Automatically deduplicates findings first.
    """
    if not findings:
        return 0.0

    # Ensure findings are deduplicated before scoring
    deduped = deduplicate_findings(findings)

    total_risk = 0.0
    for f in deduped:
        total_risk += calculate_finding_risk(f)

    return min(100.0, round(total_risk, 1))
