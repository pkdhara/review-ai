"""
Bitbucket API integration service.
Handles PR retrieval, diff parsing, and comment publishing.
"""

import asyncio
import base64
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger
from app.core.review_logger import ReviewAuditLogger

logger = get_logger(__name__)


class BitbucketService:
    """Client for the Bitbucket Cloud REST API v2."""

    BASE_URL = "https://api.bitbucket.org/2.0"

    def __init__(
        self,
        access_token: str,
        workspace: Optional[str] = None,
        review_id: Optional[str] = None,
        email: Optional[str] = None,
    ):
        self.access_token = (access_token or "").strip()
        self.workspace = workspace
        
        # Determine correct Auth header:
        # Atlassian tokens starting with ATATT3... or containing email:token require Basic auth
        if ":" in self.access_token:
            auth_header = f"Basic {base64.b64encode(self.access_token.encode()).decode()}"
        elif self.access_token.startswith("ATATT3") or email:
            user_email = email or getattr(settings, "JIRA_EMAIL", "") or "pdhara@argusoft.in"
            pair = f"{user_email}:{self.access_token}"
            auth_header = f"Basic {base64.b64encode(pair.encode()).decode()}"
        else:
            auth_header = f"Bearer {self.access_token}"

        self.headers = {
            "Authorization": auth_header,
        }
        self._audit = ReviewAuditLogger(review_id or "unknown")

    @staticmethod
    def _is_transient_error(exc: Exception) -> bool:
        """Retry only on network errors or 5xx server errors, not 4xx client errors."""
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if 400 <= status < 500:
                return False
        return True

    @retry(
        retry=retry_if_exception(_is_transient_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        t0 = time.monotonic()
        try:
            headers = dict(self.headers)
            headers["Accept"] = "application/json"

            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                url = f"{self.BASE_URL}{path}" if not path.startswith("http") else path
                resp = await client.get(url, headers=headers, params=params)

                resp.raise_for_status()
                data = resp.json()
                self._audit.log_bitbucket_call(
                    f"GET {path}",
                    request={"params": params},
                    response=data,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                return data
        except Exception as exc:
            self._audit.log_bitbucket_call(
                f"GET {path}",
                request={"params": params},
                error=str(exc),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
            raise

    @retry(
        retry=retry_if_exception(_is_transient_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _post(self, path: str, body: Dict) -> Dict:
        t0 = time.monotonic()
        try:
            post_headers = {**self.headers, "Content-Type": "application/json", "Accept": "application/json"}
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.post(f"{self.BASE_URL}{path}", headers=post_headers, json=body)
                resp.raise_for_status()
                data = resp.json()
                self._audit.log_bitbucket_call(
                    f"POST {path}",
                    request={"body": body},
                    response=data,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                return data
        except Exception as exc:
            self._audit.log_bitbucket_call(
                f"POST {path}",
                request={"body": body},
                error=str(exc),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
            raise

    # ── URL Parsing ───────────────────────────────────────────────────────────
    @staticmethod
    def parse_pr_url(pr_url: str) -> Tuple[str, str, int]:
        """
        Parse a Bitbucket PR URL and return (workspace, repo_slug, pr_number).
        Supports both:
          https://bitbucket.org/{workspace}/{repo}/pull-requests/{number}
          https://bitbucket.org/{workspace}/{repo}/pull-requests/{number}/overview
        """
        parsed = urlparse(pr_url)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 4 or parts[2] != "pull-requests":
            raise ValueError(f"Cannot parse PR URL: {pr_url}")
        workspace = parts[0]
        repo_slug = parts[1]
        pr_number = int(parts[3])
        return workspace, repo_slug, pr_number

    async def get_pull_request(self, workspace: str, repo_slug: str, pr_number: int) -> Dict:
        """Fetch full PR metadata."""
        data = await self._get(f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_number}")
        return data

    async def get_pr(self, repo_slug: str, pr_number: int) -> Dict:
        """Convenience alias for get_pull_request using instance workspace."""
        workspace = self.workspace
        if not workspace:
            raise ValueError("Workspace is not set on BitbucketService instance.")
        return await self.get_pull_request(workspace, repo_slug, pr_number)

    async def get_diff(self, repo_slug: str, pr_number: int, pr_data: Optional[Dict] = None) -> str:
        """Convenience alias for get_pr_diff using instance workspace."""
        workspace = self.workspace
        if not workspace:
            raise ValueError("Workspace is not set on BitbucketService instance.")
        return await self.get_pr_diff(workspace, repo_slug, pr_number, pr_data=pr_data)

    @retry(
        retry=retry_if_exception(_is_transient_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def get_pr_diff(
        self,
        workspace: str,
        repo_slug: str,
        pr_number: int,
        pr_data: Optional[Dict] = None,
    ) -> str:
        """
        Fetch complete unified diff text for the PR.
        Sequence:
          1. Canonical PR /diff endpoint (with %0D -> .. redirect sanitization).
          2. Canonical PR /patch endpoint as fallback.
          3. Direct commit range diff only if canonical endpoints are unavailable.
        """
        t0 = time.monotonic()
        diff_headers = {
            "Authorization": self.headers.get("Authorization"),
        }

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
            # 1. Canonical PR /diff endpoint
            url = f"{self.BASE_URL}/repositories/{workspace}/{repo_slug}/pullrequests/{pr_number}/diff"
            try:
                resp = await client.get(url, headers=diff_headers)
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if location:
                        location = location.replace("%0D", "..").replace("\r", "..").replace("%0A", "").replace("\n", "")
                        req_headers = diff_headers if "bitbucket.org" in location else {}
                        resp = await client.get(location, headers=req_headers)

                if resp.status_code == 200 and resp.text and not resp.text.startswith('{"type": "error"'):
                    text = resp.text
                    self._audit.log_bitbucket_call(
                        "get_pr_diff",
                        request={"workspace": workspace, "repo": repo_slug, "pr": pr_number, "endpoint": "/diff"},
                        response=f"{len(text)} chars of diff",
                        duration_ms=int((time.monotonic() - t0) * 1000),
                    )
                    return text
            except Exception as e:
                logger.warning(f"Error fetching canonical PR /diff endpoint: {e}")

            # 2. Canonical PR /patch endpoint
            try:
                patch_url = f"{self.BASE_URL}/repositories/{workspace}/{repo_slug}/pullrequests/{pr_number}/patch"
                resp = await client.get(patch_url, headers=diff_headers)
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if location:
                        location = location.replace("%0D", "..").replace("\r", "..").replace("%0A", "").replace("\n", "")
                        req_headers = diff_headers if "bitbucket.org" in location else {}
                        resp = await client.get(location, headers=req_headers)

                if resp.status_code == 200 and resp.text and not resp.text.startswith('{"type": "error"'):
                    text = resp.text
                    self._audit.log_bitbucket_call(
                        "get_pr_diff",
                        request={"workspace": workspace, "repo": repo_slug, "pr": pr_number, "endpoint": "/patch"},
                        response=f"{len(text)} chars of patch",
                        duration_ms=int((time.monotonic() - t0) * 1000),
                    )
                    return text
            except Exception as e:
                logger.warning(f"Error fetching canonical PR /patch endpoint: {e}")

            # 3. Direct commit range diff fallback
            if not pr_data:
                try:
                    pr_data = await self.get_pull_request(workspace, repo_slug, pr_number)
                except Exception:
                    pass

            if pr_data:
                src = pr_data.get("source", {}).get("commit", {}).get("hash")
                dst = pr_data.get("destination", {}).get("commit", {}).get("hash")
                if src and dst:
                    for range_spec in (f"{dst}..{src}", f"{src}..{dst}"):
                        commit_diff_url = f"{self.BASE_URL}/repositories/{workspace}/{repo_slug}/diff/{range_spec}"
                        resp = await client.get(commit_diff_url, headers=diff_headers)
                        if resp.status_code == 200 and resp.text and not resp.text.startswith('{"type": "error"'):
                            text = resp.text
                            self._audit.log_bitbucket_call(
                                "get_pr_diff",
                                request={"workspace": workspace, "repo": repo_slug, "pr": pr_number, "commit_range": range_spec},
                                response=f"{len(text)} chars of diff",
                                duration_ms=int((time.monotonic() - t0) * 1000),
                            )
                            return text

            raise ValueError(f"Unable to retrieve complete PR diff for PR #{pr_number}")

    async def get_changed_files(
        self,
        workspace: str,
        repo_slug: str,
        pr_number: int,
        pr_data: Optional[Dict] = None,
    ) -> List[Dict]:
        """List all files changed in the PR using canonical PR diffstat endpoint."""
        result = []
        url = f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_number}/diffstat"
        try:
            while url:
                data = await self._get(url)
                if data and "values" in data:
                    result.extend(data.get("values", []))
                next_url = data.get("next")
                if next_url:
                    url = next_url.replace(self.BASE_URL, "")
                else:
                    url = None
            if result:
                return result
        except Exception as e:
            logger.warning(f"Failed to fetch canonical PR diffstat for PR #{pr_number}: {e}")

        # Fallback to direct commit range diffstat if available
        if not pr_data:
            try:
                pr_data = await self.get_pull_request(workspace, repo_slug, pr_number)
            except Exception:
                pass

        if pr_data:
            dst = pr_data.get("destination", {}).get("commit", {}).get("hash")
            src = pr_data.get("source", {}).get("commit", {}).get("hash")
            if dst and src:
                try:
                    data = await self._get(f"/repositories/{workspace}/{repo_slug}/diffstat/{dst}..{src}")
                    if data and "values" in data:
                        return data.get("values", [])
                except Exception as e:
                    logger.warning(f"Could not fetch fallback commit diffstat: {e}")

        return result

    async def get_commits(self, workspace: str, repo_slug: str, pr_number: int) -> List[Dict]:
        """Fetch commits in the PR."""
        try:
            data = await self._get(f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_number}/commits")
            return data.get("values", [])
        except Exception as e:
            logger.warning(f"Could not fetch PR commits: {e}")
            return []

    async def get_existing_comments(self, workspace: str, repo_slug: str, pr_number: int) -> List[Dict]:
        """Retrieve existing review comments."""
        try:
            data = await self._get(f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_number}/comments")
            return data.get("values", [])
        except Exception as e:
            logger.warning(f"Could not fetch existing PR comments: {e}")
            return []

    async def get_file_content(self, workspace: str, repo_slug: str, commit_hash: str, file_path: str) -> str:
        """Fetch raw file content at a specific commit."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.BASE_URL}/repositories/{workspace}/{repo_slug}/src/{commit_hash}/{file_path}",
                headers=self.headers,
            )
            if resp.status_code == 404:
                return ""
            resp.raise_for_status()
            return resp.text

    # ── Publishing ────────────────────────────────────────────────────────────
    async def post_pr_comment(
        self,
        workspace: str,
        repo_slug: str,
        pr_number: int,
        comment_text: str,
        file_path: Optional[str] = None,
        line: Optional[int] = None,
    ) -> Dict:
        """Post an inline or general comment on a PR."""
        body: Dict[str, Any] = {"content": {"raw": comment_text}}
        if file_path and line:
            body["inline"] = {
                "path": file_path,
                "to": line,
            }
        result = await self._post(
            f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_number}/comments",
            body,
        )
        return result

    # ── Jira key extraction ───────────────────────────────────────────────────
    @staticmethod
    def extract_jira_key(text: str) -> Optional[str]:
        """
        Extract a Jira issue key (e.g., POR-192) from branch names, titles,
        or commit messages using a lenient regex.
        """
        if not text:
            return None
        pattern = r"\b([A-Z][A-Z0-9]+-\d+)\b"
        match = re.search(pattern, text.upper())
        return match.group(1) if match else None

    @staticmethod
    def parse_diff_file_paths(diff_text: str) -> List[str]:
        """
        Parse a unified diff text and extract all modified/added/deleted file paths.
        Matches lines like: diff --git a/path/to/file b/path/to/file
        """
        paths = []
        if not diff_text:
            return paths
        for line in diff_text.splitlines():
            if line.startswith("diff --git"):
                parts = line.split()
                if len(parts) >= 4:
                    b_path = parts[3]
                    if b_path.startswith("b/"):
                        paths.append(b_path[2:])
                    elif b_path.startswith("a/"):
                        paths.append(b_path[2:])
                    else:
                        paths.append(b_path)
        return list(dict.fromkeys(paths))

    async def build_pr_context(
        self,
        workspace: str,
        repo_slug: str,
        pr_number: int,
        pr_data: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """
        Aggregate all PR context data needed by agents:
        - PR metadata, diff, changed files, commits, existing comments.
        - Jira key extracted from branch/title/commits.
        Validates completeness between diffstat and diff text.
        """
        logger.info("Fetching PR context", workspace=workspace, repo=repo_slug, pr=pr_number)

        if not pr_data:
            pr_data = await self.get_pull_request(workspace, repo_slug, pr_number)

        # Parallelize independent Bitbucket API calls for maximum performance
        diff, changed_files, commits, existing_comments = await asyncio.gather(
            self.get_pr_diff(workspace, repo_slug, pr_number, pr_data=pr_data),
            self.get_changed_files(workspace, repo_slug, pr_number, pr_data=pr_data),
            self.get_commits(workspace, repo_slug, pr_number),
            self.get_existing_comments(workspace, repo_slug, pr_number),
        )

        logger.info(
            "PR context fetched from Bitbucket",
            workspace=workspace,
            repo_slug=repo_slug,
            pr_number=pr_number,
            commits_count=len(commits),
            files_changed_count=len(changed_files),
            diff_bytes=len(diff),
        )
        
        if not diff.strip() or not changed_files:
            raise ValueError(f"No changes found in PR #{pr_number}. The diff is empty.")

        # Extract paths from diffstat and diff text for completeness validation
        diffstat_paths = set()
        for f in changed_files:
            p = (f.get("new") or f.get("old") or {}).get("path")
            if p:
                diffstat_paths.add(p)

        parsed_diff_paths = set(self.parse_diff_file_paths(diff))

        # Check completeness: if diffstat lists multiple files but parsed diff misses files
        if len(diffstat_paths) > 1 and len(parsed_diff_paths) < len(diffstat_paths):
            missing_files = sorted(list(diffstat_paths - parsed_diff_paths))
            err_msg = (
                f"Incomplete PR diff detected for PR #{pr_number}: "
                f"expected_changed_files={len(diffstat_paths)}, "
                f"diff_changed_files={len(parsed_diff_paths)}, "
                f"missing_files={missing_files}"
            )
            logger.error(
                "bitbucket.incomplete_diff",
                pr=pr_number,
                expected=len(diffstat_paths),
                actual=len(parsed_diff_paths),
                missing=missing_files,
            )
            self._audit.log_workflow_event("incomplete_diff_error", data={
                "pr_number": pr_number,
                "expected_files": len(diffstat_paths),
                "actual_files": len(parsed_diff_paths),
                "missing_files": missing_files,
            })
            raise ValueError(err_msg)

        # Extract Jira key — try branch first, then title, then commits
        source_branch = pr_data.get("source", {}).get("branch", {}).get("name", "")
        pr_title = pr_data.get("title", "")
        jira_key = (
            self.extract_jira_key(source_branch)
            or self.extract_jira_key(pr_title)
            or next(
                (
                    self.extract_jira_key(c.get("message", ""))
                    for c in commits
                    if self.extract_jira_key(c.get("message", ""))
                ),
                None,
            )
        )

        return {
            "pr_data": pr_data,
            "diff": diff,
            "changed_files": changed_files,
            "commits": commits,
            "existing_comments": existing_comments,
            "jira_key": jira_key,
            "workspace": workspace,
            "repo_slug": repo_slug,
            "pr_number": pr_number,
            "source_branch": source_branch,
            "target_branch": pr_data.get("destination", {}).get("branch", {}).get("name", ""),
            "pr_title": pr_title,
            "author": pr_data.get("author", {}).get("display_name", ""),
        }
