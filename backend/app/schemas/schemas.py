"""
Pydantic v2 API schemas — request/response contracts.
All schemas use model_config with from_attributes=True for ORM compatibility.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.db.models.models import (
    AgentExecStatus,
    ApprovalStatus,
    FindingCategory,
    FindingSeverity,
    ReviewRecommendation,
    ReviewStatus,
)


# ── Shared ──────────────────────────────────────────────────────────────────

class OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Review ──────────────────────────────────────────────────────────────────

class StartReviewRequest(BaseModel):
    pr_url:                Optional[str]  = Field(None, description="Full Bitbucket PR URL")
    bitbucket_workspace:   Optional[str]  = None
    bitbucket_repo_slug:   Optional[str]  = None
    pr_number:             Optional[int]  = Field(None, gt=0)
    jira_key_override:     Optional[str]  = None

    @field_validator("pr_number")
    @classmethod
    def validate_input(cls, v, info):
        data = info.data
        if not data.get("pr_url") and not (
            data.get("bitbucket_workspace")
            and data.get("bitbucket_repo_slug")
            and v
        ):
            raise ValueError(
                "Provide either pr_url or (bitbucket_workspace + bitbucket_repo_slug + pr_number)"
            )
        return v


class ReviewResponse(OrmBase):
    id:                    uuid.UUID
    pr_number:             int
    pr_title:              Optional[str] = None
    pr_url:                Optional[str] = None
    pr_author:             Optional[str] = None
    pr_author_email:       Optional[str] = None
    source_branch:         Optional[str] = None
    target_branch:         Optional[str] = None
    jira_key:              Optional[str] = None
    jira_url:              Optional[str] = None
    status:                ReviewStatus
    current_agent:         Optional[str] = None
    progress_percent:      int
    error_message:         Optional[str] = None
    risk_score:            Optional[float] = None
    overall_recommendation: Optional[ReviewRecommendation] = None
    executive_summary:     Optional[str] = None
    total_findings:        int = 0
    critical_count:        int = 0
    high_count:            int = 0
    medium_count:          int = 0
    low_count:             int = 0
    started_at:            Optional[datetime] = None
    completed_at:          Optional[datetime] = None
    duration_seconds:      Optional[int] = None
    created_at:            datetime
    updated_at:            datetime

    @model_validator(mode="after")
    def compute_jira_url(self) -> ReviewResponse:
        if self.jira_key and not self.jira_url:
            from app.core.config import settings
            base_url = getattr(settings, "JIRA_BASE_URL", "") or "https://freshconcepts.atlassian.net"
            if base_url:
                self.jira_url = f"{base_url.rstrip('/')}/browse/{self.jira_key}"
        return self


class ReviewListResponse(BaseModel):
    items:     list[ReviewResponse]
    total:     int
    page:      int
    page_size: int


# ── Pending PRs ───────────────────────────────────────────────────────────────

class PendingPrItem(BaseModel):
    pr_number:              int
    pr_title:               str
    pr_url:                 str
    pr_author:              Optional[str] = None
    pr_author_email:        Optional[str] = None
    source_branch:          Optional[str] = None
    target_branch:          Optional[str] = None
    jira_key:               Optional[str] = None
    jira_url:               Optional[str] = None
    jira_status:            Optional[str] = None
    workspace:              str
    repo_slug:              str
    created_on:             Optional[str] = None
    updated_on:             Optional[str] = None
    existing_review_id:     Optional[str] = None
    existing_review_status: Optional[str] = None
    approvers:              list[str] = []
    changes_requested_by:   list[str] = []
    comment_count:          int = 0
    current_user_approved:  bool = False


class PendingPrsResponse(BaseModel):
    items: list[PendingPrItem]
    total: int



# ── Findings ─────────────────────────────────────────────────────────────────

class FindingResponse(OrmBase):
    id:                   uuid.UUID
    review_id:            uuid.UUID
    agent_name:           str
    severity:             FindingSeverity
    category:             FindingCategory
    file_path:            Optional[str]
    line_number:          Optional[int]
    line_number_end:      Optional[int]
    title:                str
    description:          str
    evidence:             Optional[str]
    recommendation:       str
    review_comment:       str
    pr_comment:           Optional[str] = None
    edited_comment:       Optional[str]
    approval_status:      ApprovalStatus
    approved_by:          Optional[str]
    approved_at:          Optional[datetime]
    rejection_reason:     Optional[str]
    published:            bool
    published_at:         Optional[datetime]
    bitbucket_comment_id: Optional[str]
    confidence_score:     Optional[float]
    tags:                 Optional[list[str]]
    origin:               Optional[str] = "introduced_by_pr"
    change_scope:         Optional[str] = "changed"
    classification:       Optional[str] = "finding"
    affected_by_pr:       Optional[bool] = True
    created_at:           datetime


class FindingListResponse(BaseModel):
    items:     list[FindingResponse]
    total:     int
    page:      int
    page_size: int


# ── Comments ─────────────────────────────────────────────────────────────────

class ApproveCommentsRequest(BaseModel):
    finding_ids:  list[uuid.UUID] = Field(..., min_length=1)
    approved_by:  str             = Field(..., min_length=1, max_length=255)


class RejectCommentsRequest(BaseModel):
    finding_ids:      list[uuid.UUID] = Field(..., min_length=1)
    rejection_reason: Optional[str]   = None


class UpdateCommentRequest(BaseModel):
    edited_comment: str = Field(..., min_length=1)


class PublishRequest(BaseModel):
    finding_ids: list[uuid.UUID] = Field(..., min_length=1)


class PublishResponse(BaseModel):
    published_count: int
    failed_count:    int
    message:         str
    errors:          list[str] = []


class BulkActionResponse(BaseModel):
    affected: int
    message:  str


# ── Agent Execution ──────────────────────────────────────────────────────────

class AgentExecutionResponse(OrmBase):
    id:                  uuid.UUID
    agent_name:          str
    status:              AgentExecStatus
    sequence_number:     int
    started_at:          Optional[datetime]
    completed_at:        Optional[datetime]
    duration_ms:         Optional[int]
    llm_model:           Optional[str]
    total_tokens:        Optional[int]
    estimated_cost_usd:  Optional[float]
    findings_count:      int
    error_message:       Optional[str]


# ── Summary ──────────────────────────────────────────────────────────────────

class ReviewSummaryResponse(BaseModel):
    review_id:             uuid.UUID
    risk_score:            Optional[float]
    overall_recommendation: Optional[ReviewRecommendation]
    executive_summary:     Optional[str]
    total_findings:        int
    findings_by_severity:  dict[str, int]
    findings_by_category:  dict[str, int]
    agent_executions:      list[AgentExecutionResponse]


# ── Settings ─────────────────────────────────────────────────────────────────

class SettingsUpdateRequest(BaseModel):
    bitbucket_workspace:    Optional[str] = None
    bitbucket_access_token: Optional[str] = None
    jira_base_url:          Optional[str] = None
    jira_email:             Optional[str] = None
    jira_api_token:         Optional[str] = None
    ai_provider:            Optional[str] = Field(None, pattern="^(anthropic|openai|gemini|google)$")
    anthropic_api_key:      Optional[str] = None
    openai_api_key:         Optional[str] = None
    gemini_api_key:         Optional[str] = None
    max_findings_per_agent: Optional[int] = Field(None, ge=1, le=50)
    agent_timeout_seconds:  Optional[int] = Field(None, ge=30, le=600)


class SettingsResponse(BaseModel):
    bitbucket_workspace:    Optional[str]
    jira_base_url:          Optional[str]
    jira_email:             Optional[str]
    ai_provider:            str
    max_findings_per_agent: int
    agent_timeout_seconds:  int
    # Masked booleans — never expose raw keys
    has_bitbucket_token:    bool
    has_jira_token:         bool
    has_anthropic_key:      bool
    has_openai_key:         bool
    has_gemini_key:         bool


# ── Error ────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    code:    str
    message: str
    detail:  Optional[Any] = None
