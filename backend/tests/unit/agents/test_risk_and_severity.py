"""
Unit Tests for Finding Severity Calibration and Deterministic Risk Score Calculation
─────────────────────────────────────────────────────────────────────────────────────
Tests all 12 scenarios outlined in ReviewAI Severity & Risk Scoring Policy.
"""

import pytest
from app.agents.risk_calculator import (
    calculate_pr_risk_score,
    calculate_finding_risk,
    is_pr_defect,
    get_pr_defects_and_recommendations,
)
from app.agents.deduplication import deduplicate_findings
from app.agents.git_diff_verifier import classify_and_verify_finding, verify_all_findings


def test_01_missing_test_is_recommendation_and_zero_risk():
    finding = {
        "title": "Missing unit test for Edicom810InvoiceMessage",
        "category": "test_coverage",
        "severity": "high",
        "file_path": "com/fresh/Edicom810InvoiceMessage.java",
        "line_number": 45,
        "origin": "introduced_by_pr",
    }
    verified = classify_and_verify_finding(finding, "diff --git a/com/fresh/Edicom810InvoiceMessage.java b/com/fresh/Edicom810InvoiceMessage.java\n@@ -40,10 +40,10 @@\n+ new line")
    
    assert verified["classification"] == "recommendation"
    assert verified["affected_by_pr"] is False
    assert is_pr_defect(verified) is False
    assert calculate_finding_risk(verified) == 0.0


def test_02_duplicate_code_is_low_severity_and_minimal_risk():
    finding = {
        "title": "Duplicate validation logic across classes",
        "category": "refactoring",
        "severity": "high",
        "file_path": "com/fresh/Edicom810InvoiceMessage.java",
        "line_number": 50,
        "origin": "introduced_by_pr",
    }
    verified = classify_and_verify_finding(finding, "diff --git a/com/fresh/Edicom810InvoiceMessage.java b/com/fresh/Edicom810InvoiceMessage.java\n@@ -50,5 +50,5 @@\n+ duplicate line")

    assert verified["severity"] == "low"
    risk = calculate_finding_risk(verified)
    assert risk == 0.5  # 1.0 base * 0.5 refactoring multiplier


def test_03_normal_code_quality_is_medium_severity():
    finding = {
        "title": "Complex inline expressions and poor variable naming",
        "category": "code_quality",
        "severity": "high",
        "file_path": "com/fresh/InvoiceService.java",
        "line_number": 120,
        "origin": "introduced_by_pr",
    }
    verified = classify_and_verify_finding(finding, "diff --git a/com/fresh/InvoiceService.java b/com/fresh/InvoiceService.java\n@@ -120,5 +120,5 @@\n+ complex expr")

    assert verified["severity"] == "medium"
    risk = calculate_finding_risk(verified)
    assert risk == 3.0  # 4.0 base * 0.75 code_quality multiplier


def test_04_real_functional_defect_is_high_severity():
    finding = {
        "title": "Uncaught NullPointerException in invoice export loop",
        "description": "NPE crash occurring on null customer ID in production path",
        "category": "code_quality",
        "severity": "high",
        "file_path": "com/fresh/InvoiceService.java",
        "line_number": 130,
        "origin": "introduced_by_pr",
    }
    verified = classify_and_verify_finding(finding, "diff --git a/com/fresh/InvoiceService.java b/com/fresh/InvoiceService.java\n@@ -130,5 +130,5 @@\n+ crash line")

    assert verified["severity"] == "high"
    risk = calculate_finding_risk(verified)
    assert risk == 9.0  # 12.0 base * 0.75 code_quality multiplier


def test_05_critical_security_vulnerability_is_very_high_risk():
    finding = {
        "title": "SQL Injection in custom query builder",
        "description": "Unsanitized user input concatenated into SQL query string",
        "category": "security",
        "severity": "critical",
        "file_path": "com/fresh/UserRepository.java",
        "line_number": 85,
        "origin": "introduced_by_pr",
        "classification": "finding",
        "affected_by_pr": True,
    }
    risk = calculate_finding_risk(finding)
    assert risk == 31.25  # 25.0 base * 1.25 security multiplier


