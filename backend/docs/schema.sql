-- ============================================================
-- ReviewAI — PostgreSQL Schema DDL
-- All tables use UUID PKs, soft delete, and audit columns
-- ============================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- USERS
-- ============================================================
CREATE TABLE users (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           VARCHAR(255) NOT NULL UNIQUE,
    full_name       VARCHAR(255),
    avatar_url      TEXT,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    is_superuser    BOOLEAN     NOT NULL DEFAULT FALSE,
    last_login_at   TIMESTAMPTZ,
    -- audit
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,           -- soft delete
    created_by      UUID        REFERENCES users(id),
    updated_by      UUID        REFERENCES users(id)
);

CREATE INDEX idx_users_email        ON users(email) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_is_active    ON users(is_active) WHERE deleted_at IS NULL;

-- ============================================================
-- PROJECTS
-- ============================================================
CREATE TABLE projects (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    owner_id        UUID        NOT NULL REFERENCES users(id),
    jira_project_key VARCHAR(50),
    bitbucket_workspace VARCHAR(100),
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    -- audit
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    created_by      UUID        REFERENCES users(id),
    updated_by      UUID        REFERENCES users(id)
);

CREATE INDEX idx_projects_owner        ON projects(owner_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_projects_jira_key     ON projects(jira_project_key) WHERE deleted_at IS NULL;

-- ============================================================
-- REPOSITORIES
-- ============================================================
CREATE TABLE repositories (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID        NOT NULL REFERENCES projects(id),
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(255) NOT NULL,
    workspace       VARCHAR(100) NOT NULL,
    full_name       VARCHAR(500) NOT NULL,  -- workspace/slug
    clone_url       TEXT,
    default_branch  VARCHAR(100) DEFAULT 'main',
    language        VARCHAR(50),
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    -- audit
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    created_by      UUID        REFERENCES users(id),
    updated_by      UUID        REFERENCES users(id),

    UNIQUE(workspace, slug)
);

CREATE INDEX idx_repos_project     ON repositories(project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_repos_full_name   ON repositories(full_name) WHERE deleted_at IS NULL;

-- ============================================================
-- REVIEWS
-- ============================================================
CREATE TYPE review_status AS ENUM (
    'pending', 'running', 'completed', 'failed', 'cancelled'
);

CREATE TYPE review_recommendation AS ENUM (
    'APPROVE', 'REQUEST_CHANGES', 'NEEDS_DISCUSSION'
);

CREATE TABLE reviews (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    repository_id       UUID            REFERENCES repositories(id),
    user_id             UUID            NOT NULL REFERENCES users(id),
    -- PR metadata
    pr_number           INTEGER         NOT NULL,
    pr_title            TEXT,
    pr_url              TEXT,
    pr_description      TEXT,
    source_branch       VARCHAR(255),
    target_branch       VARCHAR(255),
    pr_author           VARCHAR(255),
    pr_author_email     VARCHAR(255),
    base_commit_hash    VARCHAR(40),
    head_commit_hash    VARCHAR(40),
    files_changed       INTEGER,
    lines_added         INTEGER,
    lines_removed       INTEGER,
    -- Jira
    jira_key            VARCHAR(50),
    -- Status
    status              review_status   NOT NULL DEFAULT 'pending',
    current_agent       VARCHAR(100),
    progress_percent    INTEGER         NOT NULL DEFAULT 0
                                        CHECK (progress_percent BETWEEN 0 AND 100),
    error_message       TEXT,
    -- Results
    risk_score          NUMERIC(5,2)    CHECK (risk_score BETWEEN 0 AND 100),
    overall_recommendation review_recommendation,
    executive_summary   TEXT,
    total_findings      INTEGER         NOT NULL DEFAULT 0,
    critical_count      INTEGER         NOT NULL DEFAULT 0,
    high_count          INTEGER         NOT NULL DEFAULT 0,
    medium_count        INTEGER         NOT NULL DEFAULT 0,
    low_count           INTEGER         NOT NULL DEFAULT 0,
    -- Timing
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    duration_seconds    INTEGER,
    -- audit
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,
    created_by          UUID            REFERENCES users(id),
    updated_by          UUID            REFERENCES users(id)
);

CREATE INDEX idx_reviews_user           ON reviews(user_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_reviews_repo           ON reviews(repository_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_reviews_status         ON reviews(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_reviews_jira_key       ON reviews(jira_key) WHERE deleted_at IS NULL;
CREATE INDEX idx_reviews_created_at     ON reviews(created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX idx_reviews_pr_number      ON reviews(repository_id, pr_number) WHERE deleted_at IS NULL;

-- ============================================================
-- REVIEW FILES
-- ============================================================
CREATE TABLE review_files (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    review_id       UUID        NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    file_path       TEXT        NOT NULL,
    file_type       VARCHAR(50),
    change_type     VARCHAR(20) CHECK (change_type IN ('added','modified','deleted','renamed')),
    lines_added     INTEGER     DEFAULT 0,
    lines_removed   INTEGER     DEFAULT 0,
    diff_content    TEXT,       -- unified diff for this file
    -- audit
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_review_files_review    ON review_files(review_id);
CREATE INDEX idx_review_files_path      ON review_files(review_id, file_path);

-- ============================================================
-- REVIEW FINDINGS
-- ============================================================
CREATE TYPE finding_severity AS ENUM (
    'critical', 'high', 'medium', 'low', 'info'
);

CREATE TYPE finding_category AS ENUM (
    'requirement', 'code_quality', 'sql_performance',
    'security', 'refactoring', 'test_coverage', 'general'
);

CREATE TYPE approval_status AS ENUM (
    'pending', 'approved', 'rejected'
);

CREATE TABLE review_findings (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    review_id           UUID            NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    review_file_id      UUID            REFERENCES review_files(id),
    agent_name          VARCHAR(100)    NOT NULL,
    -- Classification
    severity            finding_severity NOT NULL,
    category            finding_category NOT NULL,
    -- Location
    file_path           TEXT,
    line_number         INTEGER,
    line_number_end     INTEGER,
    column_number       INTEGER,
    -- Content
    title               VARCHAR(500)    NOT NULL,
    description         TEXT            NOT NULL,
    evidence            TEXT,           -- code snippet or excerpt
    recommendation      TEXT            NOT NULL,
    -- Review comment (what gets posted to Bitbucket)
    review_comment      TEXT            NOT NULL,
    edited_comment      TEXT,           -- human-edited version
    -- Approval workflow
    approval_status     approval_status NOT NULL DEFAULT 'pending',
    approved_by         VARCHAR(255),
    approved_at         TIMESTAMPTZ,
    rejection_reason    TEXT,
    -- Publishing
    published           BOOLEAN         NOT NULL DEFAULT FALSE,
    published_at        TIMESTAMPTZ,
    bitbucket_comment_id VARCHAR(100),
    -- Metadata
    confidence_score    NUMERIC(3,2)    CHECK (confidence_score BETWEEN 0 AND 1),
    tags                TEXT[],
    -- audit
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,
    created_by          UUID            REFERENCES users(id),
    updated_by          UUID            REFERENCES users(id)
);

CREATE INDEX idx_findings_review        ON review_findings(review_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_findings_severity      ON review_findings(review_id, severity) WHERE deleted_at IS NULL;
CREATE INDEX idx_findings_category      ON review_findings(review_id, category) WHERE deleted_at IS NULL;
CREATE INDEX idx_findings_approval      ON review_findings(approval_status) WHERE deleted_at IS NULL;
CREATE INDEX idx_findings_published     ON review_findings(published) WHERE deleted_at IS NULL;
CREATE INDEX idx_findings_file_path     ON review_findings(review_id, file_path) WHERE deleted_at IS NULL;

-- ============================================================
-- REVIEW COMMENTS  (inline Bitbucket-style comments)
-- ============================================================
CREATE TABLE review_comments (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    finding_id          UUID        NOT NULL REFERENCES review_findings(id) ON DELETE CASCADE,
    review_id           UUID        NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    author              VARCHAR(255) NOT NULL,
    comment_text        TEXT        NOT NULL,
    parent_id           UUID        REFERENCES review_comments(id),   -- threading
    bitbucket_comment_id VARCHAR(100),
    is_resolved         BOOLEAN     NOT NULL DEFAULT FALSE,
    resolved_at         TIMESTAMPTZ,
    resolved_by         VARCHAR(255),
    -- audit
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ
);

CREATE INDEX idx_comments_finding       ON review_comments(finding_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_comments_review        ON review_comments(review_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_comments_parent        ON review_comments(parent_id) WHERE deleted_at IS NULL;

-- ============================================================
-- JIRA REQUIREMENTS
-- ============================================================
CREATE TABLE jira_requirements (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    review_id           UUID        NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    jira_key            VARCHAR(50) NOT NULL,
    issue_type          VARCHAR(50),
    summary             TEXT,
    description         TEXT,
    acceptance_criteria TEXT[],     -- extracted AC bullet points
    technical_notes     TEXT,
    priority            VARCHAR(20),
    status              VARCHAR(50),
    assignee            VARCHAR(255),
    labels              TEXT[],
    story_points        NUMERIC(5,1),
    raw_json            JSONB,      -- full Jira response for audit
    -- audit
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_jira_req_review        ON jira_requirements(review_id);
CREATE INDEX idx_jira_req_key           ON jira_requirements(jira_key);
CREATE INDEX idx_jira_req_raw           ON jira_requirements USING GIN(raw_json);

-- ============================================================
-- AGENT EXECUTIONS  (per-agent run log)
-- ============================================================
CREATE TYPE agent_exec_status AS ENUM (
    'pending', 'running', 'completed', 'failed', 'skipped'
);

CREATE TABLE agent_executions (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    review_id           UUID            NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    agent_name          VARCHAR(100)    NOT NULL,
    status              agent_exec_status NOT NULL DEFAULT 'pending',
    sequence_number     INTEGER         NOT NULL,   -- order in pipeline
    -- Timing
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    duration_ms         INTEGER,
    -- LLM usage
    llm_provider        VARCHAR(50),
    llm_model           VARCHAR(100),
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    total_tokens        INTEGER,
    estimated_cost_usd  NUMERIC(10,6),
    -- Results
    findings_count      INTEGER         NOT NULL DEFAULT 0,
    error_message       TEXT,
    logs                JSONB,          -- structured execution log entries
    output_json         JSONB,          -- raw LLM output before parsing
    -- audit
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agent_exec_review      ON agent_executions(review_id);
CREATE INDEX idx_agent_exec_status      ON agent_executions(status);
CREATE INDEX idx_agent_exec_agent       ON agent_executions(agent_name);

-- ============================================================
-- SYSTEM SETTINGS  (encrypted credentials per user/project)
-- ============================================================
CREATE TABLE system_settings (
    id                      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id                 UUID        REFERENCES users(id),
    project_id              UUID        REFERENCES projects(id),
    -- Scope: NULL = global, user_id only = user-level, both = project-level
    -- Bitbucket
    bitbucket_workspace     VARCHAR(100),
    bitbucket_access_token  TEXT,       -- Fernet encrypted
    -- Jira
    jira_base_url           TEXT,
    jira_email              VARCHAR(255),
    jira_api_token          TEXT,       -- Fernet encrypted
    -- AI Provider
    ai_provider             VARCHAR(20) NOT NULL DEFAULT 'anthropic'
                                        CHECK (ai_provider IN ('anthropic','openai')),
    anthropic_api_key       TEXT,       -- Fernet encrypted
    openai_api_key          TEXT,       -- Fernet encrypted
    -- Agent tuning
    max_findings_per_agent  INTEGER     DEFAULT 10,
    agent_timeout_seconds   INTEGER     DEFAULT 120,
    -- audit
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by              UUID        REFERENCES users(id),
    updated_by              UUID        REFERENCES users(id),

    UNIQUE(user_id, project_id)         -- one settings row per scope
);

CREATE INDEX idx_settings_user      ON system_settings(user_id);
CREATE INDEX idx_settings_project   ON system_settings(project_id);

-- ============================================================
-- AUDIT LOGS  (immutable append-only action trail)
-- ============================================================
CREATE TYPE audit_action AS ENUM (
    'review.start', 'review.complete', 'review.fail', 'review.cancel',
    'comment.approve', 'comment.reject', 'comment.edit', 'comment.publish',
    'settings.update', 'user.login', 'user.create'
);

CREATE TABLE audit_logs (
    id              UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    action          audit_action    NOT NULL,
    actor_id        UUID            REFERENCES users(id),
    actor_email     VARCHAR(255),   -- denormalised — preserved even if user deleted
    resource_type   VARCHAR(50)     NOT NULL,   -- 'review' | 'finding' | 'settings'
    resource_id     UUID,
    old_value       JSONB,          -- snapshot before change
    new_value       JSONB,          -- snapshot after change
    ip_address      INET,
    user_agent      TEXT,
    request_id      VARCHAR(100),   -- X-Request-ID for correlation
    metadata        JSONB,
    -- No updated_at / deleted_at — audit rows are immutable
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_actor        ON audit_logs(actor_id, created_at DESC);
CREATE INDEX idx_audit_resource     ON audit_logs(resource_type, resource_id, created_at DESC);
CREATE INDEX idx_audit_action       ON audit_logs(action, created_at DESC);
CREATE INDEX idx_audit_created      ON audit_logs(created_at DESC);

-- ============================================================
-- TRIGGERS  — auto-update updated_at
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'users','projects','repositories','reviews',
        'review_files','review_findings','review_comments',
        'agent_executions','system_settings'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_%s_updated_at
             BEFORE UPDATE ON %s
             FOR EACH ROW EXECUTE FUNCTION update_updated_at()',
            tbl, tbl
        );
    END LOOP;
END;
$$;
