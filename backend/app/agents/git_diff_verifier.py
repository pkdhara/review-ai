"""
Git Diff Verifier & Finding Origin Classification Engine
──────────────────────────────────────────────────────────
Authoritatively parses Git diffs to determine whether finding evidence resides
on changed or unchanged lines, and verifies the finding's origin and classification.

Origin Types:
  - introduced_by_pr: Defect introduced by new/modified lines in PR (PR Finding).
  - modified_by_pr: Issue existed before, but PR changed behavior affecting it (PR Finding).
  - worsened_by_pr: Issue existed before, but PR materially worsened it (PR Finding).
  - pre_existing: Issue clearly existed before PR and is not modified/worsened by PR (Recommendation).
  - contextual: Surrounding code context (Recommendation/Advisory).
  - unknown: Origin cannot be determined — treated as Recommendation/Advisory.

Change Scope:
  - changed: Evidence is on a changed line in Git diff.
  - unchanged: Evidence is on an unchanged/context line in Git diff.
  - both: Evidence spans both changed and unchanged lines.

Classifications:
  - finding: Actionable PR defect (affects defect score, compliance, and recommendations).
  - recommendation: Pre-existing issue or advisory (does NOT affect PR defect score).
"""

from __future__ import annotations
import re
from typing import Dict, Optional, Set, List
from app.agents.state import FindingDict


def parse_diff_changed_lines(diff_str: str) -> Dict[str, Set[int]]:
    """
    Parses a unified diff string and returns a dictionary mapping normalized file paths
    to sets of changed/added line numbers in the new (target) file.
    """
    changed_lines: Dict[str, Set[int]] = {}
    if not diff_str:
        return changed_lines

    current_file: Optional[str] = None
    current_line = 0

    for line in diff_str.splitlines():
        # Match diff header: diff --git a/path b/path
        if line.startswith("diff --git "):
            parts = line.split(" b/")
            if len(parts) > 1:
                current_file = parts[-1].strip()
            else:
                m = re.search(r"b/(.+)$", line)
                current_file = m.group(1).strip() if m else None
            if current_file and current_file not in changed_lines:
                changed_lines[current_file] = set()
            continue

        # Match hunk header: @@ -old_start,old_count +new_start,new_count @@
        if line.startswith("@@ "):
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                current_line = int(m.group(1))
            continue

        if current_file is None:
            continue

        # Lines in hunk body:
        if line.startswith("+") and not line.startswith("+++"):
            changed_lines[current_file].add(current_line)
            current_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            # Old line deleted — does not advance new line counter
            pass
        elif line.startswith(" "):
            # Unchanged context line — advances line counter in new file
            current_line += 1

    return changed_lines


def _find_matching_file_key(file_path: str, changed_lines_map: Dict[str, Set[int]]) -> Optional[str]:
    """Finds the best matching key in changed_lines_map for a given file_path."""
    if not file_path:
        return None

    norm_path = file_path.replace("\\", "/").strip("/")

    # Exact match
    if norm_path in changed_lines_map:
        return norm_path

    # Suffix or basename match
    for k in changed_lines_map:
        norm_k = k.replace("\\", "/").strip("/")
        if norm_path.endswith(norm_k) or norm_k.endswith(norm_path):
            return k
        if norm_path.split("/")[-1] == norm_k.split("/")[-1]:
            return k

    return None


def extract_changed_symbols_from_diff(diff_str: str) -> Set[str]:
    """Extracts specific modified method/function call names from diff addition lines."""
    symbols: Set[str] = set()
    if not diff_str:
        return symbols

    for line in diff_str.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            matches = re.findall(r"\b([a-z][a-zA-Z0-9_]{3,})\s*\(", line)
            for m in matches:
                norm_m = m.lower()
                if norm_m not in {
                    "public", "private", "protected", "static", "final", "class", "void",
                    "return", "import", "package", "if", "else", "for", "while", "new",
                    "this", "super", "true", "false", "null", "string", "int", "boolean",
                    "get", "set", "is", "add", "remove", "tostring", "equals", "hashcode",
                    "run", "execute", "main", "log", "info", "debug", "error", "warn", "print"
                }:
                    symbols.add(norm_m)
    return symbols