def test_06_pre_existing_high_finding_is_zero_risk():
    finding = {
        "title": "Pre-existing SQL query performance issue",
        "category": "sql_performance",
        "severity": "high",
        "file_path": "com/fresh/LegacyExport.java",
        "line_number": 300,
        "origin": "pre_existing",
        "classification": "recommendation",
        "affected_by_pr": False,
    }
    assert is_pr_defect(finding) is False
    assert calculate_finding_risk(finding) == 0.0


def test_07_affected_by_pr_false_is_zero_risk():
    finding = {
        "title": "Advisory comment on unchanged utility class",
        "category": "general",
        "severity": "medium",
        "file_path": "com/fresh/StringUtils.java",
        "line_number": 15,
        "origin": "contextual",
        "classification": "recommendation",
        "affected_by_pr": False,
    }
    assert calculate_finding_risk(finding) == 0.0


def test_08_duplicate_findings_deduplicated_and_counted_once():
    f1 = {
        "title": "N+1 query fetching restaurant records in loop",
        "description": "DB query inside loop",
        "category": "sql_performance",
        "severity": "high",
        "file_path": "com/fresh/InvoiceExporter.java",
        "line_number": 75,
        "origin": "introduced_by_pr",
        "classification": "finding",
        "affected_by_pr": True,
    }
    f2 = {
        "title": "N+1 query fetching restaurant records in loop",
        "description": "DB query inside loop repeated",
        "category": "sql_performance",
        "severity": "high",
        "file_path": "com/fresh/InvoiceExporter.java",
        "line_number": 76,
        "origin": "introduced_by_pr",
        "classification": "finding",
        "affected_by_pr": True,
    }
    findings = [f1, f2]
    deduped = deduplicate_findings(findings)
    assert len(deduped) == 1
    score = calculate_pr_risk_score(findings)
    assert score == 12.0  # 12.0 base * 1.0 sql_performance multiplier counted once


def test_09_inferred_requirement_gap_is_recommendation_and_zero_risk():
    finding = {
        "title": "Potential requirement gap (Inferred) INF-01: Additional currency check",
        "category": "requirement",
        "severity": "medium",
        "tags": ["inferred"],
        "file_path": "com/fresh/CurrencyService.java",
        "line_number": 40,
        "origin": "pre_existing",
    }
    verified = classify_and_verify_finding(finding, "")
    assert verified["classification"] == "recommendation"
    assert verified["affected_by_pr"] is False
    assert calculate_finding_risk(verified) == 0.0


def test_10_explicit_acceptance_criterion_violated_contributes_to_risk():
    finding = {
        "title": "AC-01 Violation: Skip logic not executed for EdiCom format",
        "category": "requirement",
        "severity": "high",
        "tags": ["explicit"],
        "file_path": "com/fresh/EdicomExporter.java",
        "line_number": 110,
        "origin": "introduced_by_pr",
        "classification": "finding",
        "affected_by_pr": True,
    }
    assert is_pr_defect(finding) is True
    risk = calculate_finding_risk(finding)
    assert risk == 13.2  # 12.0 base * 1.1 requirement multiplier


def test_11_many_test_and_refactoring_recommendations_do_not_produce_100_risk():
    findings = []
    # Add 15 test coverage findings (all recommendations)
    for i in range(15):
        findings.append({
            "title": f"Missing unit test #{i}",
            "category": "test_coverage",
            "severity": "high",
            "file_path": f"com/fresh/File{i}.java",
            "line_number": 10,
            "origin": "introduced_by_pr",
            "classification": "recommendation",
            "affected_by_pr": False,
        })
    # Add 10 refactoring recommendations
    for i in range(10):
        findings.append({
            "title": f"Duplicate code section #{i}",
            "category": "refactoring",
            "severity": "low",
            "file_path": f"com/fresh/Helper{i}.java",
            "line_number": 20,
            "origin": "introduced_by_pr",
            "classification": "recommendation",
            "affected_by_pr": False,
        })

    risk_score = calculate_pr_risk_score(findings)
    assert risk_score == 0.0  # All recommendations -> 0 risk!


