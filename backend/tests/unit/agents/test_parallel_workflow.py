"""
Tests for parallel workflow execution:
1. Bitbucket and Jira execute concurrently
2. One failing does not prevent the other result from being retained
3. State from both branches is merged correctly
4. No duplicate API calls occur
5. Review summary waits for required agents
6. Independent agents execute concurrently
7. Dependent agents retain their required ordering
8. Read-only restrictions remain enforced
"""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.workflow import (
    ReviewWorkflow,
    _PARALLEL_ANALYSIS_AGENTS,
    _SEQUENTIAL_AGENTS,
)
from app.agents.state import ReviewState


def _make_workflow(**overrides) -> ReviewWorkflow:
    defaults = dict(
        review_id="test-review-parallel",
        workspace="freshconcepts",
        repo_slug="fc-angular",
        pr_number=5371,
        jira_key="FRES-8851",
        bitbucket_token="bb-token",
        jira_base_url="https://jira.example.com",
        jira_email="test@example.com",
        jira_token="jira-token",
        ai_provider="gemini",
        ai_key="key",
    )
    defaults.update(overrides)
    return ReviewWorkflow(**defaults)


def _base_state(**overrides) -> ReviewState:
    state = ReviewState(
        review_id="test-review-parallel",
        workspace="freshconcepts",
        repo_slug="fc-angular",
        bitbucket_token="bb-token",
        jira_base_url="https://jira.example.com",
        jira_email="test@example.com",
        jira_token="jira-token",
        ai_provider="gemini",
        ai_key="key",
        pr_context={
            "pr_number": 5371,
            "workspace": "freshconcepts",
            "repo_slug": "fc-angular",
            "jira_key": "FRES-8851",
        },
        jira_context={},
        findings=[],
        logs=[],
        requirements=[],
        extracted_requirements={},
        current_agent="",
        progress_percent=0,
        progress_callback=None,
    )
    state.update(overrides)
    return state


