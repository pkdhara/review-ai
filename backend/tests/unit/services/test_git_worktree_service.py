"""
Unit tests for GitWorktreeManager (Standard unittest compatible)
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from app.services.git_worktree_service import GitWorktreeManager
from app.core.config import Settings


class TestGitWorktreeManager(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.settings = Settings(
            LOCAL_REPO_BASE_DIR=str(self.tmp_path / "repos"),
            WORKTREE_BASE_DIR=str(self.tmp_path / "worktrees"),
        )
        self.repo_dir = self.tmp_path / "repos" / "fc-angular"
        self.repo_dir.mkdir(parents=True)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_resolve_repo_path(self):
        mgr = GitWorktreeManager(self.settings)
        path = mgr.resolve_repo_path("fc-angular")
        self.assertIsNotNone(path)
        self.assertEqual(Path(path).resolve(), self.repo_dir.resolve())

    def test_commit_exists_locally_true(self):
        mgr = GitWorktreeManager(self.settings)

        async def run():
            with patch.object(mgr, "_run_git", new_callable=AsyncMock) as mock_git:
                mock_git.return_value = (0, "abc12345", "")
                exists = await mgr.commit_exists_locally(str(self.repo_dir), "abc12345")
                self.assertTrue(exists)
                mock_git.assert_called_once()
                self.assertEqual(mock_git.call_args[0], (str(self.repo_dir), "rev-parse", "--verify", "abc12345^{commit}"))

        asyncio.run(run())

    def test_commit_exists_locally_false(self):
        mgr = GitWorktreeManager(self.settings)

        async def run():
            with patch.object(mgr, "_run_git", new_callable=AsyncMock) as mock_git:
                mock_git.return_value = (1, "", "fatal: Not a valid object name")
                exists = await mgr.commit_exists_locally(str(self.repo_dir), "missing_sha")
                self.assertFalse(exists)

        asyncio.run(run())

    def test_prepare_worktree_success(self):
        mgr = GitWorktreeManager(self.settings)

        async def run():
            with patch.object(mgr, "commit_exists_locally", new_callable=AsyncMock, return_value=True), \
                 patch.object(mgr, "_run_git", new_callable=AsyncMock, return_value=(0, "Worktree created", "")):

                wt_path = await mgr.prepare_worktree("fc-angular", "abc12345", "test-review-001")
                self.assertTrue(wt_path.endswith("test-review-001"))
                self.assertEqual(Path(wt_path).parent, Path(self.settings.WORKTREE_BASE_DIR))

        asyncio.run(run())

    def test_prepare_worktree_missing_commit_fetches_remote(self):
        mgr = GitWorktreeManager(self.settings)

        async def run():
            with patch.object(mgr, "commit_exists_locally", new_callable=AsyncMock, return_value=True), \
                 patch.object(mgr, "fetch_commit_from_remote", new_callable=AsyncMock, return_value=True), \
                 patch.object(mgr, "_run_git", new_callable=AsyncMock, return_value=(0, "Worktree created", "")):

                wt_path = await mgr.prepare_worktree("fc-angular", "remote_commit_sha", "test-review-002")
                self.assertTrue(wt_path.endswith("test-review-002"))

        asyncio.run(run())

    def test_get_authenticated_remote_url(self):
        self.settings.BITBUCKET_ACCESS_TOKEN = "test-token"
        self.settings.BITBUCKET_USERNAME = "pradeep30"
        mgr = GitWorktreeManager(self.settings)

        async def run():
            with patch.object(mgr, "_run_git", new_callable=AsyncMock, return_value=(0, "https://bitbucket.org/org/repo.git", "")):
                url = await mgr._get_authenticated_remote_url(str(self.repo_dir))
                self.assertEqual(url, "https://pradeep30:test-token@bitbucket.org/org/repo.git")

        asyncio.run(run())

    def test_fetch_commit_from_remote_fallback_refspec(self):
        mgr = GitWorktreeManager(self.settings)

        async def run():
            # commit_exists_locally: initial check (False), after branch fetch (False), after SHA fetch (False), after refspec fetch (True)
            with patch.object(mgr, "commit_exists_locally", new_callable=AsyncMock, side_effect=[False, False, False, True]), \
                 patch.object(mgr, "_get_authenticated_remote_url", new_callable=AsyncMock, return_value="https://target"), \
                 patch.object(mgr, "_run_git", new_callable=AsyncMock, return_value=(0, "", "")):

                res = await mgr.fetch_commit_from_remote(str(self.repo_dir), "target_sha", source_branch="feature/branch")
                self.assertTrue(res)

        asyncio.run(run())

    def test_cleanup_worktree(self):
        mgr = GitWorktreeManager(self.settings)
        wt_dir = Path(self.settings.WORKTREE_BASE_DIR) / "test-review-003"
        wt_dir.mkdir(parents=True, exist_ok=True)

        async def run():
            with patch.object(mgr, "_run_git", new_callable=AsyncMock, return_value=(0, "", "")):
                await mgr.cleanup_worktree("fc-angular", "test-review-003")
                self.assertFalse(wt_dir.exists())

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
