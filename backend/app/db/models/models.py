"""
SQLAlchemy ORM Models — ReviewAI
All tables use UUID PKs, soft delete, and audit columns.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Enum, ForeignKey,
    Index, Integer, Numeric, String, Text, ARRAY,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

import enum


# ── Base ────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Mixins ──────────────────────────────────────────────────────────────────

class AuditMixin:
    """Adds created_at / updated_at / deleted_at + created_by / updated_by."""
    created_at: Mapped[datetime] = mapped_column(
        default=func.now(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


# ── Enums ────────────────────────────────────────────────────────────────────

class ReviewStatus(str, enum.Enum):
    pending   = "pending"
    running   = "running"
    completed = "completed"
    failed    = "failed"
    cancelled = "cancelled"


class ReviewRecommendation(str, enum.Enum):
    APPROVE           = "APPROVE"
    REQUEST_CHANGES   = "REQUEST_CHANGES"
    NEEDS_DISCUSSION  = "NEEDS_DISCUSSION"


class FindingSeverity(str, enum.Enum):
    critical = "critical"
    high     = "high"
    medium   = "medium"
    low      = "low"
    info     = "info"


class FindingCategory(str, enum.Enum):
    requirement     = "requirement"
    code_quality    = "code_quality"
    sql_performance = "sql_performance"
    security        = "security"
    refactoring     = "refactoring"
    test_coverage   = "test_coverage"
    general         = "general"


class ApprovalStatus(str, enum.Enum):
    pending  = "pending"
    approved = "approved"
    rejected = "rejected"


class AgentExecStatus(str, enum.Enum):
    pending   = "pending"
    running   = "running"
    completed = "completed"
    failed    = "failed"
    skipped   = "skipped"


class AuditAction(str, enum.Enum):
    review_start    = "review.start"
    review_complete = "review.complete"
    review_fail     = "review.fail"
    review_cancel   = "review.cancel"
    comment_approve = "comment.approve"
    comment_reject  = "comment.reject"
    comment_edit    = "comment.edit"
    comment_publish = "comment.publish"
    settings_update = "settings.update"
    user_login      = "user.login"
    user_create     = "user.create"


# ── Models ──────────────────────────────────────────────────────────────────

class User(UUIDMixin, AuditMixin, Base):
    __tablename__ = "users"

    email:        Mapped[str]            = mapped_column(String(255), nullable=False, unique=True)
    full_name:    Mapped[Optional[str]]  = mapped_column(String(255))
    avatar_url:   Mapped[Optional[str]]  = mapped_column(Text)
    is_active:    Mapped[bool]           = mapped_column(Boolean, nullable=False, default=True)
    is_superuser: Mapped[bool]           = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_by:   Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_by:   Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    # Relationships
    projects:  Mapped[List["Project"]]  = relationship("Project", foreign_keys="Project.owner_id", back_populates="owner")
    reviews:   Mapped[List["Review"]]   = relationship("Review",  foreign_keys="Review.user_id",   back_populates="user")
    settings:  Mapped[List["SystemSettings"]] = relationship("SystemSettings", foreign_keys="SystemSettings.user_id")

    __table_args__ = (
        Index("idx_users_email",     "email",     postgresql_where=Column("deleted_at").is_(None)),
        Index("idx_users_is_active", "is_active", postgresql_where=Column("deleted_at").is_(None)),
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class Project(UUIDMixin, AuditMixin, Base):
    __tablename__ = "projects"

    name:                Mapped[str]           = mapped_column(String(255), nullable=False)
    description:         Mapped[Optional[str]] = mapped_column(Text)
    owner_id:            Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    jira_project_key:    Mapped[Optional[str]] = mapped_column(String(50))
    bitbucket_workspace: Mapped[Optional[str]] = mapped_column(String(100))
    is_active:           Mapped[bool]          = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[Optional[uuid.UUID]]    = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_by: Mapped[Optional[uuid.UUID]]    = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    owner:        Mapped["User"]              = relationship("User", foreign_keys=[owner_id], back_populates="projects")
    repositories: Mapped[List["Repository"]] = relationship("Repository", back_populates="project")

    __table_args__ = (
        Index("idx_projects_owner",    "owner_id",         postgresql_where=Column("deleted_at").is_(None)),
        Index("idx_projects_jira_key", "jira_project_key", postgresql_where=Column("deleted_at").is_(None)),
    )


class Repository(UUIDMixin, AuditMixin, Base):
    __tablename__ = "repositories"

    project_id:     Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    name:           Mapped[str]           = mapped_column(String(255), nullable=False)
    slug:           Mapped[str]           = mapped_column(String(255), nullable=False)
    workspace:      Mapped[str]           = mapped_column(String(100), nullable=False)
    full_name:      Mapped[str]           = mapped_column(String(500), nullable=False)
    clone_url:      Mapped[Optional[str]] = mapped_column(Text)
    default_branch: Mapped[str]           = mapped_column(String(100), default="main")
    language:       Mapped[Optional[str]] = mapped_column(String(50))
    is_active:      Mapped[bool]          = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    project: Mapped["Project"]      = relationship("Project", back_populates="repositories")
    reviews: Mapped[List["Review"]] = relationship("Review",  back_populates="repository")

    __table_args__ = (
        Index("idx_repos_project",   "project_id", postgresql_where=Column("deleted_at").is_(None)),
        Index("idx_repos_full_name", "full_name",  postgresql_where=Column("deleted_at").is_(None)),
        {"schema": None},
    )


class Review(UUIDMixin, AuditMixin, Base):
    __tablename__ = "reviews"

    repository_id:   Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id"))
    user_id:         Mapped[uuid.UUID]            = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    # PR
    pr_number:       Mapped[int]           = mapped_column(Integer, nullable=False)
    pr_title:        Mapped[Optional[str]] = mapped_column(Text)
    pr_url:          Mapped[Optional[str]] = mapped_column(Text)
    pr_description:  Mapped[Optional[str]] = mapped_column(Text)
    source_branch:   Mapped[Optional[str]] = mapped_column(String(255))
    target_branch:   Mapped[Optional[str]] = mapped_column(String(255))
    pr_author:       Mapped[Optional[str]] = mapped_column(String(255))
    pr_author_email: Mapped[Optional[str]] = mapped_column(String(255))
    base_commit_hash: Mapped[Optional[str]] = mapped_column(String(40))
    head_commit_hash: Mapped[Optional[str]] = mapped_column(String(40))
    files_changed:   Mapped[Optional[int]] = mapped_column(Integer)
    lines_added:     Mapped[Optional[int]] = mapped_column(Integer)
    lines_removed:   Mapped[Optional[int]] = mapped_column(Integer)
    # Jira
    jira_key:        Mapped[Optional[str]] = mapped_column(String(50))
    # Status
    status:          Mapped[ReviewStatus]  = mapped_column(
        Enum(ReviewStatus, name="review_status"), nullable=False, default=ReviewStatus.pending
    )
    current_agent:    Mapped[Optional[str]] = mapped_column(String(100))
    progress_percent: Mapped[int]           = mapped_column(Integer, nullable=False, default=0)
    error_message:    Mapped[Optional[str]] = mapped_column(Text)
    # Results
    risk_score:              Mapped[Optional[float]]               = mapped_column(Numeric(5, 2))
    overall_recommendation:  Mapped[Optional[ReviewRecommendation]] = mapped_column(
        Enum(ReviewRecommendation, name="review_recommendation")
    )
    executive_summary: Mapped[Optional[str]] = mapped_column(Text)
    total_findings:    Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    critical_count:    Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    high_count:        Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    medium_count:      Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_count:         Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Timing
    started_at:       Mapped[Optional[datetime]] = mapped_column()
    completed_at:     Mapped[Optional[datetime]] = mapped_column()
    duration_seconds: Mapped[Optional[int]]      = mapped_column(Integer)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    repository:       Mapped[Optional["Repository"]]    = relationship("Repository",    back_populates="reviews")
    user:             Mapped["User"]                    = relationship("User",           foreign_keys=[user_id])
    files:            Mapped[List["ReviewFile"]]        = relationship("ReviewFile",     back_populates="review",    cascade="all, delete-orphan")
    findings:         Mapped[List["ReviewFinding"]]     = relationship("ReviewFinding",  back_populates="review",    cascade="all, delete-orphan")
    jira_requirements: Mapped[List["JiraRequirement"]] = relationship("JiraRequirement", back_populates="review",   cascade="all, delete-orphan")
    agent_executions: Mapped[List["AgentExecution"]]   = relationship("AgentExecution", back_populates="review",    cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("progress_percent BETWEEN 0 AND 100", name="chk_progress_range"),
        CheckConstraint("risk_score BETWEEN 0 AND 100",       name="chk_risk_range"),
        Index("idx_reviews_user",       "user_id",       postgresql_where=Column("deleted_at").is_(None)),
        Index("idx_reviews_repo",       "repository_id", postgresql_where=Column("deleted_at").is_(None)),
        Index("idx_reviews_status",     "status",        postgresql_where=Column("deleted_at").is_(None)),
        Index("idx_reviews_jira_key",   "jira_key",      postgresql_where=Column("deleted_at").is_(None)),
        Index("idx_reviews_created_at", "created_at",    postgresql_where=Column("deleted_at").is_(None)),
    )


class ReviewFile(UUIDMixin, Base):
    __tablename__ = "review_files"

    review_id:    Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    file_path:    Mapped[str]           = mapped_column(Text, nullable=False)
    file_type:    Mapped[Optional[str]] = mapped_column(String(50))
    change_type:  Mapped[Optional[str]] = mapped_column(String(20))
    lines_added:  Mapped[int]           = mapped_column(Integer, default=0)
    lines_removed: Mapped[int]          = mapped_column(Integer, default=0)
    diff_content: Mapped[Optional[str]] = mapped_column(Text)
    created_at:   Mapped[datetime]      = mapped_column(default=func.now(), server_default=func.now())
    updated_at:   Mapped[datetime]      = mapped_column(default=func.now(), server_default=func.now(), onupdate=func.now())

    review:   Mapped["Review"]               = relationship("Review", back_populates="files")
    findings: Mapped[List["ReviewFinding"]]  = relationship("ReviewFinding", back_populates="review_file")

    __table_args__ = (
        Index("idx_review_files_review", "review_id"),
        Index("idx_review_files_path",   "review_id", "file_path"),
    )


class ReviewFinding(UUIDMixin, AuditMixin, Base):
    __tablename__ = "review_findings"

    review_id:      Mapped[uuid.UUID]            = mapped_column(UUID(as_uuid=True), ForeignKey("reviews.id",      ondelete="CASCADE"), nullable=False)
    review_file_id: Mapped[Optional[uuid.UUID]]  = mapped_column(UUID(as_uuid=True), ForeignKey("review_files.id"))
    agent_name:     Mapped[str]                  = mapped_column(String(100), nullable=False)
    severity:       Mapped[FindingSeverity]       = mapped_column(Enum(FindingSeverity,  name="finding_severity"), nullable=False)
    category:       Mapped[FindingCategory]       = mapped_column(Enum(FindingCategory,  name="finding_category"), nullable=False)
    file_path:      Mapped[Optional[str]]         = mapped_column(Text)
    line_number:    Mapped[Optional[int]]         = mapped_column(Integer)
    line_number_end: Mapped[Optional[int]]        = mapped_column(Integer)
    title:          Mapped[str]                   = mapped_column(String(500), nullable=False)
    description:    Mapped[str]                   = mapped_column(Text, nullable=False)
    evidence:       Mapped[Optional[str]]         = mapped_column(Text)
    recommendation: Mapped[str]                   = mapped_column(Text, nullable=False)
    review_comment: Mapped[str]                   = mapped_column(Text, nullable=False)
    pr_comment:     Mapped[Optional[str]]         = mapped_column(Text)
    edited_comment: Mapped[Optional[str]]         = mapped_column(Text)
    approval_status: Mapped[ApprovalStatus]       = mapped_column(Enum(ApprovalStatus, name="approval_status"), nullable=False, default=ApprovalStatus.pending)
    approved_by:    Mapped[Optional[str]]         = mapped_column(String(255))
    approved_at:    Mapped[Optional[datetime]]    = mapped_column()
    rejection_reason: Mapped[Optional[str]]       = mapped_column(Text)
    published:      Mapped[bool]                  = mapped_column(Boolean, nullable=False, default=False)
    published_at:   Mapped[Optional[datetime]]    = mapped_column()
    bitbucket_comment_id: Mapped[Optional[str]]  = mapped_column(String(100))
    confidence_score: Mapped[Optional[float]]     = mapped_column(Numeric(3, 2))
    tags:           Mapped[Optional[list]]        = mapped_column(ARRAY(Text))
    origin:         Mapped[Optional[str]]         = mapped_column(String(50))
    change_scope:   Mapped[Optional[str]]         = mapped_column(String(20))
    classification: Mapped[Optional[str]]         = mapped_column(String(30))
    affected_by_pr: Mapped[Optional[bool]]        = mapped_column(Boolean)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    review:      Mapped["Review"]                  = relationship("Review",     back_populates="findings")
    review_file: Mapped[Optional["ReviewFile"]]    = relationship("ReviewFile", back_populates="findings")
    comments:    Mapped[List["ReviewComment"]]     = relationship("ReviewComment", back_populates="finding", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_findings_review",    "review_id",       postgresql_where=Column("deleted_at").is_(None)),
        Index("idx_findings_severity",  "review_id", "severity",  postgresql_where=Column("deleted_at").is_(None)),
        Index("idx_findings_category",  "review_id", "category",  postgresql_where=Column("deleted_at").is_(None)),
        Index("idx_findings_approval",  "approval_status", postgresql_where=Column("deleted_at").is_(None)),
        Index("idx_findings_published", "published",       postgresql_where=Column("deleted_at").is_(None)),
    )


class ReviewComment(UUIDMixin, Base):
    __tablename__ = "review_comments"

    finding_id:  Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("review_findings.id", ondelete="CASCADE"), nullable=False)
    review_id:   Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("reviews.id",         ondelete="CASCADE"), nullable=False)
    author:      Mapped[str]                = mapped_column(String(255), nullable=False)
    comment_text: Mapped[str]               = mapped_column(Text, nullable=False)
    parent_id:   Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("review_comments.id"))
    bitbucket_comment_id: Mapped[Optional[str]] = mapped_column(String(100))
    is_resolved: Mapped[bool]               = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column()
    resolved_by: Mapped[Optional[str]]      = mapped_column(String(255))
    deleted_at:  Mapped[Optional[datetime]] = mapped_column()
    created_at:  Mapped[datetime]           = mapped_column(default=func.now(), server_default=func.now())
    updated_at:  Mapped[datetime]           = mapped_column(default=func.now(), server_default=func.now(), onupdate=func.now())

    finding:  Mapped["ReviewFinding"]           = relationship("ReviewFinding", back_populates="comments")
    replies:  Mapped[List["ReviewComment"]]     = relationship("ReviewComment", back_populates="parent")
    parent:   Mapped[Optional["ReviewComment"]] = relationship("ReviewComment", back_populates="replies", remote_side="ReviewComment.id")

    __table_args__ = (
        Index("idx_comments_finding", "finding_id", postgresql_where=Column("deleted_at").is_(None)),
        Index("idx_comments_review",  "review_id",  postgresql_where=Column("deleted_at").is_(None)),
    )


class JiraRequirement(UUIDMixin, Base):
    __tablename__ = "jira_requirements"

    review_id:           Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    jira_key:            Mapped[str]           = mapped_column(String(50), nullable=False)
    issue_type:          Mapped[Optional[str]] = mapped_column(String(50))
    summary:             Mapped[Optional[str]] = mapped_column(Text)
    description:         Mapped[Optional[str]] = mapped_column(Text)
    acceptance_criteria: Mapped[Optional[list]] = mapped_column(ARRAY(Text))
    technical_notes:     Mapped[Optional[str]] = mapped_column(Text)
    priority:            Mapped[Optional[str]] = mapped_column(String(20))
    status:              Mapped[Optional[str]] = mapped_column(String(50))
    assignee:            Mapped[Optional[str]] = mapped_column(String(255))
    labels:              Mapped[Optional[list]] = mapped_column(ARRAY(Text))
    story_points:        Mapped[Optional[float]] = mapped_column(Numeric(5, 1))
    raw_json:            Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at:  Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
    updated_at:  Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now(), onupdate=func.now())

    review: Mapped["Review"] = relationship("Review", back_populates="jira_requirements")

    __table_args__ = (
        Index("idx_jira_req_review", "review_id"),
        Index("idx_jira_req_key",    "jira_key"),
    )


class AgentExecution(UUIDMixin, Base):
    __tablename__ = "agent_executions"

    review_id:        Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    agent_name:       Mapped[str]              = mapped_column(String(100), nullable=False)
    status:           Mapped[AgentExecStatus]  = mapped_column(Enum(AgentExecStatus, name="agent_exec_status"), nullable=False, default=AgentExecStatus.pending)
    sequence_number:  Mapped[int]              = mapped_column(Integer, nullable=False)
    started_at:       Mapped[Optional[datetime]] = mapped_column()
    completed_at:     Mapped[Optional[datetime]] = mapped_column()
    duration_ms:      Mapped[Optional[int]]    = mapped_column(Integer)
    llm_provider:     Mapped[Optional[str]]    = mapped_column(String(50))
    llm_model:        Mapped[Optional[str]]    = mapped_column(String(100))
    prompt_tokens:    Mapped[Optional[int]]    = mapped_column(Integer)
    completion_tokens: Mapped[Optional[int]]   = mapped_column(Integer)
    total_tokens:     Mapped[Optional[int]]    = mapped_column(Integer)
    estimated_cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 6))
    findings_count:   Mapped[int]              = mapped_column(Integer, nullable=False, default=0)
    error_message:    Mapped[Optional[str]]    = mapped_column(Text)
    logs:             Mapped[Optional[dict]]   = mapped_column(JSONB)
    output_json:      Mapped[Optional[dict]]   = mapped_column(JSONB)
    created_at:       Mapped[datetime]         = mapped_column(default=func.now(), server_default=func.now())
    updated_at:       Mapped[datetime]         = mapped_column(default=func.now(), server_default=func.now(), onupdate=func.now())

    review: Mapped["Review"] = relationship("Review", back_populates="agent_executions")

    __table_args__ = (
        Index("idx_agent_exec_review", "review_id"),
        Index("idx_agent_exec_status", "status"),
    )


class SystemSettings(UUIDMixin, Base):
    __tablename__ = "system_settings"

    user_id:    Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    # Bitbucket
    bitbucket_workspace:    Mapped[Optional[str]] = mapped_column(String(100))
    bitbucket_access_token: Mapped[Optional[str]] = mapped_column(Text)   # encrypted
    # Jira
    jira_base_url:  Mapped[Optional[str]] = mapped_column(Text)
    jira_email:     Mapped[Optional[str]] = mapped_column(String(255))
    jira_api_token: Mapped[Optional[str]] = mapped_column(Text)            # encrypted
    # AI
    ai_provider:       Mapped[str]           = mapped_column(String(20), nullable=False, default="gemini")
    anthropic_api_key: Mapped[Optional[str]] = mapped_column(Text)         # encrypted
    openai_api_key:    Mapped[Optional[str]] = mapped_column(Text)         # encrypted
    # Tuning
    max_findings_per_agent: Mapped[int] = mapped_column(Integer, default=10)
    agent_timeout_seconds:  Mapped[int] = mapped_column(Integer, default=120)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now(), onupdate=func.now())
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    user:    Mapped[Optional["User"]]    = relationship("User",    foreign_keys=[user_id], overlaps="settings")
    project: Mapped[Optional["Project"]] = relationship("Project", foreign_keys=[project_id])

    __table_args__ = (
        Index("idx_settings_user",    "user_id"),
        Index("idx_settings_project", "project_id"),
    )


class AuditLog(UUIDMixin, Base):
    __tablename__ = "audit_logs"

    action:        Mapped[AuditAction]      = mapped_column(Enum(AuditAction, name="audit_action"), nullable=False)
    actor_id:      Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    actor_email:   Mapped[Optional[str]]    = mapped_column(String(255))
    resource_type: Mapped[str]              = mapped_column(String(50), nullable=False)
    resource_id:   Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    old_value:     Mapped[Optional[dict]]   = mapped_column(JSONB)
    new_value:     Mapped[Optional[dict]]   = mapped_column(JSONB)
    ip_address:    Mapped[Optional[str]]    = mapped_column(INET)
    user_agent:    Mapped[Optional[str]]    = mapped_column(Text)
    request_id:    Mapped[Optional[str]]    = mapped_column(String(100))
    metadata_:     Mapped[Optional[dict]]   = mapped_column("metadata", JSONB)
    created_at:    Mapped[datetime]         = mapped_column(default=func.now(), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_audit_actor",    "actor_id",    "created_at"),
        Index("idx_audit_resource", "resource_type", "resource_id", "created_at"),
        Index("idx_audit_action",   "action",      "created_at"),
        Index("idx_audit_created",  "created_at"),
    )