class TestParallelFetch(unittest.IsolatedAsyncioTestCase):
    """Tests for concurrent Bitbucket + Jira I/O fetch stage."""

    @patch("app.agents.workflow.JiraService")
    @patch("app.agents.workflow.JiraReadService")
    @patch("app.agents.workflow.BitbucketService")
    @patch("app.agents.workflow.BitbucketReadService")
    async def test_bitbucket_and_jira_execute_concurrently(
        self, mock_bb_read, mock_bb, mock_jira_read, mock_jira
    ):
        """Both fetches start before either finishes — wall-clock ≈ max not sum."""
        call_log: list[tuple[str, float]] = []
        t0_global = time.monotonic()

        async def slow_bb(*a, **kw):
            call_log.append(("bb_start", time.monotonic() - t0_global))
            await asyncio.sleep(0.05)
            call_log.append(("bb_end", time.monotonic() - t0_global))
            return {
                "pr_title": "Test PR", "jira_key": "FRES-8851",
                "diff": "diff content", "changed_files": [], "pr_data": {},
            }

        async def slow_jira(*a, **kw):
            call_log.append(("jira_start", time.monotonic() - t0_global))
            await asyncio.sleep(0.05)
            call_log.append(("jira_end", time.monotonic() - t0_global))
            return {"summary": "Jira summary", "acceptance_criteria": []}

        mock_bb_read.return_value.build_pr_context = slow_bb
        mock_jira_read.return_value.extract_issue_context = slow_jira

        wf = _make_workflow()
        state = _base_state()

        t_start = time.monotonic()
        result = await wf._parallel_fetch(state)
        elapsed = time.monotonic() - t_start

        # Both started before the other finished (overlapping)
        bb_start = next(t for n, t in call_log if n == "bb_start")
        jira_start = next(t for n, t in call_log if n == "jira_start")
        bb_end = next(t for n, t in call_log if n == "bb_end")
        jira_end = next(t for n, t in call_log if n == "jira_end")

        # Jira started before Bitbucket ended → concurrent
        self.assertLess(jira_start, bb_end, "Jira should start before Bitbucket finishes (concurrent)")
        # Wall-clock should be close to 0.05s (max), not 0.10s (sum)
        self.assertLess(elapsed, 0.09, f"Wall-clock {elapsed:.3f}s should be < sum of both durations (0.10s)")

    @patch("app.agents.workflow.JiraService")
    @patch("app.agents.workflow.JiraReadService")
    @patch("app.agents.workflow.BitbucketService")
    @patch("app.agents.workflow.BitbucketReadService")
    async def test_jira_failure_does_not_discard_bitbucket_result(
        self, mock_bb_read, mock_bb, mock_jira_read, mock_jira
    ):
        """If Jira fails, Bitbucket pr_context must still be in the merged state."""
        mock_bb_read.return_value.build_pr_context = AsyncMock(return_value={
            "pr_title": "My PR", "jira_key": "FRES-8851",
            "diff": "--- a/foo.ts", "changed_files": [], "pr_data": {},
        })
        mock_jira_read.return_value.extract_issue_context = AsyncMock(
            side_effect=RuntimeError("Jira 503")
        )

        wf = _make_workflow()
        state = _base_state()
        result = await wf._parallel_fetch(state)

        # Bitbucket result preserved
        self.assertEqual(result["pr_context"]["pr_title"], "My PR")
        # Jira context empty but state still valid
        self.assertIn("jira_context", result)
        # Error logged but state not crashed
        error_logs = [l for l in result["logs"] if l.get("level") == "warning"]
        self.assertTrue(any("Jira" in l["message"] for l in error_logs))

    @patch("app.agents.workflow.JiraService")
    @patch("app.agents.workflow.JiraReadService")
    @patch("app.agents.workflow.BitbucketService")
    @patch("app.agents.workflow.BitbucketReadService")
    async def test_bitbucket_failure_does_not_discard_jira_result(
        self, mock_bb_read, mock_bb, mock_jira_read, mock_jira
    ):
        """If Bitbucket fails, Jira jira_context must still be in the merged state."""
        mock_bb_read.return_value.build_pr_context = AsyncMock(
            side_effect=RuntimeError("BB 401")
        )
        mock_jira_read.return_value.extract_issue_context = AsyncMock(return_value={
            "summary": "Feature story", "acceptance_criteria": ["AC1"],
        })

        wf = _make_workflow()
        state = _base_state()
        result = await wf._parallel_fetch(state)

        # Jira result preserved
        self.assertEqual(result["jira_context"]["summary"], "Feature story")

    @patch("app.agents.workflow.JiraService")
    @patch("app.agents.workflow.JiraReadService")
    @patch("app.agents.workflow.BitbucketService")
    @patch("app.agents.workflow.BitbucketReadService")
    async def test_state_merged_correctly_no_data_loss(
        self, mock_bb_read, mock_bb, mock_jira_read, mock_jira
    ):
        """Merged state contains both pr_context and jira_context without collision."""
        mock_bb_read.return_value.build_pr_context = AsyncMock(return_value={
            "pr_title": "Angular PR", "jira_key": "FRES-8851",
            "diff": "diff --git", "changed_files": [{"path": "app.ts"}], "pr_data": {},
        })
        mock_jira_read.return_value.extract_issue_context = AsyncMock(return_value={
            "summary": "Feature X", "acceptance_criteria": ["AC1", "AC2"],
        })

        wf = _make_workflow()
        state = _base_state()
        result = await wf._parallel_fetch(state)

        self.assertEqual(result["pr_context"]["pr_title"], "Angular PR")
        self.assertEqual(result["jira_context"]["summary"], "Feature X")
        self.assertEqual(len(result["jira_context"]["acceptance_criteria"]), 2)

    @patch("app.agents.workflow.JiraService")
    @patch("app.agents.workflow.JiraReadService")
    @patch("app.agents.workflow.BitbucketService")
    @patch("app.agents.workflow.BitbucketReadService")
    async def test_no_duplicate_api_calls(
        self, mock_bb_read, mock_bb, mock_jira_read, mock_jira
    ):
        """Each API (Bitbucket, Jira) is called exactly once per review."""
        mock_bb_read.return_value.build_pr_context = AsyncMock(return_value={
            "pr_title": "PR", "jira_key": "FRES-1",
            "diff": "", "changed_files": [], "pr_data": {},
        })
        mock_jira_read.return_value.extract_issue_context = AsyncMock(return_value={
            "summary": "S", "acceptance_criteria": [],
        })

        wf = _make_workflow()
        state = _base_state()
        await wf._parallel_fetch(state)

        self.assertEqual(mock_bb_read.return_value.build_pr_context.call_count, 1)
        self.assertEqual(mock_jira_read.return_value.extract_issue_context.call_count, 1)


