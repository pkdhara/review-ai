"""
Unit tests for per-finding PR Comment feature.
Covers test cases 1-17 from the acceptance criteria.
"""
from __future__ import annotations
import pytest
from app.agents.pr_comment_generator import generate_finding_pr_comment


# ─── Helpers ────────────────────────────────────────────────────────────────

def make_finding(**overrides):
    base = {
        "id": "f1",
        "title": "SQL Query Construction via String Concatenation",
        "description": "Distributor IDs concatenated into SQL string.",
        "evidence": '+ "AND distributor_id IN (" + StringUtils.join(distributorIds, ",") + ")";',
        "recommendation": "Use parameterized queries instead of string concatenation.",
        "category": "security",
        "severity": "critical",
        "origin": "introduced_by_pr",
        "classification": "finding",
        "affected_by_pr": True,
    }
    base.update(overrides)
    return base


# ─── Test 1: One finding → one PR comment ────────────────────────────────────

def test_one_finding_one_comment():
    finding = make_finding()
    comment = generate_finding_pr_comment(finding)
    assert isinstance(comment, str)
    assert len(comment) > 0


# ─── Test 2: Two findings → two independent comments ─────────────────────────

def test_two_findings_two_independent_comments():
    f1 = make_finding(id="f1", category="security", title="SQL Injection", recommendation="Use parameterized queries")
    f2 = make_finding(id="f2", category="code_quality", title="Potential NullPointerException",
                      recommendation="Handle null before calling toString()")
    c1 = generate_finding_pr_comment(f1)
    c2 = generate_finding_pr_comment(f2)
    assert c1 != c2
    assert isinstance(c1, str) and isinstance(c2, str)


# ─── Test 3: PR comments are specific to their findings ──────────────────────

def test_comments_specific_to_finding():
    sql_finding = make_finding(
        id="f_sql",
        title="SQL Query String Concatenation",
        recommendation="Use parameterized placeholders for distributorIds"
    )
    null_finding = make_finding(
        id="f_null",
        category="code_quality",
        severity="high",
        title="Potential NullPointerException on price string conversion",
        recommendation="Handle null pricePerCase before calling toString()"
    )
    c_sql = generate_finding_pr_comment(sql_finding)
    c_null = generate_finding_pr_comment(null_finding)
    # SQL comment should reference SQL/parameterized
    assert "parameterized" in c_sql.lower() or "sql" in c_sql.lower()
    # Null comment should reference null/toString
    assert "null" in c_null.lower() or "tostring" in c_null.lower()


# ─── Test 4: Security finding → respectful security-specific wording ─────────

def test_security_finding_respectful_wording():
    finding = make_finding()
    comment = generate_finding_pr_comment(finding)
    # Starts with respectful phrasing
    assert comment.startswith("Could you please") or comment.startswith("Could you consider")
    # No harsh language
    for bad in ("This is wrong", "You failed", "must be fixed", "Bad code", "incorrect"):
        assert bad.lower() not in comment.lower(), f"Found harsh phrase: {bad!r}"
    # Should mention SQL or security risk
    assert "sql" in comment.lower() or "injection" in comment.lower() or "security" in comment.lower()


# ─── Test 5: Requirement finding → requirement-specific comment ───────────────

def test_requirement_finding_comment():
    finding = make_finding(
        id="f_req",
        category="requirement",
        severity="high",
        title="Foreign exchange setting not checked",
        recommendation="Verify that the target DC's FX setting is checked before selecting foreign sell price",
    )
    comment = generate_finding_pr_comment(finding)
    assert "Could you please verify" in comment or "verify" in comment.lower()


# ─── Test 6: Code quality finding → concise quality-specific comment ──────────

def test_code_quality_finding_comment():
    finding = make_finding(
        id="f_cq",
        category="code_quality",
        severity="medium",
        title="Unused variable assignment",
        recommendation="Remove unused variable to simplify the method",
        origin="introduced_by_pr",
        classification="finding",
    )
    comment = generate_finding_pr_comment(finding)
    assert isinstance(comment, str)
    assert "Could you please" in comment or "Could you consider" in comment


# ─── Test 7: Refactoring finding → softer recommendation wording ──────────────