def test_12_deterministic_risk_score_calculation():
    # Mix of PR defects and recommendations
    findings = [
        # PR Defect 1: High Security (12 * 1.25 = 15.0)
        {
            "title": "CSRF token missing on endpoint",
            "category": "security",
            "severity": "high",
            "file_path": "com/fresh/ApiController.java",
            "line_number": 50,
            "origin": "introduced_by_pr",
            "classification": "finding",
            "affected_by_pr": True,
        },
        # Recommendation 1: Test coverage (0.0)
        {
            "title": "Missing test for ApiController",
            "category": "test_coverage",
            "severity": "medium",
            "file_path": "com/fresh/ApiController.java",
            "line_number": 50,
            "origin": "pre_existing",
            "classification": "recommendation",
            "affected_by_pr": False,
        },
        # Recommendation 2: Pre-existing issue (0.0)
        {
            "title": "Legacy method uses deprecated API",
            "category": "code_quality",
            "severity": "high",
            "file_path": "com/fresh/LegacyService.java",
            "line_number": 200,
            "origin": "pre_existing",
            "classification": "recommendation",
            "affected_by_pr": False,
        }
    ]

    pr_defects, recs = get_pr_defects_and_recommendations(findings)
    assert len(pr_defects) == 1
    assert len(recs) == 2
    assert calculate_pr_risk_score(findings) == 15.0


# ── AUDIT REGRESSION TESTS A THROUGH N ───────────────────────────────────────

def test_case_A_normal_missing_test_is_recommendation_zero_risk():
    finding = {
        "title": "Missing unit test for EdgeCaseHandler",
        "category": "test_coverage",
        "severity": "medium",
        "file_path": "com/fresh/EdgeCaseHandler.java",
        "line_number": 12,
        "origin": "introduced_by_pr",
    }
    verified = classify_and_verify_finding(finding, "diff --git a/com/fresh/EdgeCaseHandler.java b/com/fresh/EdgeCaseHandler.java\n@@ -10,5 +10,5 @@\n+ line 12")
    assert verified["classification"] == "recommendation"
    assert verified["affected_by_pr"] is False
    assert calculate_finding_risk(verified) == 0.0


def test_case_B_test_coverage_functional_regression_contributes_risk():
    finding = {
        "title": "Regression defect: Test suite fails due to unhandled null in branch",
        "description": "Actual regression introduced by PR in test suite execution path",
        "category": "test_coverage",
        "severity": "high",
        "file_path": "com/fresh/TestRunner.java",
        "line_number": 88,
        "origin": "introduced_by_pr",
        "impact_type": "runtime_failure",
    }
    verified = classify_and_verify_finding(finding, "diff --git a/com/fresh/TestRunner.java b/com/fresh/TestRunner.java\n@@ -88,5 +88,5 @@\n+ unhandled null")
    assert verified["classification"] == "finding"
    assert verified["affected_by_pr"] is True
    assert is_pr_defect(verified) is True
    risk = calculate_finding_risk(verified)
    assert risk == 6.0  # 12.0 base * 0.50 test_coverage multiplier


def test_case_C_simple_duplication_is_low_recommendation():
    finding = {
        "title": "Duplicate validation helper in export package",
        "category": "refactoring",
        "severity": "high",
        "file_path": "com/fresh/ExportHelper.java",
        "line_number": 30,
        "origin": "pre_existing",
        "classification": "recommendation",
        "affected_by_pr": False,
    }
    verified = classify_and_verify_finding(finding, "")
    assert verified["classification"] == "recommendation"
    assert calculate_finding_risk(verified) == 0.0


def test_case_D_index_out_of_bounds_exception_remains_high_severity():
    finding = {
        "title": "Uncaught IndexOutOfBoundsException in array slicing",
        "description": "Array access with unvalidated bounds index leading to crash",
        "category": "code_quality",
        "severity": "high",
        "file_path": "com/fresh/ArrayProcessor.java",
        "line_number": 45,
        "origin": "introduced_by_pr",
    }
    verified = classify_and_verify_finding(finding, "diff --git a/com/fresh/ArrayProcessor.java b/com/fresh/ArrayProcessor.java\n@@ -45,5 +45,5 @@\n+ slice line")
    assert verified["severity"] == "high"
    assert verified["classification"] == "finding"
    assert calculate_finding_risk(verified) == 9.0  # 12.0 base * 0.75 code_quality multiplier


