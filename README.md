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

## 🛠️ How to Run on Different Servers / Environments

---

### Scenario A: Production On-Prem / Local Server with Antigravity Bridge (Zero API Cost)

Use this setup on your local workstation or local Linux server where Antigravity is logged in with your Google account.

#### Step 1: Clone Repository & Configure Environment
```bash
git clone https://github.com/your-org/review-ai.git
cd review-ai

# Copy environment template
cp backend/.env.example backend/.env
```

#### Step 2: Configure `backend/.env`
Edit `backend/.env` to configure your tokens:
```ini
# Application & Database
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://reviewai:reviewai_pass@127.0.0.1:5432/reviewai
REDIS_URL=redis://127.0.0.1:6379/0

# LLM Provider Configuration
LLM_PROVIDER=antigravity
ANTIGRAVITY_MODEL=gemini-3.6-flash
ALLOW_LLM_FALLBACK=false

# Bitbucket Integration
BITBUCKET_USERNAME=your_username
BITBUCKET_ACCESS_TOKEN=your_bitbucket_app_password
BITBUCKET_WORKSPACE=your_workspace_slug

# Jira Integration
JIRA_BASE_URL=https://your-org.atlassian.net
JIRA_EMAIL=you@company.com
JIRA_API_TOKEN=your_jira_api_token

# Encryption Key (Generate via: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
ENCRYPTION_KEY=xCcfce12MskAaHuyMHcbGm0BKrw3y7cK1hM5UHUvTUA=
```

#### Step 3: Launch Services with Antigravity Bridge Profile
```bash
# Start PostgreSQL, Redis, Antigravity Bridge, and Backend using host networking mode
docker compose --profile bridge up -d --build
```

#### Step 4: Apply Database Migrations
```bash
docker compose exec backend alembic upgrade head
```

#### Step 5: Verify Deployment
- **Frontend Dashboard**: Open `http://<SERVER_IP>` in your browser.
- **Backend OpenAPI Docs**: Open `http://<SERVER_IP>:8000/docs`.
- **Bridge Health Check**: Run `curl http://localhost:8899/health`.

---

### Scenario B: Cloud Server Deployment with Cloud API Keys (AWS / GCP / Azure)

Use this setup on standard cloud virtual machines (EC2, Compute Engine, droplets) where you connect via OpenAI, Gemini Public API, or Anthropic.

#### Step 1: Configure `backend/.env` for Cloud LLM
```ini
# Choose your preferred cloud provider
LLM_PROVIDER=openai   # Options: openai | gemini | anthropic

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

#### Step 2: Start Containers
```bash
docker compose up -d --build
docker compose exec backend alembic upgrade head
```

---

### Scenario C: Local Development Mode (Hot Reloading)

Use this mode when developing new agents, modifying FastAPI endpoints, or extending Angular components.

#### 1. Start Support Infrastructure (DB & Redis)
```bash
docker compose up -d postgres redis
```

#### 2. Start Backend Locally
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run migrations & start dev server
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

#### 3. Start Frontend Locally
```bash
cd frontend
npm install
npm start
# Opens http://localhost:4200 with hot-module reload
```

---

## 🏗️ Architecture & Docker Services Summary

| Service Container | Port Mapping | Network Mode | Description |
|-------------------|--------------|--------------|-------------|
| `reviewai_frontend` | `80:80` | Bridge | Nginx web server serving Angular SPA UI |
| `reviewai_backend` | `8000:8000` | Host | FastAPI server + LangGraph workflow runner |
| `reviewai_bridge` | `8899:8899` | Host | OpenAI-compatible RPC bridge to local Antigravity daemon |
| `reviewai_postgres` | `5432:5432` | Bridge / Host | PostgreSQL 16 relational database |
| `reviewai_redis` | `6379:6379` | Bridge / Host | Redis 7 pub/sub for SSE progress events |

---

## 🔍 Diagnostics & Health Checks

### Check System Logs
```bash
# View backend structured logs
docker compose logs -f backend

# View bridge daemon discovery logs
docker compose logs -f antigravity-bridge

# View raw JSONL audit logs for specific reviews
cat /home/pradeep/ai-logs/<REVIEW_ID>.log
```

### Run Automated Unit Tests
```bash
docker exec -e PYTHONPATH=. reviewai_backend pytest -v
```

---

## 📄 License & Documentation

- [System Architecture Specification](file:///home/pradeep/project/review-ai/ARCHITECTURE.md)
- [Antigravity Local LLM Bridge Manual](file:///home/pradeep/project/review-ai/antigravity-bridge/README.md)
- [Bridge Technical Specification](file:///home/pradeep/project/review-ai/docs/ANTIGRAVITY_BRIDGE.md)