def test_refactoring_finding_soft_wording():
    finding = make_finding(
        id="f_ref",
        category="refactoring",
        severity="low",
        title="Duplicate pricing logic",
        recommendation="Extract repeated logic into a shared helper method",
        classification="recommendation",
    )
    comment = generate_finding_pr_comment(finding)
    # Should use soft phrasing for refactoring
    assert "Could you consider" in comment
    # Must not sound like a blocking defect
    assert "must" not in comment.lower()
    assert "This is wrong" not in comment


# ─── Test 8: Test coverage → concise recommendation-style comment ──────────────

def test_test_coverage_finding_comment():
    finding = make_finding(
        id="f_tc",
        category="test_coverage",
        severity="medium",
        title="Missing test coverage for FX pricing fallback",
        recommendation="Add unit tests for foreign currency conversion logic",
        classification="recommendation",
    )
    comment = generate_finding_pr_comment(finding)
    assert "add" in comment.lower() or "coverage" in comment.lower() or "test" in comment.lower()
    assert len(comment) < 400  # kept concise


# ─── Test 9: Pre-existing finding → does NOT imply PR introduced it ───────────

def test_pre_existing_finding_does_not_blame_pr():
    finding = make_finding(
        id="f_pre",
        category="code_quality",
        severity="medium",
        title="Unused import",
        recommendation="Remove unused imports to keep the class clean",
        origin="pre_existing",
        classification="recommendation",
        affected_by_pr=False,
    )
    comment = generate_finding_pr_comment(finding)
    # Must NOT imply this PR introduced the issue
    assert "introduced" not in comment.lower()
    assert "this pr" not in comment.lower()
    assert "you introduced" not in comment.lower()
    # Should use "as a general improvement" or similar
    assert "improvement" in comment.lower() or "consider" in comment.lower()


# ─── Test 10: Internal metadata not exposed ───────────────────────────────────

def test_internal_metadata_not_in_comment():
    finding = make_finding(
        id="abc-123-xyz",
        classification="finding",
        origin="introduced_by_pr",
        affected_by_pr=True,
    )
    comment = generate_finding_pr_comment(finding)
    # None of these internal fields should appear in the comment text
    for meta in ("abc-123-xyz", "classification=", "origin=", "affected_by_pr", "risk_score"):
        assert meta not in comment, f"Internal metadata leaked: {meta!r}"


# ─── Test 11: Risk score unchanged after comment generation ───────────────────

def test_risk_score_unchanged():
    finding = make_finding(risk_score=72.5, severity="critical")
    generate_finding_pr_comment(finding)
    # Must not mutate the finding dict
    assert finding["risk_score"] == 72.5
    assert finding["severity"] == "critical"
    assert finding["classification"] == "finding"
    assert finding["origin"] == "introduced_by_pr"


# ─── Test 12: Empty recommendation falls back to title ───────────────────────

def test_empty_recommendation_falls_back_to_title():
    finding = make_finding(
        title="Missing null check for product price",
        recommendation="",
    )
    comment = generate_finding_pr_comment(finding)
    assert isinstance(comment, str)
    assert len(comment) > 10
    # Should mention something related to null or price
    assert "null" in comment.lower() or "price" in comment.lower() or "missing" in comment.lower()


# ─── Test 13: Multiple findings produce unique comments ───────────────────────

def test_multiple_findings_unique_comments():
    findings = [
        make_finding(id=f"f{i}", title=f"Issue #{i}", recommendation=f"Fix issue {i}")
        for i in range(5)
    ]
    comments = [generate_finding_pr_comment(f) for f in findings]
    # All must be strings, at least some must differ
    assert all(isinstance(c, str) for c in comments)
    assert len(set(comments)) > 1


# ─── Test 14: Null pr_comment does not break the generator ───────────────────

def test_null_pr_comment_field_does_not_break():
    finding = make_finding(pr_comment=None)
    comment = generate_finding_pr_comment(finding)
    assert isinstance(comment, str)
    assert len(comment) > 0


# ─── Test 15: Security with NullPointerException title gets both hints ────────

def test_npe_in_title_gets_null_rationale():
    finding = make_finding(
        id="f_npe",
        category="code_quality",
        severity="high",
        title="Potential NullPointerException on price parse",
        recommendation="Handle the possibility of a null price before calling toString()",
    )
    comment = generate_finding_pr_comment(finding)
    assert "null" in comment.lower() or "nullpointer" in comment.lower() or "runtime" in comment.lower()