def test_case_E_arithmetic_exception_division_by_zero_remains_high_severity():
    finding = {
        "title": "ArithmeticException due to division by zero in pricing formula",
        "description": "Quantity divisor can be zero when discount applied",
        "category": "code_quality",
        "severity": "high",
        "file_path": "com/fresh/PricingCalculator.java",
        "line_number": 102,
        "origin": "introduced_by_pr",
    }
    verified = classify_and_verify_finding(finding, "diff --git a/com/fresh/PricingCalculator.java b/com/fresh/PricingCalculator.java\n@@ -102,5 +102,5 @@\n+ div line")
    assert verified["severity"] == "high"
    assert calculate_finding_risk(verified) == 9.0


def test_case_F_race_condition_remains_high_severity():
    finding = {
        "title": "Critical race condition on shared mutable cache state",
        "description": "Concurrent thread access without synchronization lock causes data corrupt state",
        "category": "code_quality",
        "severity": "high",
        "file_path": "com/fresh/CacheManager.java",
        "line_number": 64,
        "origin": "introduced_by_pr",
    }
    verified = classify_and_verify_finding(finding, "diff --git a/com/fresh/CacheManager.java b/com/fresh/CacheManager.java\n@@ -64,5 +64,5 @@\n+ state line")
    assert verified["severity"] == "high"
    assert calculate_finding_risk(verified) == 9.0


def test_case_G_normal_readability_issue_downgraded_to_medium():
    finding = {
        "title": "Method name is unclear and inline logic is hard to read",
        "description": "Poor naming convention and missing code comments",
        "category": "code_quality",
        "severity": "high",
        "file_path": "com/fresh/Service.java",
        "line_number": 20,
        "origin": "introduced_by_pr",
    }
    verified = classify_and_verify_finding(finding, "diff --git a/com/fresh/Service.java b/com/fresh/Service.java\n@@ -20,5 +20,5 @@\n+ name line")
    assert verified["severity"] == "medium"
    assert calculate_finding_risk(verified) == 3.0  # 4.0 base * 0.75 code_quality multiplier


def test_case_H_pre_existing_npe_is_recommendation_zero_risk():
    finding = {
        "title": "Potential NullPointerException on legacy method return",
        "category": "code_quality",
        "severity": "high",
        "file_path": "com/fresh/LegacyService.java",
        "line_number": 150,
        "origin": "pre_existing",
        "classification": "recommendation",
        "affected_by_pr": False,
    }
    verified = classify_and_verify_finding(finding, "")
    assert verified["classification"] == "recommendation"
    assert verified["affected_by_pr"] is False
    assert calculate_finding_risk(verified) == 0.0


def test_case_I_pr_introduced_npe_is_finding_positive_risk():
    finding = {
        "title": "NullPointer risk on newly added customer getter",
        "description": "NPE crash when customer record is missing",
        "category": "code_quality",
        "severity": "high",
        "file_path": "com/fresh/CustomerService.java",
        "line_number": 55,
        "origin": "introduced_by_pr",
    }
    verified = classify_and_verify_finding(finding, "diff --git a/com/fresh/CustomerService.java b/com/fresh/CustomerService.java\n@@ -55,5 +55,5 @@\n+ getter line")
    assert verified["classification"] == "finding"
    assert verified["affected_by_pr"] is True
    assert calculate_finding_risk(verified) == 9.0


