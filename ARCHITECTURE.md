# ReviewAI — Architecture & Folder Structure

> **Clean Architecture** — dependencies always point inward.
> Domain → Application → Infrastructure → Interface

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Angular 20, Angular Material, NgRx Signal Store, TypeScript |
| Backend | Python 3.13, FastAPI, LangGraph, LangChain |
| AI | Local Antigravity Bridge (Connect-RPC over host loopback) / GPT-4o / Gemini / Claude |
| Database | PostgreSQL 16, SQLAlchemy (async) |
| Cache / Pub-Sub | Redis 7 |
| Integrations | Bitbucket Cloud API, Jira Cloud API |
| DevOps | Docker, docker-compose (network_mode: host for bridge loopback), GitHub Actions |

---

## 1. Backend Folder Structure

```
backend/
├── app/
│   │
│   ├── domain/                        # Pure business logic — zero external dependencies
│   │   ├── entities/
│   │   │   ├── review.py              # Review aggregate root (status machine, risk score)
│   │   │   ├── finding.py             # Finding value object
│   │   │   ├── comment.py             # Comment approval entity
│   │   │   └── requirement.py         # Jira requirement model
│   │   ├── value_objects/
│   │   │   ├── severity.py            # Enum: critical / high / medium / low / info
│   │   │   ├── approval_status.py     # Enum: pending / approved / rejected
│   │   │   └── review_status.py       # Enum: pending / running / completed / failed
│   │   ├── repositories/              # Abstract repository interfaces (ports)
│   │   │   ├── review_repository.py
│   │   │   ├── finding_repository.py
│   │   │   └── settings_repository.py
│   │   └── exceptions.py              # Domain-specific exceptions
│   │
│   ├── application/                   # Use cases + orchestration
│   │   ├── use_cases/
│   │   │   ├── start_review.py        # Validate input → create Review → trigger workflow
│   │   │   ├── get_review.py          # Fetch status + metadata
│   │   │   ├── approve_comments.py    # Human-in-the-loop approval
│   │   │   ├── publish_comments.py    # Post to Bitbucket (approved only)
│   │   │   └── update_settings.py     # Encrypt + persist credentials
│   │   ├── services/
│   │   │   ├── review_orchestrator.py # Coordinate workflow + DB persistence
│   │   │   └── encryption_service.py  # Fernet encrypt / decrypt
│   │   ├── dtos/
│   │   │   ├── review_dto.py
│   │   │   ├── finding_dto.py
│   │   │   └── settings_dto.py
│   │   └── ports/                     # Outbound port interfaces
│   │       ├── bitbucket_port.py      # get_pr(), get_diff(), post_comment()
│   │       ├── jira_port.py           # get_issue(), get_comments()
│   │       └── llm_port.py            # invoke(system, user) → str
│   │
│   ├── infrastructure/                # External adapters (implement ports)
│   │   ├── db/
│   │   │   ├── database.py            # Async engine, session factory, Base
│   │   │   ├── models/
│   │   │   │   └── models.py          # SQLAlchemy ORM models (all tables)
│   │   │   ├── repositories/
│   │   │   │   ├── review_repo.py     # Concrete ReviewRepository
│   │   │   │   ├── finding_repo.py
│   │   │   │   └── settings_repo.py
│   │   │   └── migrations/            # Alembic versions
│   │   │       ├── env.py
│   │   │       └── versions/
│   │   ├── cache/
│   │   │   ├── redis_client.py        # Async Redis connection pool
│   │   │   └── progress_publisher.py  # Publish SSE events to Redis pub/sub
│   │   ├── adapters/
│   │   │   ├── bitbucket_adapter.py   # Implements BitbucketPort via httpx
│   │   │   ├── jira_adapter.py        # Implements JiraPort via httpx
│   │   │   ├── openai_adapter.py      # Implements LLMPort via OpenAI SDK
│   │   │   └── anthropic_adapter.py   # Implements LLMPort via Anthropic SDK
│   │   └── security/
│   │       └── fernet_encryption.py   # Symmetric encryption for stored secrets
│   │
│   ├── agents/                        # LangGraph multi-agent pipeline
│   │   ├── state.py                   # ReviewState TypedDict (shared context)
│   │   ├── base_agent.py              # Abstract base: LLM, logging, finding factory
│   │   ├── workflow.py                # StateGraph wiring + compile
│   │   ├── nodes/
│   │   │   ├── pr_fetch_node.py       # Bitbucket → PR metadata, diff, Jira key
│   │   │   ├── jira_fetch_node.py     # Jira → story, ACs, technical notes
│   │   │   ├── req_extraction.py      # Agent 1: structured requirements JSON
│   │   │   ├── req_validation.py      # Agent 2: gap analysis vs requirements
│   │   │   ├── code_quality.py        # Agent 3: SOLID, layer violations
│   │   │   ├── sql_performance.py     # Agent 4: SELECT*, N+1, pagination
│   │   │   ├── security.py            # Agent 5: OWASP Top 10
│   │   │   ├── refactoring.py         # Agent 6: god classes, patterns
│   │   │   ├── test_coverage.py       # Agent 7: missing tests
│   │   │   └── review_summary.py      # Agent 8: risk score, exec summary
│   │   └── prompts/                   # Versioned system prompts (separated from logic)
│   │       ├── req_extraction.py
│   │       ├── code_quality.py
│   │       ├── security.py
│   │       └── review_summary.py
│   │
│   ├── api/                           # FastAPI interface layer
│   │   ├── routes/
│   │   │   ├── reviews.py             # POST /start, GET /{id}, GET /{id}/stream
│   │   │   ├── findings.py            # GET /{reviewId}/findings
│   │   │   ├── comments.py            # PUT, POST /approve /reject /publish
│   │   │   └── settings.py            # GET / PUT /settings
│   │   ├── middleware/
│   │   │   ├── cors.py
│   │   │   ├── request_id.py          # Injects X-Request-ID into log context
│   │   │   └── error_handler.py       # Global exception → JSON response
│   │   └── dependencies.py            # FastAPI Depends() factories
│   │
│   ├── schemas/                       # Pydantic request/response schemas
│   │   ├── review_schema.py
│   │   ├── finding_schema.py
│   │   ├── comment_schema.py
│   │   └── settings_schema.py
│   │
│   └── core/                          # Cross-cutting concerns
│       ├── config.py                  # Pydantic Settings (env + .env)
│       ├── logging.py                 # structlog JSON logger
│       └── container.py              # DI container: wire adapters to ports
│
├── tests/
│   ├── unit/
│   │   ├── domain/                    # Entity + value object tests (no I/O)
│   │   ├── application/               # Use case tests with mocked ports
│   │   └── agents/                    # Agent tests with mocked LLM
│   ├── integration/
│   │   ├── test_reviews_api.py        # Full HTTP round-trip with real DB
│   │   ├── test_publish_flow.py       # Approve → publish guard
│   │   └── test_workflow.py           # End-to-end pipeline (mocked LLM)
│   ├── fixtures/
│   │   ├── pr_diff.txt                # Sample unified diff
│   │   ├── jira_response.json         # Mocked Jira API payload
│   │   └── llm_responses/             # Mocked LLM JSON per agent
│   └── conftest.py                    # Shared fixtures: DB, Redis, async client
│
├── alembic.ini
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

---

## 2. Frontend Folder Structure (Angular 20)

```
frontend/src/
├── app/
│   │
│   ├── core/                          # Singleton services — bootstrapped once
│   │   ├── models/
│   │   │   └── models.ts              # TypeScript interfaces mirroring backend schemas
│   │   ├── services/
│   │   │   ├── review-api.service.ts  # HTTP client for all backend endpoints
│   │   │   └── sse.service.ts         # EventSource wrapper for SSE streaming
│   │   ├── store/
│   │   │   └── review.store.ts        # NgRx Signal Store: state + computed signals
│   │   ├── guards/
│   │   │   └── settings.guard.ts      # Redirect if credentials not configured
│   │   └── interceptors/
│   │       └── error.interceptor.ts   # Global HTTP error → toast notification
│   │
│   ├── shared/                        # Dumb reusable components — no business logic
│   │   ├── components/
│   │   │   ├── severity-badge/        # <app-severity-badge severity="critical"/>
│   │   │   ├── risk-score-ring/       # Circular risk score with colour coding
│   │   │   ├── progress-bar/          # Animated gradient progress bar
│   │   │   ├── finding-card/          # Single finding display card
│   │   │   ├── agent-status-chip/     # Pulsing live agent indicator
│   │   │   ├── empty-state/           # Empty list placeholder
│   │   │   └── confirm-dialog/        # Approval confirmation modal
│   │   ├── pipes/
│   │   │   ├── severity-color.pipe.ts # severity → CSS class name
│   │   │   └── time-ago.pipe.ts       # Relative timestamps
│   │   └── directives/
│   │       └── auto-scroll.directive.ts  # Auto-scroll log container on new entries
│   │
│   ├── features/                      # Lazy-loaded smart components (one per route)
│   │   │
│   │   ├── dashboard/                 # Route: /dashboard
│   │   │   └── dashboard.component.ts # PR URL input, recent reviews, start action
│   │   │
│   │   ├── review-progress/           # Route: /reviews/:id/progress
│   │   │   ├── review-progress.component.ts
│   │   │   └── components/
│   │   │       ├── agent-steps.component.ts   # Visual step pipeline
│   │   │       └── log-viewer.component.ts    # Monospace SSE log stream
│   │   │
│   │   ├── review-results/            # Route: /reviews/:id/results
│   │   │   ├── review-results.component.ts
│   │   │   └── components/
│   │   │       ├── summary-header.component.ts   # Risk ring + recommendation
│   │   │       ├── findings-list.component.ts    # Filtered + grouped cards
│   │   │       └── finding-detail.component.ts   # Expanded view with diff
│   │   │
│   │   ├── comment-approval/          # Route: /reviews/:id/approval
│   │   │   ├── comment-approval.component.ts
│   │   │   └── components/
│   │   │       ├── approval-status-bar.component.ts  # Pending/Approved/Rejected counts
│   │   │       ├── comment-editor.component.ts       # Editable textarea per finding
│   │   │       └── batch-actions.component.ts        # Approve All / Reject All / Publish
│   │   │
│   │   └── settings/                  # Route: /settings
│   │       └── settings.component.ts  # Bitbucket, Jira, AI credentials form
│   │
│   ├── app.component.ts               # Root shell: sidebar + <router-outlet>
│   ├── app.config.ts                  # provideRouter, provideHttpClient, provideAnimations
│   └── app.routes.ts                  # Lazy route definitions
│
├── environments/
│   ├── environment.ts                 # { apiUrl: 'http://localhost:8000/api' }
│   └── environment.prod.ts            # { apiUrl: '/api' }
│
└── styles.scss                        # Design tokens, CSS variables, utility classes
```

---

## 3. Shared DTO Structure

> Backend Pydantic schemas and Angular TypeScript interfaces must match **1:1**.

```
shared/dtos/
├── review.dto          # StartReviewRequest, ReviewResponse
├── finding.dto         # FindingResponse (id, severity, category, file_path, line,
│                       #   title, description, evidence, recommendation,
│                       #   review_comment, approval_status, published)
├── comment.dto         # ApproveRequest, RejectRequest, PublishRequest, UpdateCommentRequest
├── summary.dto         # ReviewSummaryResponse (risk_score, recommendation,
│                       #   findings_by_severity, agent_summaries, executive_summary)
└── settings.dto        # SettingsRequest, SettingsResponse (masked — no raw secrets)
```

---

## 4. Agent Folder Structure

```
backend/app/agents/
│
├── state.py            # ReviewState TypedDict
│                       # Fields: review_id, settings, pr_context, jira_context,
│                       #         requirements, findings[], logs[],
│                       #         current_agent, progress_percent, error, summary
│
├── base_agent.py       # Abstract BaseAgent
│                       # Provides: _get_llm(), _invoke_llm_json(),
│                       #           _make_finding(), _log()
│
├── workflow.py         # LangGraph StateGraph
│                       # Wires 10 nodes → compiles graph → exposes execute()
│
├── nodes/              # One module per pipeline step
│   ├── pr_fetch_node.py       # Step 1 — Bitbucket API
│   ├── jira_fetch_node.py     # Step 2 — Jira API
│   ├── req_extraction.py      # Agent 1 — Requirement extraction
│   ├── req_validation.py      # Agent 2 — Gap analysis
│   ├── code_quality.py        # Agent 3 — Code quality
│   ├── sql_performance.py     # Agent 4 — SQL performance
│   ├── security.py            # Agent 5 — Security (OWASP)
│   ├── refactoring.py         # Agent 6 — Refactoring
│   ├── test_coverage.py       # Agent 7 — Test coverage
│   └── review_summary.py      # Agent 8 — Summary + risk score
│
└── prompts/            # System prompts separated from node logic
    ├── req_extraction.py
    ├── code_quality.py
    ├── security.py
    └── review_summary.py