def classify_and_verify_finding(
    finding: FindingDict,
    diff_str: str,
    pr_context: Optional[dict] = None
) -> FindingDict:
    """
    Verifies location of finding against Git diff and enforces origin/change_scope/classification metadata.
    """
    f = dict(finding)
    changed_lines_map = parse_diff_changed_lines(diff_str)
    file_path = f.get("file_path", "") or ""
    line_number = f.get("line_number")
    line_number_end = f.get("line_number_end")
    category = (f.get("category") or "").lower()
    title = (f.get("title") or "").lower()
    impact_type = (f.get("impact_type") or f.get("defect_impact") or "").lower()

    file_key = _find_matching_file_key(file_path, changed_lines_map)
    changed_set = changed_lines_map.get(file_key, set()) if file_key else set()

    # 1. Determine change_scope using Git diff as authoritative source
    if line_number is not None and file_key is not None:
        lines_to_check = [line_number]
        if line_number_end and line_number_end > line_number:
            lines_to_check = list(range(line_number, line_number_end + 1))

        changed_count = sum(1 for l in lines_to_check if l in changed_set)

        if changed_count == len(lines_to_check) and changed_count > 0:
            change_scope = "changed"
        elif changed_count > 0:
            change_scope = "both"
        else:
            change_scope = "unchanged"
    elif file_key is not None and len(changed_set) > 0:
        # File was changed in diff, but line number not specified
        evidence = (f.get("evidence") or "").strip()
        change_scope = "changed" if (evidence and evidence in diff_str) else "unchanged"
    else:
        change_scope = "unchanged"

    f["change_scope"] = change_scope

    # 2. Determine / Verify Origin & Behavioral Impact
    raw_origin = (f.get("origin") or "").lower()
    desc = (f.get("description") or "").lower() + " " + (f.get("title") or "").lower() + " " + (f.get("recommendation") or "").lower() + " " + (f.get("review_comment") or "").lower()

    # Symbol extraction for cross-file behavioral impact detection
    file_basename = file_path.split("/")[-1].split(".")[0].lower() if file_path else ""
    changed_symbols = extract_changed_symbols_from_diff(diff_str)
    referenced_changed_symbol = any(
        sym in desc for sym in changed_symbols
        if len(sym) >= 4 and sym != file_basename
    ) if changed_symbols else False

    # Check for behavioral impact flags in LLM output, description, or changed symbols
    has_behavioral_impact = referenced_changed_symbol or any(k in desc for k in [
        "behavior modified", "worsened by pr", "modified by pr", "upstream change",
        "pr changes condition", "pr alters flow", "pr introduced", "changed caller",
        "changed factory", "changed state", "modified_by_pr", "worsened_by_pr",
        "caller behavior", "changed interface", "changed signature", "changed return",
        "changed parameter", "changed feature flag", "changed contract", "changed method",
        "caller passes", "caller method"
    ])

    if raw_origin in ("introduced_by_pr", "modified_by_pr", "worsened_by_pr", "pre_existing", "contextual", "unknown"):
        origin = raw_origin
    else:
        if change_scope in ("changed", "both"):
            origin = "introduced_by_pr"
        elif has_behavioral_impact:
            origin = "modified_by_pr"
        else:
            origin = "pre_existing"

    # Enforce Git diff consistency rule:
    # If line is unchanged and origin was guessed as introduced_by_pr without behavioral impact, reclassify to pre_existing
    if change_scope == "unchanged" and origin == "introduced_by_pr" and not has_behavioral_impact:
        origin = "pre_existing"
    elif change_scope == "unchanged" and has_behavioral_impact and origin in ("pre_existing", "contextual", "unknown"):
        origin = "modified_by_pr"

    f["origin"] = origin

    # 3. Special Rule: Test Coverage findings are recommendations by default (0 risk)
    # UNLESS they represent an explicit functional regression / defect introduced by PR
    if category == "test_coverage" or f.get("agent_name") == "test_coverage":
        is_functional_defect = (
            impact_type in ("correctness", "runtime_failure", "data_integrity", "concurrency", "resource_exhaustion", "security", "production_failure")
            or any(k in desc for k in ["actual regression", "functional defect", "runtime error", "production failure", "data corruption", "introduced by pr", "regression defect"])
        )
        if not is_functional_defect:
            f["classification"] = "recommendation"
            f["affected_by_pr"] = False
            f["origin"] = "pre_existing"
            if f.get("severity") in ("critical", "high"):
                f["severity"] = "medium"

    # 4. Special Rule: Inferred requirements (INF-XX) are recommendations by default
    tags = [str(t).lower() for t in (f.get("tags") or [])]
    is_inferred = "inferred" in tags or "inf-" in title or title.startswith("expected behavior inferred") or title.startswith("potential requirement gap")
    if category in ("requirement", "requirement_validation") and is_inferred:
        f["classification"] = "recommendation"
        f["affected_by_pr"] = False

    # 5. Determine Classification & PR defect status for normal categories
    if f.get("classification") != "recommendation":
        is_pr_defect = origin in ("introduced_by_pr", "modified_by_pr", "worsened_by_pr")
        f["classification"] = "finding" if is_pr_defect else "recommendation"
        f["affected_by_pr"] = is_pr_defect
    else:
        f["affected_by_pr"] = False

    # 6. Severity Calibration Rules
    # Refactoring: LOW by default unless real functional defect
    if category == "refactoring" or f.get("agent_name") == "refactoring":
        is_real_defect = (
            impact_type in ("correctness", "runtime_failure", "data_integrity", "concurrency", "resource_exhaustion", "security", "production_failure")
            or any(k in desc for k in ["functional defect", "security vulnerability", "data corruption", "runtime crash", "performance crash", "inconsistent behavior"])
        )
        if not is_real_defect:
            sev = (f.get("severity") or "low").lower()
            if sev in ("high", "critical"):
                f["severity"] = "low"
            elif sev != "info":
                f["severity"] = "low"

    # Code Quality: MEDIUM by default unless real functional crash/bug/exception
    elif category == "code_quality" or f.get("agent_name") == "code_quality":
        is_real_defect = (
            impact_type in ("correctness", "runtime_failure", "data_integrity", "concurrency", "resource_exhaustion", "security", "production_failure")
            or any(k in desc for k in [
                "exception", "error", "npe", "nullpointer", "indexoutofbounds", "arithmeticexception",
                "stackoverflow", "illegalstateexception", "illegalargumentexception", "concurrentmodificationexception",
                "classcastexception", "outofmemory", "deadlock", "race condition", "data loss", "data corruption",
                "concurrency", "integer overflow", "resource leak", "memory leak", "crash", "production failure", "panic",
                "vulnerability", "defect", "bug", "fails", "failure", "incorrect", "unvalidated", "invalid"
            ])
        )
        if not is_real_defect:
            sev = (f.get("severity") or "medium").lower()
            if sev in ("high", "critical"):
                f["severity"] = "medium"

    # 7. Severity Rule for Pre-existing Issues & Recommendations
    if f.get("classification") == "recommendation" or not f.get("affected_by_pr"):
        sev = str(f.get("severity", "medium")).lower()
        if sev in ("critical", "high"):
            f["severity"] = "medium"
        elif origin == "unknown" and sev not in ("low", "info"):
            f["severity"] = "low"

    return f


def verify_all_findings(
    findings: List[FindingDict],
    diff_str: str,
    pr_context: Optional[dict] = None
) -> List[FindingDict]:
    """Applies classification and Git diff verification to a list of findings."""
    return [classify_and_verify_finding(f, diff_str, pr_context) for f in findings]
