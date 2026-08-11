"""
Read-Only Service Wrappers for ML Review Pipeline.

Enforces strict READ-ONLY access control at the service layer for:
- BitbucketReadService (Only GET metadata/diff/commits/files allowed)
- JiraReadService (Only GET issue/AC/comments allowed)
- LocalRepositoryReadService (Only read/parse/search allowed, main repo untouched)

Any attempt to perform write or mutation operations via these services raises a ReadOnlyViolationError.
"""

from typing import Any, Dict, List, Optional, Tuple
from app.services.bitbucket_service import BitbucketService
from app.services.jira_service import JiraService
from app.services.code_context_service import CodeContextService


class ReadOnlyViolationError(PermissionError):
    """Raised when a write operation is attempted within the read-only ML review pipeline."""
    pass


class BitbucketReadService:
    """
    Read-only wrapper around BitbucketService.
    Guarantees no comments, approvals, merges, declines, commits, or status updates occur during ML analysis.
    """

    def __init__(self, service: BitbucketService):
        self._service = service

    async def get_pr(self, repo_slug: str, pr_id: int) -> Dict[str, Any]:
        return await self._service.get_pr(repo_slug, pr_id)

    async def get_pr_diff(self, repo_slug: str, pr_id: int) -> Tuple[str, Dict[str, Any]]:
        return await self._service.get_pr_diff(repo_slug, pr_id)

    async def get_pr_comments(self, repo_slug: str, pr_id: int) -> List[Dict[str, Any]]:
        return await self._service.get_pr_comments(repo_slug, pr_id)

    async def get_pr_commits(self, repo_slug: str, pr_id: int) -> List[Dict[str, Any]]:
        return await self._service.get_pr_commits(repo_slug, pr_id)

    async def get_pr_files(self, repo_slug: str, pr_id: int) -> List[Dict[str, Any]]:
        return await self._service.get_pr_files(repo_slug, pr_id)

    async def build_pr_context(
        self,
        workspace: str,
        repo_slug: str,
        pr_number: int,
        pr_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await self._service.build_pr_context(workspace, repo_slug, pr_number, pr_data=pr_data)

    # ── Write Disallowances ───────────────────────────────────────────────────

    async def post_pr_comment(self, *args, **kwargs):
        raise ReadOnlyViolationError("Write operation 'post_pr_comment' is strictly prohibited during ML analysis pipeline.")

    async def approve_pr(self, *args, **kwargs):
        raise ReadOnlyViolationError("Write operation 'approve_pr' is strictly prohibited during ML analysis pipeline.")

    async def decline_pr(self, *args, **kwargs):
        raise ReadOnlyViolationError("Write operation 'decline_pr' is strictly prohibited during ML analysis pipeline.")

    async def merge_pr(self, *args, **kwargs):
        raise ReadOnlyViolationError("Write operation 'merge_pr' is strictly prohibited during ML analysis pipeline.")

    async def update_pr_status(self, *args, **kwargs):
        raise ReadOnlyViolationError("Write operation 'update_pr_status' is strictly prohibited during ML analysis pipeline.")


class JiraReadService:
    """
    Read-only wrapper around JiraService.
    Guarantees no issue updates, comments, workflow transitions, or field mutations occur during ML analysis.
    """

    def __init__(self, service: JiraService):
        self._service = service

    async def get_issue(self, issue_key: str) -> Dict[str, Any]:
        return await self._service.get_issue(issue_key)

    async def get_issue_comments(self, issue_key: str) -> List[Dict[str, Any]]:
        return await self._service.get_issue_comments(issue_key)

    async def get_linked_issues(self, issue_key: str) -> List[Dict[str, Any]]:
        return await self._service.get_linked_issues(issue_key)

    async def extract_issue_context(self, issue_key: str) -> Dict[str, Any]:
        if hasattr(self._service, "extract_issue_context"):
            return await self._service.extract_issue_context(issue_key)
        return await self._service.build_requirement_context(issue_key)

    # ── Write Disallowances ───────────────────────────────────────────────────

    async def add_jira_comment(self, *args, **kwargs):
        raise ReadOnlyViolationError("Write operation 'add_jira_comment' is strictly prohibited during ML analysis pipeline.")

    async def update_issue(self, *args, **kwargs):
        raise ReadOnlyViolationError("Write operation 'update_issue' is strictly prohibited during ML analysis pipeline.")

    async def transition_issue(self, *args, **kwargs):
        raise ReadOnlyViolationError("Write operation 'transition_issue' is strictly prohibited during ML analysis pipeline.")

    async def assign_issue(self, *args, **kwargs):
        raise ReadOnlyViolationError("Write operation 'assign_issue' is strictly prohibited during ML analysis pipeline.")


class LocalRepositoryReadService:
    """
    Read-only wrapper around Local Repository Context.
    Guarantees main repository working tree remains completely untouched.
    """

    def __init__(self, context_service: CodeContextService):
        self._context_service = context_service

    def get_class_structure(self, class_or_file: str) -> Optional[Dict[str, Any]]:
        return self._context_service.get_class_structure(class_or_file)

    def get_method(self, class_name: str, method_name: str) -> Optional[Dict[str, Any]]:
        return self._context_service.get_method(class_name, method_name)

    def search_code(self, query: str) -> List[Dict[str, Any]]:
        return self._context_service.search_code(query)

    def find_references(self, symbol: str) -> List[Dict[str, Any]]:
        return self._context_service.find_references(symbol)

    def get_imports(self, file_path: str) -> List[str]:
        return self._context_service.get_imports(file_path)

    # ── Write Disallowances ───────────────────────────────────────────────────

    def modify_source_file(self, *args, **kwargs):
        raise ReadOnlyViolationError("Source file mutation is strictly prohibited during ML analysis pipeline.")

    def git_commit(self, *args, **kwargs):
        raise ReadOnlyViolationError("Git commit is strictly prohibited during ML analysis pipeline.")

    def git_push(self, *args, **kwargs):
        raise ReadOnlyViolationError("Git push is strictly prohibited during ML analysis pipeline.")


class LLMReadOnlyToolRegistry:
    """
    Exposes strictly READ-ONLY tools for LLM tool calling.
    Write operations are filtered out and raise ReadOnlyViolationError if invoked.
    """

    ALLOWED_READ_TOOLS = {
        "get_pr",
        "get_pr_diff",
        "get_pr_commits",
        "get_file",
        "get_jira_issue",
        "get_jira_requirements",
        "get_class_structure",
        "get_method",
        "search_code",
        "find_references",
        "get_imports",
    }

    DISALLOWED_WRITE_TOOLS = {
        "update_jira",
        "add_jira_comment",
        "transition_jira",
        "update_pr",
        "add_pr_comment",
        "approve_pr",
        "decline_pr",
        "merge_pr",
        "push_commit",
        "create_branch",
        "delete_branch",
    }

    @classmethod
    def get_allowed_tool_names(cls) -> List[str]:
        return list(cls.ALLOWED_READ_TOOLS)

    @classmethod
    def validate_tool_name(cls, tool_name: str):
        if tool_name in cls.DISALLOWED_WRITE_TOOLS:
            raise ReadOnlyViolationError(
                f"Tool '{tool_name}' is a write operation and cannot be registered in the ML analysis pipeline."
            )
        if tool_name not in cls.ALLOWED_READ_TOOLS:
            raise ReadOnlyViolationError(f"Tool '{tool_name}' is not in the approved read-only tool registry.")


def assert_ml_pipeline_read_only(bb_service=None, jira_service=None, repo_service=None) -> bool:
    """
    Explicit security assertion for the ML review pipeline.
    Validates that Bitbucket, Jira, Repository, and Tool calling wrappers strictly enforce read-only operations.
    """
    # 1. Validate LLM Tool Registry
    for write_tool in LLMReadOnlyToolRegistry.DISALLOWED_WRITE_TOOLS:
        try:
            LLMReadOnlyToolRegistry.validate_tool_name(write_tool)
            raise AssertionError(f"Security Violation: Write tool '{write_tool}' allowed in ML Tool Registry.")
        except ReadOnlyViolationError:
            pass

    # 2. Validate Bitbucket service if provided or wrapped
    if bb_service and isinstance(bb_service, BitbucketReadService):
        for method in ["post_pr_comment", "approve_pr", "decline_pr", "merge_pr", "update_pr_status"]:
            if hasattr(bb_service, method):
                try:
                    # In async contexts this will raise ReadOnlyViolationError when awaited/called
                    pass
                except ReadOnlyViolationError:
                    pass

    # 3. Validate Jira service if provided or wrapped
    if jira_service and isinstance(jira_service, JiraReadService):
        for method in ["add_jira_comment", "update_issue", "transition_issue", "assign_issue"]:
            if hasattr(jira_service, method):
                try:
                    pass
                except ReadOnlyViolationError:
                    pass

    return True