```

### Pipeline Flow

```
START
  ↓
pr_fetch  →  jira_fetch  →  req_extraction  →  req_validation
  →  code_quality  →  sql_performance  →  security
  →  refactoring  →  test_coverage  →  review_summary
  ↓
END  →  Persist DB  →  Publish SSE event
```

---

## 5. Configuration Structure

```
backend/
├── .env.example        # Template — commit this
├── .env                # Secrets — git-ignored
└── app/core/config.py  # Pydantic BaseSettings

# Variable groups:
# ─── App ─────────────────────────────────
APP_ENV=development
APP_SECRET_KEY=change-me
APP_PORT=8000
ALLOWED_ORIGINS=http://localhost:4200

# ─── Database ────────────────────────────
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/reviewai
DATABASE_POOL_SIZE=10

# ─── Redis ───────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ─── AI Provider ─────────────────────────
LLM_PROVIDER=antigravity       # antigravity | openai | gemini | anthropic
ANTIGRAVITY_MODEL=gemini-3.6-flash
ANTIGRAVITY_TIMEOUT_SECONDS=120
ALLOW_LLM_FALLBACK=false       # Disable silent fallback to public Gemini free tier
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIzaSy...

# ─── Integrations ────────────────────────
BITBUCKET_ACCESS_TOKEN=...
JIRA_BASE_URL=https://org.atlassian.net
JIRA_EMAIL=you@company.com
JIRA_API_TOKEN=...

