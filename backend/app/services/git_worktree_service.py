"""
Git Worktree Manager Service
Handles isolated Git worktrees for PR reviews using local git repositories.
"""

import asyncio
import os
import shutil
from pathlib import Path
from typing import Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.review_logger import ReviewAuditLogger

logger = get_logger(__name__)


class GitWorktreeManager:
    """
    Manages local Git repositories and creates isolated Git worktrees
    detached at the PR source commit SHA for review isolation.
    """

    def __init__(self, settings=None):
        self.settings = settings or get_settings()

    async def _run_git(self, cwd: str, *args: str, timeout: float = 8.0) -> tuple[int, str, str]:
        """Execute a git command asynchronously in the specified directory with timeout."""
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-c",
            "safe.directory=*",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return (
                proc.returncode or 0,
                stdout.decode("utf-8", errors="replace").strip(),
                stderr.decode("utf-8", errors="replace").strip(),
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return (1, "", "Git command execution timed out")

    def resolve_repo_path(self, repo_slug: str) -> Optional[str]:
        """Find the local repository path for the given repository slug."""
        return self.settings.resolve_repo_path(repo_slug)

    async def _get_authenticated_remote_url(self, repo_path: str, custom_token: Optional[str] = None) -> Optional[str]:
        """
        Gets origin remote URL and injects BITBUCKET_ACCESS_TOKEN & BITBUCKET_USERNAME
        for headless git fetching over HTTPS.
        """
        token = (custom_token or getattr(self.settings, "BITBUCKET_ACCESS_TOKEN", "") or os.environ.get("BITBUCKET_ACCESS_TOKEN", "") or "").strip()
        if not token:
            return None

        code, remote_url, _ = await self._run_git(repo_path, "remote", "get-url", "origin", timeout=5.0)
        if code != 0 or not remote_url:
            return None

        import urllib.parse
        encoded_token = urllib.parse.quote(token, safe="")

        if remote_url.startswith("https://"):
            url_no_scheme = remote_url[8:]
            configured_username = (getattr(self.settings, "BITBUCKET_USERNAME", "") or os.environ.get("BITBUCKET_USERNAME", "") or "").strip()

            if "@" in url_no_scheme:
                url_user, url_no_scheme = url_no_scheme.rsplit("@", 1)
                username = configured_username or url_user or "x-token-auth"
            else:
                username = configured_username or "x-token-auth"

            return f"https://{username}:{encoded_token}@{url_no_scheme}"

        return None

    async def commit_exists_locally(self, repo_path: str, commit_sha: str) -> bool:
        """Check if a commit SHA exists in the local Git repository."""
        if not commit_sha:
            return False
        code, stdout, _ = await self._run_git(repo_path, "rev-parse", "--verify", f"{commit_sha}^{{commit}}", timeout=3.0)
        return code == 0 and bool(stdout)

    async def fetch_commit_from_remote(
        self,
        repo_path: str,
        commit_sha: str,
        source_branch: Optional[str] = None,
        bitbucket_token: Optional[str] = None,
    ) -> bool:
        """
        Fetch a missing commit ref/objects from origin remote into local repo.
        Does NOT clone or redownload the full repository.
        """
        logger.info("Fetching missing commit from remote", repo_path=repo_path, commit=commit_sha, branch=source_branch)

        # Quick check: if commit is already available locally, return True immediately
        if await self.commit_exists_locally(repo_path, commit_sha):
            return True

        auth_url = await self._get_authenticated_remote_url(repo_path, custom_token=bitbucket_token)
        remote_target = auth_url or "origin"

        # 1. Attempt targeted branch fetch if source_branch provided
        if source_branch:
            clean_branch = source_branch.replace("refs/heads/", "").strip()
            refspec = f"+refs/heads/{clean_branch}:refs/remotes/origin/{clean_branch}"
            await self._run_git(repo_path, "fetch", remote_target, refspec, timeout=12.0)
            if await self.commit_exists_locally(repo_path, commit_sha):
                return True

            await self._run_git(repo_path, "fetch", remote_target, clean_branch, timeout=12.0)
            if await self.commit_exists_locally(repo_path, commit_sha):
                return True

        # 2. Attempt specific commit SHA fetch (if Git server allows fetching arbitrary SHAs)
        await self._run_git(repo_path, "fetch", remote_target, commit_sha, timeout=10.0)
        if await self.commit_exists_locally(repo_path, commit_sha):
            return True

        # 3. Fallback: fetch remote branch heads (increased timeout to 35s for large repos)
        code, _, stderr = await self._run_git(
            repo_path, "fetch", remote_target, "+refs/heads/*:refs/remotes/origin/*", timeout=35.0
        )
        if await self.commit_exists_locally(repo_path, commit_sha):
            return True

        logger.warning(
            "Git fetch failed or non-authenticated token",
            repo_path=repo_path,
            commit=commit_sha,
            error=stderr,
        )
        return False

    async def prepare_worktree(
        self,
        repo_slug: str,
        source_commit: str,
        review_id: str,
        source_branch: Optional[str] = None,
        bitbucket_token: Optional[str] = None,
    ) -> str:
        """
        Creates an isolated git worktree for a review detached at source_commit.
        Returns the absolute filesystem path to the worktree.
        Raises ValueError or RuntimeError on failure.
        """
        audit = ReviewAuditLogger(review_id)
        repo_path = self.resolve_repo_path(repo_slug)
        if not repo_path or not Path(repo_path).exists():
            msg = f"[CodeContext] Local project repository not found for slug '{repo_slug}'"
            logger.error(msg, repo_slug=repo_slug)
            audit.log_workflow_event("worktree_error", error=msg)
            raise ValueError(msg)

        logger.info(
            "[CodeContext] Local project repository located",
            repo_slug=repo_slug,
            repo_path=repo_path,
            source_commit=source_commit,
            review_id=review_id,
        )

        # Always fetch latest from remote first
        logger.info("[CodeContext] Fetching latest commits from remote into local project before worktree creation", repo_path=repo_path, commit=source_commit)
        await self.fetch_commit_from_remote(
            repo_path, source_commit, source_branch=source_branch, bitbucket_token=bitbucket_token
        )

        # Ensure commit exists locally after fetch
        exists = await self.commit_exists_locally(repo_path, source_commit)
        if not exists:
            msg = f"[CodeContext] Could not locate commit {source_commit} in local project at '{repo_path}' or on remote"
            logger.error(msg, repo=repo_slug, commit=source_commit, repo_path=repo_path)
            audit.log_workflow_event("worktree_error", error=msg)
            raise RuntimeError(msg)

        logger.info(
            "[CodeContext] Commit located in local project repository",
            repo_slug=repo_slug,
            repo_path=repo_path,
            commit=source_commit,
        )

        worktree_base = Path(self.settings.WORKTREE_BASE_DIR)
        worktree_base.mkdir(parents=True, exist_ok=True)
        worktree_dir = worktree_base / review_id

        # Clean up existing worktree dir if it already exists from a prior attempt
        if worktree_dir.exists():
            await self.cleanup_worktree(repo_slug, review_id)

        # Create isolated worktree
        code, stdout, stderr = await self._run_git(
            repo_path,
            "worktree",
            "add",
            "--detach",
            str(worktree_dir),
            source_commit,
        )

        if code != 0:
            msg = f"[CodeContext] Failed to create worktree from local project: {stderr or stdout}"
            logger.error(msg, repo_slug=repo_slug, review_id=review_id, repo_path=repo_path)
            audit.log_workflow_event("worktree_creation_failed", error=msg)
            raise RuntimeError(msg)

        logger.info(
            "[CodeContext] Successfully fetched & created worktree from local project for full code reference",
            review_id=review_id,
            worktree_path=str(worktree_dir),
            repo_path=repo_path,
            commit=source_commit,
        )
        audit.log_workflow_event(
            "worktree_created",
            data={
                "worktree_path": str(worktree_dir),
                "source_commit": source_commit,
                "repo_path": repo_path,
            },
        )
        return str(worktree_dir)

    async def cleanup_worktree(self, repo_slug: str, review_id: str) -> None:
        """
        Safely removes a review's worktree.
        Does NOT touch or modify the main working directory or interrupt concurrent reviews.
        """
        audit = ReviewAuditLogger(review_id)
        worktree_base = Path(self.settings.WORKTREE_BASE_DIR)
        worktree_dir = worktree_base / review_id
        repo_path = self.resolve_repo_path(repo_slug)

        if worktree_dir.exists() and repo_path and Path(repo_path).exists():
            try:
                await self._run_git(repo_path, "worktree", "remove", "--force", str(worktree_dir))
            except Exception as e:
                logger.warning("Git worktree remove command warning", error=str(e))

        if worktree_dir.exists():
            try:
                import shutil
                shutil.rmtree(worktree_dir, ignore_errors=True)
            except Exception as e:
                logger.warning("Failed directory cleanup for worktree", path=str(worktree_dir), error=str(e))

        logger.info("[CodeContext] Cleaned up worktree", review_id=review_id, worktree_path=str(worktree_dir))
        audit.log_workflow_event("worktree_cleaned", data={"review_id": review_id})


git_worktree_manager = GitWorktreeManager()