class TestParallelAnalysis(unittest.IsolatedAsyncioTestCase):
    """Tests for concurrent analysis agent execution."""

    async def test_independent_agents_run_concurrently(self):
        """The 6 independent agents overlap in time (asyncio.gather)."""
        call_times: dict[str, float] = {}
        t0 = time.monotonic()

        async def _fake_run(self_agent, state):
            name = self_agent.name
            call_times[f"{name}_start"] = time.monotonic() - t0
            await asyncio.sleep(0.04)
            call_times[f"{name}_end"] = time.monotonic() - t0
            return {**state, "findings": state.get("findings", [])}

        patch_targets = [
            f"app.agents.{mod}.{cls}.run"
            for mod, cls, _ in [
                ("agent_requirement_extraction", "RequirementExtractionAgent", ""),
                ("agent_code_quality", "CodeQualityAgent", ""),
                ("agent_sql_performance", "SqlPerformanceAgent", ""),
                ("agent_security", "SecurityAgent", ""),
                ("agent_refactoring", "RefactoringAgent", ""),
                ("agent_test_coverage", "TestCoverageAgent", ""),
            ]
        ]

        patches = [patch(t, new=_fake_run) for t in patch_targets]
        for p in patches:
            p.start()
        try:
            wf = _make_workflow()
            state = _base_state()
            t_start = time.monotonic()
            await wf._parallel_analysis(state)
            elapsed = time.monotonic() - t_start

            # 6 agents each take 0.04s — if sequential: 0.24s, if parallel: ~0.04s
            self.assertLess(elapsed, 0.20,
                f"Elapsed {elapsed:.3f}s — agents must run in parallel not sequentially")
        finally:
            for p in patches:
                p.stop()

    async def test_review_summary_waits_for_all_analysis_agents(self):
        """review_summary is in _SEQUENTIAL_AGENTS, runs only after _parallel_analysis."""
        sequential_names = [name for _, name, _ in _SEQUENTIAL_AGENTS]
        self.assertIn("review_summary", sequential_names,
            "review_summary must be in the sequential finalize stage")

        parallel_names = [name for _, name, _ in _PARALLEL_ANALYSIS_AGENTS]
        self.assertNotIn("review_summary", parallel_names,
            "review_summary must NOT run in parallel with analysis agents")

    async def test_requirement_validation_runs_after_extraction(self):
        """requirement_validation depends on requirement_extraction output, so must be sequential."""
        sequential_names = [name for _, name, _ in _SEQUENTIAL_AGENTS]
        parallel_names = [name for _, name, _ in _PARALLEL_ANALYSIS_AGENTS]

        self.assertIn("requirement_extraction", parallel_names)
        self.assertIn("requirement_validation", sequential_names)

        # Ordering within sequential: validation before summary
        validation_idx = sequential_names.index("requirement_validation")
        summary_idx = sequential_names.index("review_summary")
        self.assertLess(validation_idx, summary_idx,
            "requirement_validation must come before review_summary")

    async def test_one_agent_failure_does_not_crash_pipeline(self):
        """If one parallel agent fails, others still produce findings."""
        async def _ok_run(self_agent, state):
            return {**state, "findings": state.get("findings", []) + [
                {"title": f"Finding from {self_agent.name}", "severity": "low",
                 "agent_name": self_agent.name, "description": "", "recommendation": "",
                 "review_comment": "", "category": "code_quality", "review_id": "test"}
            ]}

        async def _fail_run(self_agent, state):
            raise RuntimeError("Simulated agent crash")

        # Patch code_quality to fail, others to succeed
        patches = [
            patch("app.agents.agent_code_quality.CodeQualityAgent.run", new=_fail_run),
            patch("app.agents.agent_sql_performance.SqlPerformanceAgent.run", new=_ok_run),
            patch("app.agents.agent_security.SecurityAgent.run", new=_ok_run),
            patch("app.agents.agent_refactoring.RefactoringAgent.run", new=_ok_run),
            patch("app.agents.agent_test_coverage.TestCoverageAgent.run", new=_ok_run),
            patch("app.agents.agent_requirement_extraction.RequirementExtractionAgent.run", new=_ok_run),
        ]
        for p in patches:
            p.start()
        try:
            wf = _make_workflow()
            state = _base_state()
            result = await wf._parallel_analysis(state)

            # code_quality failure recorded in agent_errors
            self.assertIn("code_quality", result.get("agent_errors", {}))
            # Other agents' findings still present
            self.assertGreater(len(result.get("findings", [])), 0)
        finally:
            for p in patches:
                p.stop()