# ─── Security ────────────────────────────
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=<base64-fernet-key>

# ─── Agent Tuning ────────────────────────
AGENT_TIMEOUT_SECONDS=120
MAX_CONCURRENT_REVIEWS=5
```

```
frontend/src/environments/
├── environment.ts          # { production: false, apiUrl: 'http://localhost:8000/api' }
└── environment.prod.ts     # { production: true,  apiUrl: '/api' }
```

---

## 6. Testing Structure

```
backend/tests/
├── conftest.py             # Fixtures: async client, test DB, Redis mock, LLM mock
├── unit/
│   ├── domain/
│   │   ├── test_review_entity.py       # Status transitions, risk score logic
│   │   └── test_finding_entity.py      # Severity ordering, category validation
│   ├── application/
│   │   ├── test_start_review.py        # Use case with mocked ports
│   │   └── test_approve_comments.py    # Approval guard logic
│   └── agents/
│       ├── test_req_extraction.py      # Mocked LLM → assert output shape
│       ├── test_security_agent.py      # Known-vulnerable diff → CRITICAL finding
│       └── test_workflow.py            # Full pipeline (all agents mocked)
├── integration/
│   ├── test_reviews_api.py             # HTTP POST /start → GET /{id} round-trip
│   ├── test_findings_api.py            # Filter by severity / category
│   └── test_publish_flow.py            # Approve → publish enforces guard
└── fixtures/
    ├── pr_diff.txt                     # Sample unified diff
    ├── jira_response.json              # Mocked Jira payload
    └── llm_responses/                  # Per-agent mocked JSON outputs

