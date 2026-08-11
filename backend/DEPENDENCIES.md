# ReviewAI Dependencies

This document outlines the core dependencies used in the ReviewAI backend project, explaining their purpose, how they are utilized, and why they were chosen.

## 1. Core Web Framework

### `fastapi` & `uvicorn`
- **Why**: FastAPI is a modern, highly performant web framework for building APIs with Python. It provides automatic OpenAPI documentation and built-in type validation. Uvicorn is the lightning-fast ASGI server that runs the FastAPI application.
- **How**: Used to expose REST endpoints (like `/api/v1/reviews/start`) and Server-Sent Events (SSE) endpoints (like `/api/v1/reviews/stream`) to the frontend application.

## 2. AI Orchestration & LLM SDKs

### `langgraph`
- **Why**: LangGraph is an extension of LangChain used to build stateful, multi-actor applications using directed cyclic/acyclic graphs. It is perfect for complex agentic workflows where state needs to be maintained across multiple steps.
- **How**: Used in `app/agents/workflow.py` to define the 10-node pipeline (PR fetch, Jira fetch, and 8 distinct AI agents). The state (`ReviewState`) is passed and updated at each node.

### `langchain-openai` & `langchain-anthropic`
- **Why**: These are the official LangChain integration packages for OpenAI (GPT-4o, etc.) and Anthropic (Claude 3.5 Sonnet).
- **How**: Instantiated in `BaseAgent` (`app/agents/base_agent.py`) to provide a unified interface for invoking LLMs, formatting system/user prompts, and parsing JSON responses from the models.

## 3. Data Validation & Configuration

### `pydantic` & `pydantic-settings`
- **Why**: Pydantic provides data validation and settings management using Python type annotations. It enforces strict typing and parsing.
- **How**: 
  - Validates environment variables and secrets (like API keys) in `app/core/config.py`.
  - Defines the structured output formats for the AI agents (e.g., `SqlPerformanceIssue`, `ExtractedRequirements`) to guarantee the LLM returns well-formed JSON that the application can safely consume.

## 4. HTTP Clients & Networking

### `httpx`
- **Why**: An asynchronous HTTP client for Python 3. Unlike `requests`, `httpx` natively supports `asyncio`, which is critical for a high-concurrency FastAPI application.
- **How**: Used in `BitbucketService` and `JiraService` to make non-blocking, asynchronous REST API calls to Atlassian Cloud for fetching PR diffs, commits, and Jira issue descriptions.

## 5. Caching & Message Brokering

### `redis` & `hiredis`
- **Why**: Redis is an in-memory data structure store used for caching and Pub/Sub messaging. `hiredis` is a C library that speeds up Redis parsing.
- **How**: Used heavily in the application for real-time progress tracking. When LangGraph progresses to a new agent, a callback publishes a log entry to a Redis Pub/Sub channel. The FastAPI SSE endpoint subscribes to this channel to stream live updates to the frontend dashboard.

## 6. Database & ORM (Future-Proofing / Persistence)

### `sqlalchemy[asyncio]`, `alembic`, `asyncpg`
- **Why**: SQLAlchemy is the standard Python ORM. `asyncpg` is a fast asynchronous PostgreSQL driver. Alembic handles database migrations.
- **How**: Structured to persist review histories, user configurations, and historical metrics to a PostgreSQL database, allowing users to view past reviews and track codebase health over time.

## 7. Task Queues

### `celery` & `kombu`
- **Why**: Celery is a distributed task queue system. Pull request reviews can take several minutes due to rate limits and large LLM context windows, so they cannot block standard HTTP request threads.
- **How**: Used to offload the LangGraph workflow execution to background worker processes, freeing up the FastAPI server to respond immediately to incoming HTTP requests.

## 8. Testing & Quality Assurance

### `pytest`, `pytest-asyncio`, `pytest-cov`
- **Why**: Pytest is the industry standard for Python testing. The asyncio plugin allows for native testing of async functions.
- **How**: Used extensively in the `tests/` directory to mock Bitbucket/Jira API responses and assert that the workflow graph executes correctly and safely handles edge cases (like incomplete PR diffs).
