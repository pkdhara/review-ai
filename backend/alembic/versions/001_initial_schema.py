"""Initial schema — all tables

Revision ID: 001
Revises:
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extensions ──────────────────────────────────────────────────────────
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # ── ENUMs ───────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TYPE review_status AS ENUM
        ('pending','running','completed','failed','cancelled')
    """)
    op.execute("""
        CREATE TYPE review_recommendation AS ENUM
        ('APPROVE','REQUEST_CHANGES','NEEDS_DISCUSSION')
    """)
    op.execute("""
        CREATE TYPE finding_severity AS ENUM
        ('critical','high','medium','low','info')
    """)
    op.execute("""
        CREATE TYPE finding_category AS ENUM
        ('requirement','code_quality','sql_performance',
         'security','refactoring','test_coverage','general')
    """)
    op.execute("""
        CREATE TYPE approval_status AS ENUM
        ('pending','approved','rejected')
    """)
    op.execute("""
        CREATE TYPE agent_exec_status AS ENUM
        ('pending','running','completed','failed','skipped')
    """)
    op.execute("""
        CREATE TYPE audit_action AS ENUM
        ('review.start','review.complete','review.fail','review.cancel',
         'comment.approve','comment.reject','comment.edit','comment.publish',
         'settings.update','user.login','user.create')
    """)

    # ── updated_at trigger function ─────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    # ── users ───────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id",            postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("email",         sa.String(255), nullable=False),
        sa.Column("full_name",     sa.String(255)),
        sa.Column("avatar_url",    sa.Text),
        sa.Column("is_active",     sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_superuser",  sa.Boolean, nullable=False, server_default="false"),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at",    sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at",    sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at",    sa.TIMESTAMP(timezone=True)),
        sa.Column("created_by",    postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("updated_by",    postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("idx_users_email",     "users", ["email"],     postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_users_is_active", "users", ["is_active"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.execute("CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_updated_at()")

    # ── projects ─────────────────────────────────────────────────────────────
    op.create_table(
        "projects",
        sa.Column("id",                   postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name",                 sa.String(255), nullable=False),
        sa.Column("description",          sa.Text),
        sa.Column("owner_id",             postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("jira_project_key",     sa.String(50)),
        sa.Column("bitbucket_workspace",  sa.String(100)),
        sa.Column("is_active",            sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at",           sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at",           sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at",           sa.TIMESTAMP(timezone=True)),
        sa.Column("created_by",           postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("updated_by",           postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
    )
    op.create_index("idx_projects_owner",    "projects", ["owner_id"],        postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_projects_jira_key", "projects", ["jira_project_key"],postgresql_where=sa.text("deleted_at IS NULL"))
    op.execute("CREATE TRIGGER trg_projects_updated_at BEFORE UPDATE ON projects FOR EACH ROW EXECUTE FUNCTION update_updated_at()")

    # ── repositories ─────────────────────────────────────────────────────────
    op.create_table(
        "repositories",
        sa.Column("id",             postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("project_id",     postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name",           sa.String(255), nullable=False),
        sa.Column("slug",           sa.String(255), nullable=False),
        sa.Column("workspace",      sa.String(100), nullable=False),
        sa.Column("full_name",      sa.String(500), nullable=False),
        sa.Column("clone_url",      sa.Text),
        sa.Column("default_branch", sa.String(100), server_default="main"),
        sa.Column("language",       sa.String(50)),
        sa.Column("is_active",      sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at",     sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at",     sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at",     sa.TIMESTAMP(timezone=True)),
        sa.Column("created_by",     postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("updated_by",     postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("workspace", "slug", name="uq_repos_workspace_slug"),
    )
    op.create_index("idx_repos_project",   "repositories", ["project_id"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_repos_full_name", "repositories", ["full_name"],  postgresql_where=sa.text("deleted_at IS NULL"))
    op.execute("CREATE TRIGGER trg_repositories_updated_at BEFORE UPDATE ON repositories FOR EACH ROW EXECUTE FUNCTION update_updated_at()")

    # ── reviews ──────────────────────────────────────────────────────────────
    op.create_table(
        "reviews",
        sa.Column("id",                     postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("repository_id",          postgresql.UUID(as_uuid=True), sa.ForeignKey("repositories.id")),
        sa.Column("user_id",                postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("pr_number",              sa.Integer, nullable=False),
        sa.Column("pr_title",               sa.Text),
        sa.Column("pr_url",                 sa.Text),
        sa.Column("pr_description",         sa.Text),
        sa.Column("source_branch",          sa.String(255)),
        sa.Column("target_branch",          sa.String(255)),
        sa.Column("pr_author",              sa.String(255)),
        sa.Column("pr_author_email",        sa.String(255)),
        sa.Column("base_commit_hash",       sa.String(40)),
        sa.Column("head_commit_hash",       sa.String(40)),
        sa.Column("files_changed",          sa.Integer),
        sa.Column("lines_added",            sa.Integer),
        sa.Column("lines_removed",          sa.Integer),
        sa.Column("jira_key",               sa.String(50)),
        sa.Column("status",                 postgresql.ENUM("pending","running","completed","failed","cancelled", name="review_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("current_agent",          sa.String(100)),
        sa.Column("progress_percent",       sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message",          sa.Text),
        sa.Column("risk_score",             sa.Numeric(5, 2)),
        sa.Column("overall_recommendation", postgresql.ENUM("APPROVE","REQUEST_CHANGES","NEEDS_DISCUSSION", name="review_recommendation", create_type=False)),
        sa.Column("executive_summary",      sa.Text),
        sa.Column("total_findings",         sa.Integer, nullable=False, server_default="0"),
        sa.Column("critical_count",         sa.Integer, nullable=False, server_default="0"),
        sa.Column("high_count",             sa.Integer, nullable=False, server_default="0"),
        sa.Column("medium_count",           sa.Integer, nullable=False, server_default="0"),
        sa.Column("low_count",              sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at",             sa.TIMESTAMP(timezone=True)),
        sa.Column("completed_at",           sa.TIMESTAMP(timezone=True)),
        sa.Column("duration_seconds",       sa.Integer),
        sa.Column("created_at",             sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at",             sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at",             sa.TIMESTAMP(timezone=True)),
        sa.Column("created_by",             postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("updated_by",             postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.CheckConstraint("progress_percent BETWEEN 0 AND 100", name="chk_progress_range"),
        sa.CheckConstraint("risk_score BETWEEN 0 AND 100",       name="chk_risk_range"),
    )
    op.create_index("idx_reviews_user",       "reviews", ["user_id"],       postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_reviews_repo",       "reviews", ["repository_id"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_reviews_status",     "reviews", ["status"],        postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_reviews_jira_key",   "reviews", ["jira_key"],      postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_reviews_created_at", "reviews", ["created_at"],    postgresql_where=sa.text("deleted_at IS NULL"))
    op.execute("CREATE TRIGGER trg_reviews_updated_at BEFORE UPDATE ON reviews FOR EACH ROW EXECUTE FUNCTION update_updated_at()")

    # ── review_files ─────────────────────────────────────────────────────────
    op.create_table(
        "review_files",
        sa.Column("id",            postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("review_id",     postgresql.UUID(as_uuid=True), sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path",     sa.Text, nullable=False),
        sa.Column("file_type",     sa.String(50)),
        sa.Column("change_type",   sa.String(20)),
        sa.Column("lines_added",   sa.Integer, server_default="0"),
        sa.Column("lines_removed", sa.Integer, server_default="0"),
        sa.Column("diff_content",  sa.Text),
        sa.Column("created_at",    sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at",    sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_review_files_review", "review_files", ["review_id"])
    op.create_index("idx_review_files_path",   "review_files", ["review_id", "file_path"])
    op.execute("CREATE TRIGGER trg_review_files_updated_at BEFORE UPDATE ON review_files FOR EACH ROW EXECUTE FUNCTION update_updated_at()")

    # ── review_findings ──────────────────────────────────────────────────────
    op.create_table(
        "review_findings",
        sa.Column("id",                   postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("review_id",            postgresql.UUID(as_uuid=True), sa.ForeignKey("reviews.id",      ondelete="CASCADE"), nullable=False),
        sa.Column("review_file_id",       postgresql.UUID(as_uuid=True), sa.ForeignKey("review_files.id")),
        sa.Column("agent_name",           sa.String(100), nullable=False),
        sa.Column("severity",             postgresql.ENUM("critical","high","medium","low","info", name="finding_severity", create_type=False), nullable=False),
        sa.Column("category",             postgresql.ENUM("requirement","code_quality","sql_performance","security","refactoring","test_coverage","general", name="finding_category", create_type=False), nullable=False),
        sa.Column("file_path",            sa.Text),
        sa.Column("line_number",          sa.Integer),
        sa.Column("line_number_end",      sa.Integer),
        sa.Column("title",                sa.String(500), nullable=False),
        sa.Column("description",          sa.Text, nullable=False),
        sa.Column("evidence",             sa.Text),
        sa.Column("recommendation",       sa.Text, nullable=False),
        sa.Column("review_comment",       sa.Text, nullable=False),
        sa.Column("edited_comment",       sa.Text),
        sa.Column("approval_status",      postgresql.ENUM("pending","approved","rejected", name="approval_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("approved_by",          sa.String(255)),
        sa.Column("approved_at",          sa.TIMESTAMP(timezone=True)),
        sa.Column("rejection_reason",     sa.Text),
        sa.Column("published",            sa.Boolean, nullable=False, server_default="false"),
        sa.Column("published_at",         sa.TIMESTAMP(timezone=True)),
        sa.Column("bitbucket_comment_id", sa.String(100)),
        sa.Column("confidence_score",     sa.Numeric(3, 2)),
        sa.Column("tags",                 postgresql.ARRAY(sa.Text)),
        sa.Column("created_at",           sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at",           sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at",           sa.TIMESTAMP(timezone=True)),
        sa.Column("created_by",           postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("updated_by",           postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
    )
    op.create_index("idx_findings_review",    "review_findings", ["review_id"],                     postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_findings_severity",  "review_findings", ["review_id", "severity"],         postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_findings_category",  "review_findings", ["review_id", "category"],         postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_findings_approval",  "review_findings", ["approval_status"],               postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_findings_published", "review_findings", ["published"],                     postgresql_where=sa.text("deleted_at IS NULL"))
    op.execute("CREATE TRIGGER trg_review_findings_updated_at BEFORE UPDATE ON review_findings FOR EACH ROW EXECUTE FUNCTION update_updated_at()")

    # ── review_comments ──────────────────────────────────────────────────────
    op.create_table(
        "review_comments",
        sa.Column("id",                   postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("finding_id",           postgresql.UUID(as_uuid=True), sa.ForeignKey("review_findings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_id",            postgresql.UUID(as_uuid=True), sa.ForeignKey("reviews.id",         ondelete="CASCADE"), nullable=False),
        sa.Column("author",               sa.String(255), nullable=False),
        sa.Column("comment_text",         sa.Text, nullable=False),
        sa.Column("parent_id",            postgresql.UUID(as_uuid=True), sa.ForeignKey("review_comments.id")),
        sa.Column("bitbucket_comment_id", sa.String(100)),
        sa.Column("is_resolved",          sa.Boolean, nullable=False, server_default="false"),
        sa.Column("resolved_at",          sa.TIMESTAMP(timezone=True)),
        sa.Column("resolved_by",          sa.String(255)),
        sa.Column("deleted_at",           sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at",           sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at",           sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_comments_finding", "review_comments", ["finding_id"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_comments_review",  "review_comments", ["review_id"],  postgresql_where=sa.text("deleted_at IS NULL"))
    op.execute("CREATE TRIGGER trg_review_comments_updated_at BEFORE UPDATE ON review_comments FOR EACH ROW EXECUTE FUNCTION update_updated_at()")

    # ── jira_requirements ────────────────────────────────────────────────────
    op.create_table(
        "jira_requirements",
        sa.Column("id",                   postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("review_id",            postgresql.UUID(as_uuid=True), sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jira_key",             sa.String(50), nullable=False),
        sa.Column("issue_type",           sa.String(50)),
        sa.Column("summary",              sa.Text),
        sa.Column("description",          sa.Text),
        sa.Column("acceptance_criteria",  postgresql.ARRAY(sa.Text)),
        sa.Column("technical_notes",      sa.Text),
        sa.Column("priority",             sa.String(20)),
        sa.Column("status",               sa.String(50)),
        sa.Column("assignee",             sa.String(255)),
        sa.Column("labels",               postgresql.ARRAY(sa.Text)),
        sa.Column("story_points",         sa.Numeric(5, 1)),
        sa.Column("raw_json",             postgresql.JSONB),
        sa.Column("created_at",           sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at",           sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_jira_req_review", "jira_requirements", ["review_id"])
    op.create_index("idx_jira_req_key",    "jira_requirements", ["jira_key"])

    # ── agent_executions ─────────────────────────────────────────────────────
    op.create_table(
        "agent_executions",
        sa.Column("id",                  postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("review_id",           postgresql.UUID(as_uuid=True), sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_name",          sa.String(100), nullable=False),
        sa.Column("status",              postgresql.ENUM("pending","running","completed","failed","skipped", name="agent_exec_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("sequence_number",     sa.Integer, nullable=False),
        sa.Column("started_at",          sa.TIMESTAMP(timezone=True)),
        sa.Column("completed_at",        sa.TIMESTAMP(timezone=True)),
        sa.Column("duration_ms",         sa.Integer),
        sa.Column("llm_provider",        sa.String(50)),
        sa.Column("llm_model",           sa.String(100)),
        sa.Column("prompt_tokens",       sa.Integer),
        sa.Column("completion_tokens",   sa.Integer),
        sa.Column("total_tokens",        sa.Integer),
        sa.Column("estimated_cost_usd",  sa.Numeric(10, 6)),
        sa.Column("findings_count",      sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message",       sa.Text),
        sa.Column("logs",                postgresql.JSONB),
        sa.Column("output_json",         postgresql.JSONB),
        sa.Column("created_at",          sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at",          sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_agent_exec_review", "agent_executions", ["review_id"])
    op.create_index("idx_agent_exec_status", "agent_executions", ["status"])
    op.execute("CREATE TRIGGER trg_agent_executions_updated_at BEFORE UPDATE ON agent_executions FOR EACH ROW EXECUTE FUNCTION update_updated_at()")

    # ── system_settings ──────────────────────────────────────────────────────
    op.create_table(
        "system_settings",
        sa.Column("id",                      postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id",                 postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("project_id",              postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id")),
        sa.Column("bitbucket_workspace",     sa.String(100)),
        sa.Column("bitbucket_access_token",  sa.Text),
        sa.Column("jira_base_url",           sa.Text),
        sa.Column("jira_email",              sa.String(255)),
        sa.Column("jira_api_token",          sa.Text),
        sa.Column("ai_provider",             sa.String(20), nullable=False, server_default="anthropic"),
        sa.Column("anthropic_api_key",       sa.Text),
        sa.Column("openai_api_key",          sa.Text),
        sa.Column("max_findings_per_agent",  sa.Integer, server_default="10"),
        sa.Column("agent_timeout_seconds",   sa.Integer, server_default="120"),
        sa.Column("created_at",              sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at",              sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by",              postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("updated_by",              postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("user_id", "project_id", name="uq_settings_user_project"),
    )
    op.create_index("idx_settings_user",    "system_settings", ["user_id"])
    op.create_index("idx_settings_project", "system_settings", ["project_id"])
    op.execute("CREATE TRIGGER trg_system_settings_updated_at BEFORE UPDATE ON system_settings FOR EACH ROW EXECUTE FUNCTION update_updated_at()")

    # ── audit_logs ───────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id",            postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("action",        postgresql.ENUM("review.start","review.complete","review.fail","review.cancel","comment.approve","comment.reject","comment.edit","comment.publish","settings.update","user.login","user.create", name="audit_action", create_type=False), nullable=False),
        sa.Column("actor_id",      postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("actor_email",   sa.String(255)),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id",   postgresql.UUID(as_uuid=True)),
        sa.Column("old_value",     postgresql.JSONB),
        sa.Column("new_value",     postgresql.JSONB),
        sa.Column("ip_address",    postgresql.INET),
        sa.Column("user_agent",    sa.Text),
        sa.Column("request_id",    sa.String(100)),
        sa.Column("metadata",      postgresql.JSONB),
        sa.Column("created_at",    sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_audit_actor",    "audit_logs", ["actor_id",    "created_at"])
    op.create_index("idx_audit_resource", "audit_logs", ["resource_type", "resource_id", "created_at"])
    op.create_index("idx_audit_action",   "audit_logs", ["action",      "created_at"])
    op.create_index("idx_audit_created",  "audit_logs", ["created_at"])


def downgrade() -> None:
    # Drop tables in reverse FK order
    for table in [
        "audit_logs", "system_settings", "agent_executions",
        "jira_requirements", "review_comments", "review_findings",
        "review_files", "reviews", "repositories", "projects", "users",
    ]:
        op.drop_table(table)

    # Drop ENUMs
    for enum_name in [
        "audit_action", "agent_exec_status", "approval_status",
        "finding_category", "finding_severity",
        "review_recommendation", "review_status",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")

    op.execute("DROP FUNCTION IF EXISTS update_updated_at()")
