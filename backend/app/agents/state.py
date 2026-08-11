"""
Shared state object passed through the entire LangGraph pipeline.
Every node receives this and returns a partial update dict.
"""
from __future__ import annotations

from typing import Any, Callable, Coroutine, Optional, TypedDict


class LogEntry(TypedDict):
    timestamp: str
    agent: str
    message: str
    level: str  # info | warning | error


class FindingDict(TypedDict, total=False):
    review_id: str
    agent_name: str
    severity: str        # critical | high | medium | low | info
    category: str        # requirement | code_quality | sql_performance | security | refactoring | test_coverage
    file_path: Optional[str]
    line_number: Optional[int]
    line_number_end: Optional[int]
    title: str
    description: str
    evidence: Optional[str]
    recommendation: str
    review_comment: str
    confidence_score: Optional[float]
    tags: Optional[list[str]]


class PRContext(TypedDict, total=False):
    pr_number: int
    pr_title: str
    pr_url: str
    source_branch: str
    target_branch: str
    author: str
    description: str
    diff: str                   # full unified diff
    files_changed: list[dict]   # [{path, change_type, diff}]
    jira_key: Optional[str]


class JiraContext(TypedDict, total=False):
    jira_key: str
    issue_type: str
    summary: str
    description: str
    acceptance_criteria: list[str]
    technical_notes: str
    priority: str
    status: str
    labels: list[str]
    story_points: Optional[float]


class ReviewSummary(TypedDict, total=False):
    risk_score: float           # 0-100
    overall_recommendation: str # APPROVE | REQUEST_CHANGES | NEEDS_DISCUSSION
    executive_summary: str
    total_findings: int
    findings_by_severity: dict[str, int]
    findings_by_category: dict[str, int]


class CodeContextState(TypedDict, total=False):
    repo_path: str
    worktree_path: str
    source_commit: str
    target_commit: str
    has_local_context: bool
    indexed_classes_count: int
    changed_methods_count: int
    error: Optional[str]


class ReviewState(TypedDict, total=False):
    # Identifiers
    review_id: str
    workspace: str
    repo_slug: str

    # Credentials (runtime only — never persisted here)
    bitbucket_token: str
    jira_base_url: str
    jira_email: str
    jira_token: str
    ai_provider: str
    ai_key: str

    # Data fetched by fetch nodes
    pr_context: PRContext
    jira_context: JiraContext
    code_context: CodeContextState

    # Agent outputs — accumulated across all nodes
    requirements: list[dict]            # flat requirement list (used by validation agent)
    extracted_requirements: dict        # full structured ExtractedRequirements output
    findings: list[FindingDict]         # accumulated findings from all agents
    summary: ReviewSummary

    # Execution metadata
    logs: list[LogEntry]
    current_agent: str
    progress_percent: int
    error: Optional[str]
    agent_errors: dict[str, str]  # agent_name → error message

    # Callback — injected by ReviewService, not serialised
    progress_callback: Optional[Callable]
