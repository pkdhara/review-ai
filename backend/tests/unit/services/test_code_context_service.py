"""
Unit tests for CodeContextService & per-review caching (Standard unittest compatible)
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from app.services.code_context_service import CodeContextService, _PER_REVIEW_CACHE


class TestCodeContextService(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.wt_dir = Path(self.tmp_dir.name) / "worktree_001"
        self.wt_dir.mkdir(parents=True)
        pkg_dir = self.wt_dir / "src" / "main" / "java" / "com" / "example"
        pkg_dir.mkdir(parents=True)

        self.rel_path = "src/main/java/com/example/CustomerService.java"
        java_file = pkg_dir / "CustomerService.java"
        java_file.write_text("""
package com.example;

public class CustomerService {
    public Customer getCustomer(Long id) {
        return new Customer(id, "John");
    }

    public void updateCustomer(Customer customer) {
        // update
    }
}
""")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_code_context_service_initialize(self):
        review_id = "rev-test-100"
        svc = CodeContextService(review_id)

        async def run():
            with patch.object(svc.worktree_manager, "prepare_worktree", new_callable=AsyncMock, return_value=str(self.wt_dir)):
                result = await svc.initialize_review_context(
                    workspace="freshconcepts",
                    repo_slug="fc-angular",
                    source_commit="commit123",
                    diff_text="diff --git a/src/main/java/com/example/CustomerService.java b/src/main/java/com/example/CustomerService.java\n@@ -5,2 +5,3 @@\n",
                    changed_files=[{"new": {"path": self.rel_path}}],
                )

                self.assertTrue(result["has_local_context"])
                self.assertEqual(result["indexed_classes_count"], 1)
                self.assertTrue("CustomerService.java" in svc.cache["class_structures"] or self.rel_path in svc.cache["class_structures"])

        asyncio.run(run())

    def test_code_context_service_cache_hit(self):
        review_id = "rev-test-101"
        svc = CodeContextService(review_id)
        svc.cache["worktree_path"] = str(self.wt_dir)

        # First call - populates cache
        struct1 = svc.get_class_structure("CustomerService")
        self.assertIsNotNone(struct1)
        self.assertEqual(struct1["class"], "CustomerService")

        # Second call - cache hit
        struct2 = svc.get_class_structure("CustomerService")
        self.assertIs(struct1, struct2)

    def test_get_method_implementation_on_demand(self):
        review_id = "rev-test-102"
        svc = CodeContextService(review_id)
        svc.cache["worktree_path"] = str(self.wt_dir)

        method_info = svc.get_method("CustomerService", "getCustomer")
        self.assertIsNotNone(method_info)
        self.assertEqual(method_info["method_name"], "getCustomer")
        self.assertIn("return new Customer", method_info["body"])

    def test_cleanup_per_review_cache(self):
        review_id = "rev-test-103"
        svc = CodeContextService(review_id)
        svc.cache["worktree_path"] = str(self.wt_dir)
        svc.cache["repo_slug"] = "fc-angular"

        async def run():
            with patch.object(svc.worktree_manager, "cleanup_worktree", new_callable=AsyncMock) as mock_clean:
                await svc.cleanup()
                self.assertNotIn(review_id, _PER_REVIEW_CACHE)
                mock_clean.assert_called_once_with("fc-angular", review_id)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