def test_case_J_unchanged_line_defect_caused_by_changed_caller():
    diff_str = """diff --git a/com/fresh/OrderService.java b/com/fresh/OrderService.java
@@ -30,5 +30,5 @@
+ public void processOrder(OrderDTO order) { calculateDiscount(order); }
"""
    finding = {
        "title": "calculateDiscount method fails when passed null OrderDTO from processOrder caller",
        "description": "Unchanged method calculateDiscount in OrderService behaves incorrectly because changed caller processOrder passes unvalidated DTO",
        "category": "code_quality",
        "severity": "high",
        "file_path": "com/fresh/OrderService.java",
        "line_number": 120,  # Unchanged line in calculateDiscount
    }
    verified = classify_and_verify_finding(finding, diff_str)
    assert verified["change_scope"] == "unchanged"
    assert verified["origin"] == "modified_by_pr"
    assert verified["classification"] == "finding"
    assert verified["affected_by_pr"] is True
    assert calculate_finding_risk(verified) == 9.0


def test_case_K_unchanged_line_pre_existing_defect_zero_risk():
    diff_str = """diff --git a/com/fresh/OrderService.java b/com/fresh/OrderService.java
@@ -30,5 +30,5 @@
+ public void processOrder(OrderDTO order) {}
"""
    finding = {
        "title": "Legacy method legacyFormat() uses unoptimized string concatenation",
        "description": "Technical debt in legacy method",
        "category": "code_quality",
        "severity": "medium",
        "file_path": "com/fresh/OrderService.java",
        "line_number": 250,  # Unchanged line with no relation to processOrder
    }
    verified = classify_and_verify_finding(finding, diff_str)
    assert verified["change_scope"] == "unchanged"
    assert verified["origin"] == "pre_existing"
    assert verified["classification"] == "recommendation"
    assert verified["affected_by_pr"] is False
    assert calculate_finding_risk(verified) == 0.0


def test_case_L_explicit_jira_ac_violation_contributes_risk():
    finding = {
        "title": "AC-02 Violation: Order total discount formula missing tax adjustment",
        "category": "requirement",
        "severity": "high",
        "tags": ["explicit", "ac-02"],
        "file_path": "com/fresh/DiscountService.java",
        "line_number": 40,
        "origin": "introduced_by_pr",
    }
    verified = classify_and_verify_finding(finding, "diff --git a/com/fresh/DiscountService.java b/com/fresh/DiscountService.java\n@@ -40,5 +40,5 @@\n+ discount calc")
    assert verified["classification"] == "finding"
    assert verified["affected_by_pr"] is True
    assert calculate_finding_risk(verified) == 13.2  # 12.0 base * 1.10 requirement multiplier


def test_case_M_inferred_requirement_gap_is_recommendation_zero_risk():
    finding = {
        "title": "Potential requirement gap (Inferred) INF-02: Logging for audit events",
        "category": "requirement",
        "severity": "medium",
        "tags": ["inferred"],
        "file_path": "com/fresh/AuditLogger.java",
        "line_number": 15,
        "origin": "pre_existing",
    }
    verified = classify_and_verify_finding(finding, "")
    assert verified["classification"] == "recommendation"
    assert verified["affected_by_pr"] is False
    assert calculate_finding_risk(verified) == 0.0


def test_case_N_duplicate_agent_reports_merged_risk_counted_once():
    f1 = {
        "title": "IndexOutOfBoundsException when accessing order item array",
        "description": "Array bounds check missing on item index",
        "category": "code_quality",
        "severity": "high",
        "file_path": "com/fresh/OrderProcessor.java",
        "line_number": 80,
        "origin": "introduced_by_pr",
        "classification": "finding",
        "affected_by_pr": True,
    }
    f2 = {
        "title": "IndexOutOfBoundsException when accessing order item array",
        "description": "Array bounds check missing on item index reported by security agent",
        "category": "security",
        "severity": "high",
        "file_path": "com/fresh/OrderProcessor.java",
        "line_number": 81,
        "origin": "introduced_by_pr",
        "classification": "finding",
        "affected_by_pr": True,
    }
    deduped = deduplicate_findings([f1, f2])
    assert len(deduped) == 1
    score = calculate_pr_risk_score([f1, f2])
    # Deduplicated score calculated once for the single merged issue
    assert score == 15.0  # 12.0 base * 1.25 security multiplier (highest priority category preserved)

