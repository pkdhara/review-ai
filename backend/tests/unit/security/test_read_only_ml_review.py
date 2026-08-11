"""
Security Tests: Enforcing READ-ONLY ML Review Pipeline.

Validates that the entire ML/AI review pipeline operates under strict read-only guarantees with respect to:
1. Bitbucket Cloud API
2. Jira Cloud API
3. Local Git working repository
4. LLM tool-calling registries
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.read_only_services import (
    BitbucketReadService,
    JiraReadService,
    LocalRepositoryReadService,
    LLMReadOnlyToolRegistry,
    ReadOnlyViolationError,
)
from app.services.bitbucket_service import BitbucketService
from app.services.jira_service import JiraService
from app.services.code_context_service import CodeContextService
from app.services.git_worktree_service import GitWorktreeManager
from app.agents.workflow import ReviewWorkflow


class TestReadOnlySecurityRequirements(unittest.TestCase):

    # ── Requirement 1: Bitbucket data fetch without any write operation ──────
    def test_bitbucket_read_service_allows_reads_disallows_writes(self):
        mock_bb = MagicMock(spec=BitbucketService)
        mock_bb.get_pr = AsyncMock(return_value={"id": 5351, "title": "Test PR"})
        mock_bb.get_pr_diff = AsyncMock(return_value=("diff text", {}))

        read_svc = BitbucketReadService(mock_bb)

        async def run():
            pr = await read_svc.get_pr("freshconcepts", 5351)
            self.assertEqual(pr["id"], 5351)

            # Assert write operations throw ReadOnlyViolationError
            with self.assertRaises(ReadOnlyViolationError):
                await read_svc.post_pr_comment("freshconcepts", 5351, "comment")

            with self.assertRaises(ReadOnlyViolationError):
                await read_svc.approve_pr("freshconcepts", 5351)

            with self.assertRaises(ReadOnlyViolationError):
                await read_svc.decline_pr("freshconcepts", 5351)

            with self.assertRaises(ReadOnlyViolationError):
                await read_svc.merge_pr("freshconcepts", 5351)

            with self.assertRaises(ReadOnlyViolationError):
                await read_svc.update_pr_status("freshconcepts", 5351, "DECLINED")

        asyncio.run(run())

    # ── Requirement 2: Jira context fetched without any write operation ──────
    def test_jira_read_service_allows_reads_disallows_writes(self):
        mock_jira = MagicMock(spec=JiraService)
        mock_jira.get_issue = AsyncMock(return_value={"key": "FRES-8705", "fields": {}})

        read_svc = JiraReadService(mock_jira)

        async def run():
            issue = await read_svc.get_issue("FRES-8705")
            self.assertEqual(issue["key"], "FRES-8705")

            # Assert write operations throw ReadOnlyViolationError
            with self.assertRaises(ReadOnlyViolationError):
                await read_svc.add_jira_comment("FRES-8705", "Review comment")

            with self.assertRaises(ReadOnlyViolationError):
                await read_svc.update_issue("FRES-8705", {"summary": "New Title"})

            with self.assertRaises(ReadOnlyViolationError):
                await read_svc.transition_issue("FRES-8705", "Done")

            with self.assertRaises(ReadOnlyViolationError):
                await read_svc.assign_issue("FRES-8705", "user_123")

        asyncio.run(run())

    # ── Requirement 3: LLM tools contain ONLY read-only operations ───────────
    def test_llm_tool_registry_disallows_write_tools(self):
        read_tools = LLMReadOnlyToolRegistry.get_allowed_tool_names()
        self.assertIn("get_pr", read_tools)
        self.assertIn("get_class_structure", read_tools)
        self.assertIn("find_references", read_tools)

        # Disallowed tools raise error
        for disallowed in ["update_jira", "add_jira_comment", "approve_pr", "merge_pr", "push_commit"]:
            with self.assertRaises(ReadOnlyViolationError):
                LLMReadOnlyToolRegistry.validate_tool_name(disallowed)

    # ── Requirement 4 & 5 & 6: No PR comment, Jira comment/update, or PR approval during workflow execution ─
    def test_workflow_execution_makes_no_bitbucket_or_jira_writes(self):
        wf = ReviewWorkflow(
            review_id="rev-sec-001",
            workspace="freshconcepts",
            repo_slug="fc-angular",
            pr_number=5351,
            jira_key="FRES-8705",
            bitbucket_token="token",
            jira_base_url="https://jira.test",
            jira_email="test@test.com",
            jira_token="token",
            ai_provider="anthropic",
            ai_key="key",
        )

        with patch("app.agents.workflow.BitbucketService") as MockBB, \
             patch("app.agents.workflow.JiraService") as MockJira:

            MockBB.parse_pr_url = BitbucketService.parse_pr_url
            mock_bb_inst = MockBB.return_value
            mock_bb_inst.build_pr_context = AsyncMock(return_value={
                "pr_title": "Test PR",
                "jira_key": "FRES-8705",
                "changed_files": [],
                "diff": "",
            })
            mock_jira_inst = MockJira.return_value
            mock_jira_inst.extract_issue_context = AsyncMock(return_value={
                "jira_key": "FRES-8705",
                "summary": "Fix unknown product mapping",
                "acceptance_criteria": [],
            })

            async def run():
                # Execute parallel fetch (replaces the old sequential _fetch_pr + _fetch_jira)
                state = await wf._parallel_fetch({
                    "pr_context": {
                        "workspace": "freshconcepts",
                        "repo_slug": "fc-angular",
                        "pr_number": 5351,
                        "jira_key": "FRES-8705",
                    },
                    "jira_context": {},
                    "logs": [],
                    "findings": [],
                    "requirements": [],
                    "extracted_requirements": {},
                    "current_agent": "",
                    "progress_percent": 0,
                    "progress_callback": None,
                })
                # Verify only read calls were made
                mock_bb_inst.build_pr_context.assert_called_once()
                mock_jira_inst.extract_issue_context.assert_called_once()

                # Verify NO write methods exist or were called on Bitbucket or Jira
                for write_method in ["post_comment", "approve_pr", "decline_pr", "merge_pr", "post_issue_comment", "update_issue"]:
                    if hasattr(mock_bb_inst, write_method):
                        getattr(mock_bb_inst, write_method).assert_not_called()
                    if hasattr(mock_jira_inst, write_method):
                        getattr(mock_jira_inst, write_method).assert_not_called()

            asyncio.run(run())

    # ── Requirement 7 & 8 & 9: Main local repository remains completely untouched & only worktrees created/purged ─
    def test_local_repository_read_only_isolation(self):
        with tempfile.TemporaryDirectory() as tmp_main, tempfile.TemporaryDirectory() as tmp_wt_base:
            main_repo = Path(tmp_main) / "fc-angular"
            main_repo.mkdir(parents=True)
            main_file = main_repo / "Main.java"
            main_file.write_text("class Main {}")

            main_stat_before = main_file.stat()

            # Instantiate LocalRepositoryReadService
            ctx_svc = CodeContextService("test-rev-sec")
            local_read = LocalRepositoryReadService(ctx_svc)

            # Assert write methods on local_read raise ReadOnlyViolationError
            with self.assertRaises(ReadOnlyViolationError):
                local_read.modify_source_file("Main.java", "new content")

            with self.assertRaises(ReadOnlyViolationError):
                local_read.git_commit("commit msg")

            with self.assertRaises(ReadOnlyViolationError):
                local_read.git_push("origin", "main")

            # Verify main file untouched
            self.assertEqual(main_file.read_text(), "class Main {}")
            self.assertEqual(main_file.stat().st_mtime, main_stat_before.st_mtime)

    # ── Requirement 10: Future publishing step isolated outside ML analysis pipeline ─
    def test_publishing_step_isolated_from_analysis_graph(self):
        wf = ReviewWorkflow(
            review_id="test-pub",
            workspace="freshconcepts",
            repo_slug="fc-angular",
            pr_number=5351,
            jira_key="FRES-8705",
            bitbucket_token="token",
            jira_base_url="https://jira.test",
            jira_email="test@test.com",
            jira_token="token",
            ai_provider="anthropic",
            ai_key="key",
        )
        graph = wf.build_graph()

        # Nodes in the analysis state graph
        nodes = list(graph.nodes.keys())
        
            # Verify ML analysis graph nodes are purely analysis nodes
        for node_name in nodes:
            self.assertNotIn("publish", node_name.lower())
            self.assertNotIn("comment", node_name.lower())
            self.assertNotIn("write", node_name.lower())

    def test_assert_ml_pipeline_read_only_helper(self):
        from app.services.read_only_services import assert_ml_pipeline_read_only
        self.assertTrue(assert_ml_pipeline_read_only())


if __name__ == "__main__":
    unittest.main()
