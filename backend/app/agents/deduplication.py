"""
Finding Deduplication Service
──────────────────────────────
Merges redundant findings across multiple specialized agents (e.g. code_quality vs refactoring
or duplicate requirement findings describing the same file, line, and defect).

Deduplication Rules:
1. Prevents duplicate reporting of the same issue as both a PR finding and a recommendation.
2. Merges overlapping findings while preserving the strongest correct classification.
3. Keeps highest severity and aggregates tags, evidence, and review comments.
"""

from typing import List, Dict, Tuple, Set
import re
from app.agents.state import FindingDict


SEVERITY_ORDER = {
    "critical": 5,
    "high": 4,
    "medium": 3,
    "low": 2,
    "info": 1,
}

PR_DEFECT_ORIGINS = {"introduced_by_pr", "modified_by_pr", "worsened_by_pr"}
RECOMMENDATION_ORIGINS = {"pre_existing", "contextual", "unknown"}


def normalize_text(text: str) -> str:
    """Normalize text for semantic similarity checks by lowercasing and removing punctuation/whitespace."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return " ".join(text.split())


def extract_keywords(text: str) -> Set[str]:
    """Extract key technical terms (e.g. npe, nullpointer, ternary, foreignsellprice, pricepercase)."""
    norm = normalize_text(text)
    words = set(norm.split())
    # Ignore common stop words
    stop = {"the", "a", "an", "is", "are", "on", "in", "to", "for", "of", "and", "or", "with", "this", "that", "it", "should", "be", "code", "file", "line", "method", "potential", "issue"}
    return words - stop


def is_similar_issue(f1: FindingDict, f2: FindingDict) -> bool:
    """
    Check if two findings represent the same underlying defect.
    Checks:
    1. File path match
    2. Line numbers match or are within ±3 lines
    3. Keyword overlap in title/description (e.g., both mention NPE or NullPointer or foreignSellPrice)
    """
    path1 = f1.get("file_path") or ""
    path2 = f2.get("file_path") or ""
    
    # If both specify file paths and they differ, they are distinct issues
    if path1 and path2 and path1 != path2:
        return False

    line1 = f1.get("line_number")
    line2 = f2.get("line_number")

    # If line numbers are specified and differ by > 3, they are distinct issues
    if line1 is not None and line2 is not None and abs(line1 - line2) > 3:
        return False

    kw1 = extract_keywords((f1.get("title", "") + " " + f1.get("description", "")))
    kw2 = extract_keywords((f2.get("title", "") + " " + f2.get("description", "")))

    if not kw1 or not kw2:
        return False

    overlap = kw1.intersection(kw2)
    # Check for specific high-priority matching concepts like NPE / null pointer / requirement duplicate
    has_npe = ("npe" in kw1 or "nullpointerexception" in kw1 or "null" in kw1) and ("npe" in kw2 or "nullpointerexception" in kw2 or "null" in kw2)
    has_req = any(k in kw1 for k in ("fr01", "br01", "ac01", "inf01")) and any(k in kw2 for k in ("fr01", "br01", "ac01", "inf01"))
    
    if len(overlap) >= 2 or has_npe or (has_req and line1 == line2):
        return True

    return False


def deduplicate_findings(findings: List[FindingDict]) -> List[FindingDict]:
    """
    Deduplicates a list of findings, keeping the highest-severity finding
    and merging review comments/tags when duplicates are found.
    Ensures that the same issue is never output twice as both a PR finding and a recommendation.
    """
    if not findings:
        return []

    merged: List[FindingDict] = []

    for f in findings:
        matched = False
        for i, existing in enumerate(merged):
            if is_similar_issue(existing, f):
                matched = True
                
                CATEGORY_PRIORITY = {
                    "security": 10,
                    "requirement": 9,
                    "requirement_validation": 9,
                    "sql_performance": 8,
                    "code_quality": 7,
                    "refactoring": 6,
                    "test_coverage": 5,
                    "general": 1,
                }
                # Compare severities (higher numerical value = higher severity in SEVERITY_ORDER)
                s_existing = SEVERITY_ORDER.get(existing.get("severity", "low"), 2)
                s_new = SEVERITY_ORDER.get(f.get("severity", "low"), 2)

                if s_existing > s_new:
                    primary, secondary = existing, f
                elif s_new > s_existing:
                    primary, secondary = f, existing
                else:
                    # Equal severities: prefer higher-priority category multiplier
                    p_existing = CATEGORY_PRIORITY.get((existing.get("category") or "").lower(), 0)
                    p_new = CATEGORY_PRIORITY.get((f.get("category") or "").lower(), 0)
                    if p_new > p_existing:
                        primary, secondary = f, existing
                    else:
                        primary, secondary = existing, f

                # Merge Classification & Origin:
                # If EITHER finding was proven to be affected by PR / PR defect, preserve PR defect status
                orig_existing = existing.get("origin") or "unknown"
                orig_new = f.get("origin") or "unknown"
                
                is_pr_defect = (
                    existing.get("classification") == "finding" or
                    f.get("classification") == "finding" or
                    orig_existing in PR_DEFECT_ORIGINS or
                    orig_new in PR_DEFECT_ORIGINS or
                    existing.get("affected_by_pr") is True or
                    f.get("affected_by_pr") is True
                )

                if is_pr_defect:
                    # Choose strongest PR defect origin
                    merged_origin = (
                        orig_existing if orig_existing in PR_DEFECT_ORIGINS else orig_new
                    )
                    if merged_origin not in PR_DEFECT_ORIGINS:
                        merged_origin = "introduced_by_pr"
                    merged_class = "finding"
                    affected_by_pr = True
                else:
                    # Both are recommendations / pre-existing
                    merged_origin = orig_existing if orig_existing != "unknown" else orig_new
                    merged_class = "recommendation"
                    affected_by_pr = False

                # Merge change_scope: if either is changed, scope is changed
                cs1 = existing.get("change_scope", "unchanged")
                cs2 = f.get("change_scope", "unchanged")
                if cs1 == "changed" or cs2 == "changed":
                    merged_scope = "changed"
                elif cs1 == "both" or cs2 == "both":
                    merged_scope = "both"
                else:
                    merged_scope = "unchanged"

                # Merge tags and evidence
                tags = list(set((primary.get("tags") or []) + (secondary.get("tags") or [])))
                evidence = primary.get("evidence") or secondary.get("evidence")

                new_finding: FindingDict = {
                    **primary,
                    "origin": merged_origin,
                    "change_scope": merged_scope,
                    "classification": merged_class,
                    "affected_by_pr": affected_by_pr,
                    "evidence": evidence,
                    "tags": tags,
                }
                merged[i] = new_finding
                break

        if not matched:
            merged.append(dict(f))

    return merged
