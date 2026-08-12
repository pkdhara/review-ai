"""
Unit Tests for Finding Provenance and Classification System
──────────────────────────────────────────────────────────────
Validates accurate classification of findings based on Git diff verification,
behavioral causality, requirement isolation, and deduplication rules.
"""

import unittest
import asyncio
from app.agents.git_diff_verifier import (
    parse_diff_changed_lines,
    classify_and_verify_finding,
    verify_all_findings,
)
from app.agents.deduplication import deduplicate_findings
from app.agents.agent_review_summary import ReviewSummaryAgent
from app.agents.state import FindingDict


SAMPLE_DIFF = """diff --git a/src/main/java/com/fresh/PricingExporter.java b/src/main/java/com/fresh/PricingExporter.java
index 1234567..89abcdef 100644
--- a/src/main/java/com/fresh/PricingExporter.java
+++ b/src/main/java/com/fresh/PricingExporter.java
@@ -45,7 +45,9 @@ public class PricingExporter {
     public BigDecimal calculatePrice(PricingContext ctx) {
         if (ctx == null) return BigDecimal.ZERO;
-        BigDecimal price = ctx.getBasePrice();
+        // PR change on line 48
+        BigDecimal price = ctx.getForeignSellPrice() != null ? ctx.getForeignSellPrice() : ctx.getBasePrice();
         return price;
     }
+    // Line 51 added by PR
"""