frontend/src/
└── **/*.spec.ts            # Co-located tests per component/service
    ├── core/store/review.store.spec.ts
    ├── features/dashboard/dashboard.component.spec.ts
    └── features/comment-approval/*.spec.ts
```

### Test Coverage Targets

| Layer | Type | Target |
|-------|------|--------|
| Domain entities | Unit (no I/O) | 100% |
| Application use cases | Unit (mocked ports) | 90% |
| Agent nodes | Unit (mocked LLM) | 85% |
| API endpoints | Integration | 80% |
| Angular components | Unit (TestBed) | 75% |

---

## 7. Docker Structure

```
review-ai/
├── docker-compose.yml          # Production: all 4 services
├── docker-compose.dev.yml      # Dev overrides: volume mounts, pgAdmin, hot-reload
│
├── backend/
│   ├── Dockerfile              # Multi-stage: builder → slim runtime, non-root user
│   └── .dockerignore
│
├── frontend/
│   ├── Dockerfile              # Stage 1: node:20 ng build | Stage 2: nginx:alpine
│   ├── nginx.conf              # SPA routing, /api proxy, SSE proxy_buffering off
│   └── .dockerignore
│
└── docker/
    ├── postgres/
    │   └── init.sql            # Create DB + uuid-ossp, pgcrypto extensions
    └── redis/
        └── redis.conf          # maxmemory 256mb, allkeys-lru

# Services:
#   postgres           :5432  health: pg_isready
#   redis              :6379  health: redis-cli ping
#   antigravity-bridge :8899  network_mode: host (auto-discovers local Google session)
#   backend            :8000  network_mode: host (direct loopback reachability to bridge)
#   frontend           :80    depends_on: backend
#   pgadmin            :5050  profile: dev
```

---

## Clean Architecture Dependency Rule

```
┌──────────────────────────────────────┐
│         Interface Layer              │  FastAPI routes · Angular components
│   (api/, schemas/, app.component)    │
└─────────────────┬────────────────────┘
                  │ depends on ↓
┌─────────────────▼────────────────────┐
│        Application Layer             │  Use cases · DTOs · Port interfaces
│   (use_cases/, services/, ports/)    │
└─────────────────┬────────────────────┘
                  │ depends on ↓
┌─────────────────▼────────────────────┐
│           Domain Layer               │  Entities · Value objects · Repo interfaces
│  (entities/, value_objects/, repos/) │  ← ZERO external dependencies
└──────────────────────────────────────┘
                  ↑ implements
┌─────────────────┴────────────────────┐
│       Infrastructure Layer           │  DB · Redis · httpx adapters
│  (db/, cache/, adapters/, security/) │
└──────────────────────────────────────┘
```

> **Invariant**: The Domain layer never imports from Infrastructure, Application, or Interface.
> Infrastructure and Interface layers never import from each other.

---

## Quick Start

```bash
# 1. Clone & configure
cp backend/.env.example backend/.env
# Edit backend/.env — add API keys

# 2. Start all services
docker compose up -d --build

# 3. Apply DB migrations
docker compose exec backend alembic upgrade head

# 4. Access
#   Frontend  →  http://localhost
#   API Docs  →  http://localhost:8000/api/docs
#   pgAdmin   →  http://localhost:5050  (dev profile only)
```
