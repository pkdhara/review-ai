"""
Unit tests for TargetedDependencyResolver and audit logging.
"""

import json
from pathlib import Path
import pytest

from app.services.targeted_dependency_resolver import (
    TargetedDependencyResolver,
    MAX_TARGETED_FILES,
    MAX_TARGETED_SYMBOLS,
    MAX_TARGETED_CONTEXT_CHARS,
)
from app.core.review_logger import ReviewAuditLogger


def test_resolver_no_triggers():
    resolver = TargetedDependencyResolver()
    diff = """
--- a/src/Main.java
+++ b/src/Main.java
@@ -10,3 +10,3 @@
-int total = a + b;
+int total = a + b + c;
    """
    res = resolver.analyze_and_resolve(diff_text=diff, changed_files=[{"new": {"path": "src/Main.java"}}])
    assert res["has_targeted_context"] is False
    assert res["context_text"] == ""
    assert res["targeted_files"] == []
    assert res["targeted_symbols"] == []
    assert res["dependency_triggers"] == []


def test_resolver_getter_and_method_trigger(tmp_path):
    # Setup mock worktree
    dao_dir = tmp_path / "com/freshsupport/dao"
    domain_dir = tmp_path / "com/freshsupport/domain"
    dao_dir.mkdir(parents=True)
    domain_dir.mkdir(parents=True)

    dao_file = dao_dir / "SellPriceHistoryDao.java"
    dao_file.write_text("""
package com.freshsupport.dao;

public class SellPriceHistoryDao {
    public void getPricesBetweenDate() {
        String sql = "SELECT sph.sell_price FROM sell_price_history sph";
        // missing foreign_sell_price mapping
    }
}
    """, encoding="utf-8")

    domain_file = domain_dir / "PriceHistoryDomain.java"
    domain_file.write_text("""
package com.freshsupport.domain;

public class PriceHistoryDomain {
    private BigDecimal foreignSellPrice;

    public BigDecimal getForeignSellPrice() {
        return foreignSellPrice;
    }

    public void setForeignSellPrice(BigDecimal foreignSellPrice) {
        self.foreignSellPrice = foreignSellPrice;
    }
}
    """, encoding="utf-8")

    resolver = TargetedDependencyResolver(worktree_path=str(tmp_path))
    diff = """
--- a/com/freshsupport/export/EliorPriceListExport.java
+++ b/com/freshsupport/export/EliorPriceListExport.java
@@ -45,2 +45,2 @@
-BigDecimal price = product.getPricePerCase();
+BigDecimal price = resolveSellPrice(product.getPricePerCase(), product.getForeignSellPrice());
    """

    res = resolver.analyze_and_resolve(
        diff_text=diff,
        changed_files=[{"new": {"path": "com/freshsupport/export/EliorPriceListExport.java"}}],
    )

    assert res["has_targeted_context"] is True
    assert len(res["targeted_files"]) > 0
    assert "getForeignSellPrice" in res["targeted_symbols"] or "resolveSellPrice" in res["targeted_symbols"]
    assert "new_getter" in res["dependency_triggers"] or "method_call" in res["dependency_triggers"]
    assert "--- TARGETED REPOSITORY CONTEXT ---" in res["context_text"]


def test_resolver_context_budget_limits(tmp_path):
    # Create 8 files to verify file cap at 5
    for i in range(8):
        f = tmp_path / f"Domain{i}.java"
        f.write_text(f"""
public class Domain{i} {{
    private String customField{i};
    public String getCustomField{i}() {{ return customField{i}; }}
}}
        """, encoding="utf-8")

    resolver = TargetedDependencyResolver(worktree_path=str(tmp_path))
    added_lines = "\n".join([f"+ product.getCustomField{i}();" for i in range(8)])
    diff = f"""
--- a/src/Consumer.java
+++ b/src/Consumer.java
@@ -10,1 +10,8 @@
{added_lines}
    """

    res = resolver.analyze_and_resolve(diff_text=diff, changed_files=[{"new": {"path": "src/Consumer.java"}}])
    assert len(res["targeted_files"]) <= MAX_TARGETED_FILES
    assert len(res["targeted_symbols"]) <= MAX_TARGETED_SYMBOLS
    assert len(res["context_text"]) <= MAX_TARGETED_CONTEXT_CHARS


def test_audit_logger_contains_targeted_fields(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.review_logger._LOGS_DIR", tmp_path)
    logger = ReviewAuditLogger("test-review-123")

    logger.log_agent_call(
        agent_name="code_quality",
        context_mode="targeted_context",
        repository_context=True,
        diff_chars=1500,
        context_chars=4200,
        targeted_context_chars=4200,
        targeted_files=["SellPriceHistoryDao.java", "PriceHistoryDomain.java"],
        targeted_symbols=["getForeignSellPrice", "getPricesBetweenDate"],
        dependency_triggers=["new_getter", "dao_dependency"],
        dependency_depth=2,
    )

    log_file = tmp_path / "test-review-123.log"
    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").splitlines()
    data = json.loads(lines[0])

    assert data["context_mode"] == "targeted_context"
    assert data["repository_context"] is True
    assert data["diff_chars"] == 1500
    assert data["context_chars"] == 4200
    assert data["targeted_context_chars"] == 4200
    assert data["targeted_files"] == ["SellPriceHistoryDao.java", "PriceHistoryDomain.java"]
    assert data["targeted_symbols"] == ["getForeignSellPrice", "getPricesBetweenDate"]
    assert data["dependency_triggers"] == ["new_getter", "dao_dependency"]
    assert data["dependency_depth"] == 2