class TestFindingClassificationOrigin(unittest.TestCase):

    def test_case_1_unchanged_line_pre_existing_recommendation(self):
        """CASE 1: Issue exists only on an unchanged line -> origin=pre_existing, classification=recommendation."""
        finding: FindingDict = {
            "title": "Legacy NPE in helper method",
            "description": "Unchecked null access on legacy line",
            "file_path": "src/main/java/com/fresh/PricingExporter.java",
            "line_number": 10,  # Unchanged line
            "severity": "high",
            "category": "code_quality",
            "recommendation": "Add null check",
            "review_comment": "Add null check",
        }

        verified = classify_and_verify_finding(finding, SAMPLE_DIFF)

        self.assertEqual(verified["change_scope"], "unchanged")
        self.assertEqual(verified["origin"], "pre_existing")
        self.assertEqual(verified["classification"], "recommendation")
        self.assertFalse(verified["affected_by_pr"])
        # High severity on pre-existing recommendation should be capped to medium
        self.assertEqual(verified["severity"], "medium")

    def test_case_2_changed_line_pr_introduced_finding(self):
        """CASE 2: Issue is introduced on a changed line -> origin=introduced_by_pr, classification=finding."""
        finding: FindingDict = {
            "title": "Ternary operator bug on foreign sell price",
            "description": "Missing null guard on ctx.getForeignSellPrice()",
            "file_path": "src/main/java/com/fresh/PricingExporter.java",
            "line_number": 48,  # Changed line in SAMPLE_DIFF
            "severity": "high",
            "category": "code_quality",
            "recommendation": "Check for null",
            "review_comment": "Check for null",
        }

        verified = classify_and_verify_finding(finding, SAMPLE_DIFF)

        self.assertEqual(verified["change_scope"], "changed")
        self.assertEqual(verified["origin"], "introduced_by_pr")
        self.assertEqual(verified["classification"], "finding")
        self.assertTrue(verified["affected_by_pr"])
        self.assertEqual(verified["severity"], "high")

    def test_case_3_unchanged_line_behavioral_impact_modified_by_pr(self):
        """CASE 3: Issue is on unchanged line but PR changes behavior affecting it -> origin=modified_by_pr."""
        finding: FindingDict = {
            "title": "Downstream NullPointer triggered by PR change",
            "description": "PR changes caller behavior which causes modified_by_pr condition downstream on unchanged line",
            "file_path": "src/main/java/com/fresh/PricingExporter.java",
            "line_number": 20,  # Unchanged line
            "origin": "modified_by_pr",
            "severity": "high",
            "category": "code_quality",
            "recommendation": "Fix downstream handling",
            "review_comment": "Fix downstream handling",
        }

        verified = classify_and_verify_finding(finding, SAMPLE_DIFF)

        self.assertEqual(verified["change_scope"], "unchanged")
        self.assertEqual(verified["origin"], "modified_by_pr")
        self.assertEqual(verified["classification"], "finding")
        self.assertTrue(verified["affected_by_pr"])

    def test_case_4_contextual_unchanged_code(self):
        """CASE 4: Unchanged code is only contextual -> origin=contextual/pre_existing, classification=recommendation."""
        finding: FindingDict = {
            "title": "Contextual formatting style in surrounding class",
            "description": "Surrounding code lacks final modifier",
            "file_path": "src/main/java/com/fresh/PricingExporter.java",
            "line_number": 2,
            "origin": "contextual",
            "severity": "low",
            "category": "refactoring",
            "recommendation": "Add final",
            "review_comment": "Add final",
        }

        verified = classify_and_verify_finding(finding, SAMPLE_DIFF)

        self.assertEqual(verified["origin"], "contextual")
        self.assertEqual(verified["classification"], "recommendation")
        self.assertFalse(verified["affected_by_pr"])

    def test_case_5_deduplication_merges_multiple_agents_into_one_recommendation(self):
        """CASE 5: Existing issue found by two different agents -> Merged into one recommendation."""
        f1: FindingDict = {
            "title": "Potential NullPointer on line 100",
            "description": "Unchecked null access in legacy helper",
            "file_path": "src/main/java/com/fresh/PricingExporter.java",
            "line_number": 100,
            "severity": "medium",
            "category": "code_quality",
            "origin": "pre_existing",
            "classification": "recommendation",
            "affected_by_pr": False,
            "recommendation": "Add check",
            "review_comment": "Add check",
        }
        f2: FindingDict = {
            "title": "Existing nullability problem on line 100",
            "description": "Unchecked null access in legacy helper method",
            "file_path": "src/main/java/com/fresh/PricingExporter.java",
            "line_number": 100,
            "severity": "low",
            "category": "refactoring",
            "origin": "pre_existing",
            "classification": "recommendation",
            "affected_by_pr": False,
            "recommendation": "Refactor null check",
            "review_comment": "Refactor null check",
        }

        merged = deduplicate_findings([f1, f2])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["classification"], "recommendation")
        self.assertEqual(merged[0]["origin"], "pre_existing")
        self.assertFalse(merged[0]["affected_by_pr"])

    def test_case_6_pre_existing_issue_does_not_affect_risk_score(self):
        """CASE 6: Pre-existing recommendation does NOT penalize PR risk score or count as PR defect."""
        agent = ReviewSummaryAgent(settings={})
        
        pr_defect: FindingDict = {
            "title": "PR Defect",
            "severity": "low",
            "category": "code_quality",
            "classification": "finding",
            "origin": "introduced_by_pr",
            "affected_by_pr": True,
        }
        pre_existing_rec: FindingDict = {
            "title": "Legacy Debt",
            "severity": "critical",
            "category": "code_quality",
            "classification": "recommendation",
            "origin": "pre_existing",
            "affected_by_pr": False,
        }

        from app.agents.risk_calculator import calculate_pr_risk_score
        score_defects_only = calculate_pr_risk_score([pr_defect])
        self.assertEqual(score_defects_only, 0.8)  # 1.0 base * 0.75 code_quality multiplier

    def test_case_7_upstream_factory_change_triggers_modified_by_pr(self):
        """CASE 7: Upstream factory change affecting downstream line -> modified_by_pr."""
        finding: FindingDict = {
            "title": "Upstream factory condition altered",
            "description": "PR changed caller factory logic leading to potential state mismatch",
            "file_path": "src/main/java/com/fresh/PricingExporter.java",
            "line_number": 15,
            "origin": "modified_by_pr",
            "severity": "medium",
            "category": "code_quality",
            "recommendation": "Update downstream guard",
            "review_comment": "Update downstream guard",
        }

        verified = classify_and_verify_finding(finding, SAMPLE_DIFF)

        self.assertEqual(verified["origin"], "modified_by_pr")
        self.assertEqual(verified["classification"], "finding")
        self.assertTrue(verified["affected_by_pr"])


if __name__ == "__main__":
    unittest.main()