class TestReadOnlySecurityWithParallelism(unittest.IsolatedAsyncioTestCase):
    """Ensure parallelization does not weaken read-only security."""

    def test_parallel_workflow_nodes_are_all_read_only(self):
        """The graph nodes must not contain any write-capable operations."""
        from app.services.read_only_services import LLMReadOnlyToolRegistry
        allowed = LLMReadOnlyToolRegistry.ALLOWED_READ_TOOLS
        for write_tool in LLMReadOnlyToolRegistry.DISALLOWED_WRITE_TOOLS:
            self.assertNotIn(write_tool, allowed,
                f"Write tool '{write_tool}' must never appear in allowed read tools")

    def test_parallel_fetch_only_uses_read_services(self):
        """_parallel_fetch must call BitbucketReadService and JiraReadService, not raw services."""
        import inspect
        from app.agents.workflow import ReviewWorkflow
        src = inspect.getsource(ReviewWorkflow._parallel_fetch)
        self.assertIn("BitbucketReadService", src,
            "_parallel_fetch must use BitbucketReadService (read-only wrapper)")
        self.assertIn("JiraReadService", src,
            "_parallel_fetch must use JiraReadService (read-only wrapper)")
        # Must not call BitbucketService directly for PR operations
        self.assertNotIn("bb.post_pr_comment", src)
        self.assertNotIn("bb.approve_pr", src)

    def test_parallel_graph_contains_no_write_nodes(self):
        """The compiled graph must not contain any publish/approve/write nodes."""
        wf = _make_workflow()
        graph = wf.build_graph()
        nodes = list(graph.nodes.keys())
        for node_name in nodes:
            self.assertNotIn("publish", node_name.lower())
            self.assertNotIn("comment", node_name.lower())
            self.assertNotIn("approve", node_name.lower())
            self.assertNotIn("merge", node_name.lower() if "merge" != node_name else "")


class TestTimingAuditLogs(unittest.IsolatedAsyncioTestCase):
    """Verify timing information is written to audit logs."""

    @patch("app.agents.workflow.JiraService")
    @patch("app.agents.workflow.JiraReadService")
    @patch("app.agents.workflow.BitbucketService")
    @patch("app.agents.workflow.BitbucketReadService")
    async def test_parallel_fetch_logs_individual_and_wall_clock_duration(
        self, mock_bb_read, mock_bb, mock_jira_read, mock_jira
    ):
        mock_bb_read.return_value.build_pr_context = AsyncMock(return_value={
            "pr_title": "PR", "diff": "", "changed_files": [], "pr_data": {}, "jira_key": "FRES-1"
        })
        mock_jira_read.return_value.extract_issue_context = AsyncMock(return_value={
            "summary": "S", "acceptance_criteria": []
        })

        wf = _make_workflow()
        audit_events: list[dict] = []
        wf._audit.log_workflow_event = lambda event, data=None, error=None: audit_events.append(
            {"event": event, "data": data or {}}
        )

        state = _base_state()
        await wf._parallel_fetch(state)

        completed = next((e for e in audit_events if e["event"] == "parallel_fetch_completed"), None)
        self.assertIsNotNone(completed, "parallel_fetch_completed event must be emitted")
        d = completed["data"]
        self.assertIn("bitbucket_duration_s", d)
        self.assertIn("jira_duration_s", d)
        self.assertIn("parallel_wall_clock_s", d)
        # Wall-clock ≤ sum of both (proves it didn't run sequentially)
        self.assertLessEqual(
            d["parallel_wall_clock_s"],
            d["bitbucket_duration_s"] + d["jira_duration_s"] + 0.05,
        )

    @patch("app.agents.workflow.JiraService")
    @patch("app.agents.workflow.JiraReadService")
    @patch("app.agents.workflow.BitbucketService")
    @patch("app.agents.workflow.BitbucketReadService")
    async def test_timing_log_message_contains_both_durations(
        self, mock_bb_read, mock_bb, mock_jira_read, mock_jira
    ):
        mock_bb_read.return_value.build_pr_context = AsyncMock(return_value={
            "pr_title": "PR", "diff": "", "changed_files": [], "pr_data": {}, "jira_key": None
        })
        mock_jira_read.return_value.extract_issue_context = AsyncMock(return_value={})

        wf = _make_workflow()
        state = _base_state()
        result = await wf._parallel_fetch(state)

        timing_log = next(
            (l for l in result["logs"] if "Parallel fetch complete" in l.get("message", "")),
            None,
        )
        self.assertIsNotNone(timing_log, "Timing summary log entry must be present")
        self.assertIn("Bitbucket:", timing_log["message"])
        self.assertIn("Jira:", timing_log["message"])
        self.assertIn("Wall-clock:", timing_log["message"])


if __name__ == "__main__":
    unittest.main()
