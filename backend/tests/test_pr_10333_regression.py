"""
Deterministic Regression Test Suite for PR #10333 and Targeted Context Architecture.
Validates cross-file data-flow defect detection, diff-only fallback, and provenance rules.
"""

import pytest
from pathlib import Path

from app.agents.agent_code_quality import CodeQualityAgent
from app.services.targeted_dependency_resolver import TargetedDependencyResolver


@pytest.fixture
def pr_10333_worktree(tmp_path):
    """Sets up a realistic worktree layout matching PR #10333 scenario."""
    export_dir = tmp_path / "fc-core/src/main/java/com/freshsupport/export"
    dao_dir = tmp_path / "fc-core/src/main/java/com/freshsupport/dao/impl"
    domain_dir = tmp_path / "fc-core/src/main/java/com/freshsupport/report"

    export_dir.mkdir(parents=True)
    dao_dir.mkdir(parents=True)
    domain_dir.mkdir(parents=True)

    # 1. EliorPriceListExport.java
    export_file = export_dir / "EliorPriceListExport.java"
    export_file.write_text("""
package com.freshsupport.export;

import com.freshsupport.report.PriceHistoryDomain;

public class EliorPriceListExport {
    public void generateReport(PriceHistoryDomain product) {
        // Updated in PR #10333 to resolve foreign currency sell price
        BigDecimal finalPrice = resolveSellPrice(
            product.getPricePerCase(),
            product.getForeignSellPrice()
        );
    }
}
    """, encoding="utf-8")

    # 2. SellPriceHistoryDaoImpl.java (Missing foreign_sell_price in SELECT query)
    dao_file = dao_dir / "SellPriceHistoryDaoImpl.java"
    dao_file.write_text("""
package com.freshsupport.dao.impl;

public class SellPriceHistoryDaoImpl {
    public void getPricesBetweenDate() {
        // Query misses foreign_sell_price column from database!
        String sql = "SELECT sph.price_id, sph.sell_price FROM sell_price_history sph WHERE sph.active = 1";
        // Unrelated pre-existing issue in unchanged method below:
        String badQuery = "SELECT * FROM legacy_table WHERE id = " + inputId;
    }
}
    """, encoding="utf-8")

    # 3. PriceHistoryDomain.java
    domain_file = domain_dir / "PriceHistoryDomain.java"
    domain_file.write_text("""
package com.freshsupport.report;

import java.math.BigDecimal;

public class PriceHistoryDomain {
    private BigDecimal pricePerCase;
    private BigDecimal foreignSellPrice;

    public BigDecimal getPricePerCase() {
        return pricePerCase;
    }

    public BigDecimal getForeignSellPrice() {
        return foreignSellPrice;
    }

    public void setForeignSellPrice(BigDecimal foreignSellPrice) {
        this.foreignSellPrice = foreignSellPrice;
    }
}
    """, encoding="utf-8")

    return tmp_path


def test_pr_10333_targeted_context_resolution(pr_10333_worktree):
    """
    Validates that PR #10333 diff triggers targeted context resolution and extracts
    both SellPriceHistoryDaoImpl and PriceHistoryDomain snippets.
    """
    resolver = TargetedDependencyResolver(worktree_path=str(pr_10333_worktree))
    diff = """
--- a/fc-core/src/main/java/com/freshsupport/export/EliorPriceListExport.java
+++ b/fc-core/src/main/java/com/freshsupport/export/EliorPriceListExport.java
@@ -10,3 +10,3 @@
-BigDecimal finalPrice = product.getPricePerCase();
+BigDecimal finalPrice = resolveSellPrice(product.getPricePerCase(), product.getForeignSellPrice());
    """

    res = resolver.analyze_and_resolve(
        diff_text=diff,
        changed_files=[{"new": {"path": "fc-core/src/main/java/com/freshsupport/export/EliorPriceListExport.java"}}],
    )

    assert res["has_targeted_context"] is True
    assert "new_getter" in res["dependency_triggers"] or "method_call" in res["dependency_triggers"]
    assert any("SellPriceHistoryDaoImpl.java" in f for f in res["targeted_files"])
    assert any("PriceHistoryDomain.java" in f for f in res["targeted_files"])
    assert "foreignSellPrice" in res["context_text"] or "getForeignSellPrice" in res["context_text"]


def test_simple_refactor_falls_back_to_diff_only(pr_10333_worktree):
    """
    Validates that simple diffs without external triggers remain in diff_only mode.
    """
    resolver = TargetedDependencyResolver(worktree_path=str(pr_10333_worktree))
    diff = """
--- a/fc-core/src/main/java/com/freshsupport/export/EliorPriceListExport.java
+++ b/fc-core/src/main/java/com/freshsupport/export/EliorPriceListExport.java
@@ -5,2 +5,2 @@
-int total = 10;
+int total = 20;
    """

    res = resolver.analyze_and_resolve(
        diff_text=diff,
        changed_files=[{"new": {"path": "fc-core/src/main/java/com/freshsupport/export/EliorPriceListExport.java"}}],
    )

    assert res["has_targeted_context"] is False
    assert res["context_text"] == ""
    assert res["dependency_triggers"] == []


def test_agent_context_preparation():
    """
    Validates that CodeQualityAgent properly builds targeted_context prompt metadata.
    """
    agent = CodeQualityAgent({"review_id": "test-pr-10333"})
    state = {
        "pr_context": {
            "diff": "+ BigDecimal p = product.getForeignSellPrice();",
            "changed_files": [{"new": {"path": "EliorPriceListExport.java"}}],
        },
        "targeted_context": {
            "has_targeted_context": True,
            "context_text": "--- TARGETED REPOSITORY CONTEXT ---\n[File: SellPriceHistoryDaoImpl.java]\nSELECT sph.sell_price FROM sell_price_history",
            "targeted_files": ["SellPriceHistoryDaoImpl.java"],
            "targeted_symbols": ["getForeignSellPrice"],
            "dependency_triggers": ["new_getter"],
            "dependency_depth": 2,
            "targeted_context_chars": 150,
        },
    }

    ctx_info = agent._prepare_agent_context(state)
    assert ctx_info["context_mode"] == "targeted_context"
    assert ctx_info["repository_context"] is True
    assert "TARGETED REPOSITORY CONTEXT" in ctx_info["extra_prompt_text"]
    assert ctx_info["targeted_files"] == ["SellPriceHistoryDaoImpl.java"]
    assert ctx_info["dependency_depth"] == 2
