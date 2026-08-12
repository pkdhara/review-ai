# ReviewAI — Autonomous Multi-Agent AI Code Review Platform

> **Automated, Production-Grade PR Code Reviews Powered by LangGraph Multi-Agent Workflows & Antigravity LLM Backend**

---

## 🚀 What is ReviewAI?

**ReviewAI** is an intelligent, autonomous pull request code review platform designed for enterprise engineering teams. It connects directly to **Bitbucket Cloud** and **Jira Cloud**, pulling PR diffs, source context, and Jira acceptance criteria to perform deep static and semantic analysis across 8 specialized AI agents.

### Key Capabilities

- 🤖 **Multi-Agent Analysis Workflow (LangGraph)**:
  1. **Requirement Extraction**: Extracts business rules, ACs, and API requirements from Jira stories.
  2. **Requirement Validation**: Performs gap analysis to ensure pull requests fulfill all Jira ACs without regressions.
  3. **Code Quality**: Enforces SOLID principles, clean code patterns, and layer boundary rules.
  4. **SQL Performance**: Flags `SELECT *`, N+1 queries, missing index opportunities, and unpaginated database queries.
  5. **Security (OWASP Top 10)**: Identifies SQL injection, XSS, insecure deserialization, and hardcoded secrets.
  6. **Refactoring**: Spots God classes, long functions, duplicate logic, and code smells.
  7. **Test Coverage**: Verifies unit/integration test presence for changed source files.
  8. **Executive Summary**: Generates a unified risk score (0–100), severity breakdown, and merge recommendation.

- ⚡ **Local Antigravity LLM Bridge (Zero API Cost)**:
  Optionally routes LLM requests through a local OpenAI-compatible bridge that connects directly to your authenticated Google session in Antigravity — bypassing public Gemini API credit purchases and 429 quota exhaustion.

- 🛡️ **Human-In-The-Loop Approval**:
  Engineers can review, edit, approve, or reject generated findings before automatically publishing comments back to Bitbucket PR lines.

- 📊 **Real-Time Streaming UI**:
  Angular 20 frontend with NgRx Signal Store and SSE log streaming for live progress monitoring.

---

## 📋 Prerequisites

Before setting up ReviewAI, ensure your host server meets the following requirements:

### System Requirements
| Component | Minimum Requirement | Recommended |
|-----------|--------------------|-------------|
| **OS** | Linux (Ubuntu 20.04+, Debian 11+, RHEL 8+, Fedora) or macOS | Linux (Ubuntu 22.04 LTS) |
| **CPU** | 2 Cores | 4+ Cores |
| **RAM** | 4 GB | 8 GB+ |
| **Disk** | 10 GB free space | 20 GB+ SSD |
| **Docker** | Docker Engine 24.0+ & Docker Compose v2.20+ | Docker Engine 26.0+ |

### Software & API Requirements
- **Git** (installed on host for local worktree indexing).
- **Bitbucket Account**: Workspace slug and an App Password / API Token with `repositories:read` and `pullrequests:write` permissions.
- **Jira Account**: Base URL, user email, and API Token with issue read permissions.
- **LLM Backend (Choose One)**:
  - **Option A (Antigravity Bridge - Recommended for zero cost)**: Antigravity IDE / Language Server running on the host machine logged into your Google account.
  - **Option B (Cloud API)**: OpenAI API key (`gpt-4o`), Gemini API key (`gemini-3.6-flash`), or Anthropic API key (`claude-3-5-sonnet`).

### 🔐 Local Git Repository Permissions
Because the `reviewai_backend` container runs as a non-root user (`UID 999`), local repositories mounted into the container must have read/execute access permissions on their `.git` metadata directories:

```bash
# Grant read/execute access to local repositories for local worktree indexing
chmod -R o+rX /home/pradeep/fc/
# OR for any local repository base directory:
chmod -R g+rX,o+rX /path/to/local/git/repos/.git
```
*Note: Without these read permissions, Git inside the container will report `fatal: not a git repository` and fallback to diff-only context without deep local symbol indexing.*

---

## 🛠️ Quick Start Installation

Follow these simple steps to run ReviewAI using Docker:

### Step 1: Clone Repository & Setup Environment
```bash
git clone https://github.com/your-org/review-ai.git
cd review-ai
cp backend/.env.example backend/.env
```

### Step 2: Configure Environment Credentials
Edit `backend/.env` to configure your Bitbucket, Jira, and LLM Provider settings:

#### Bitbucket & Jira Credentials
```ini
# Bitbucket Integration (Permissions: repositories:read & pullrequests:write)
BITBUCKET_USERNAME=your_username
BITBUCKET_ACCESS_TOKEN=your_bitbucket_app_password
BITBUCKET_WORKSPACE=your_workspace_slug

# Jira Integration
JIRA_BASE_URL=https://your-org.atlassian.net
JIRA_EMAIL=you@company.com
JIRA_API_TOKEN=your_jira_api_token
```

#### LLM Provider Configuration (`LLM_PROVIDER`):

Set `LLM_PROVIDER` in `backend/.env` to select your backend:

**Option 1: Antigravity Local LLM (Zero API Cost)**
Routes requests through local Antigravity session (`127.0.0.1:8899`):
```ini
LLM_PROVIDER=antigravity
ANTIGRAVITY_MODEL=gemini-3.6-flash
```

**Option 2: Cloud API Keys (OpenAI / Gemini Public API / Anthropic)**
Routes requests directly to external cloud LLM providers:
```ini
# Choose Provider: openai | gemini | anthropic
LLM_PROVIDER=openai

# OpenAI Credentials
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-4o

# OR Gemini Credentials
GEMINI_API_KEY=AIzaSy...
GEMINI_MODEL=gemini-3.6-flash

# OR Anthropic Credentials
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
```

---

### Step 3: Launch Containers & Apply Migrations

```bash
# Build & start Docker containers
docker compose up -d --build

# Run database migrations (REQUIRED on initial run to create PostgreSQL tables)
docker compose exec backend alembic upgrade head
```

- **Frontend Dashboard**: Open `http://localhost` in your browser.
- **Backend OpenAPI Docs**: Open `http://localhost:8000/docs`.

---

## 🏗️ Architecture & Docker Services

| Service Container | Port Mapping | Network Mode | Description |
|-------------------|--------------|--------------|-------------|
| `reviewai_frontend` | `80:80` | Bridge | Nginx web server serving Angular SPA UI |
| `reviewai_backend` | `8000:8000` | Host | FastAPI server + LangGraph workflow runner |
| `reviewai_bridge` | `8899:8899` | Host | OpenAI-compatible RPC bridge to local Antigravity daemon |
| `reviewai_postgres` | `5432:5432` | Bridge / Host | PostgreSQL 16 relational database |
| `reviewai_redis` | `6379:6379` | Bridge / Host | Redis 7 pub/sub for SSE progress events |

---

## 🔍 Diagnostics & Health Checks

```bash
# View backend structured logs
docker compose logs -f backend

# View bridge daemon discovery logs
docker compose logs -f antigravity-bridge

# Run automated unit test suite
docker compose exec -e PYTHONPATH=. backend pytest
```

---

## 📄 License & Documentation

- [System Architecture Specification](file:///home/pradeep/project/review-ai/ARCHITECTURE.md)
- [Antigravity Local LLM Bridge Manual](file:///home/pradeep/project/review-ai/antigravity-bridge/README.md)
- [Bridge Technical Specification](file:///home/pradeep/project/review-ai/docs/ANTIGRAVITY_BRIDGE.md)
