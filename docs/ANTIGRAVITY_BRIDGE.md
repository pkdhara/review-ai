# Antigravity Bridge Architecture & Specification

> Technical reference guide for the Antigravity Local LLM Bridge integration in ReviewAI.

---

## Architecture Overview

The **Antigravity Bridge** enables local applications to perform LLM inferences through an authenticated local Google account session established by the host Antigravity IDE application.

```
+-------------------------------------------------------------------+
|                           HOST MACHINE                            |
|                                                                   |
|  +-------------------------------------------------------------+  |
|  | Antigravity Language Server (language_server_linux_x64)    |  |
|  | - Authenticated Google Account Session                      |  |
|  | - Port: Dynamic HTTPS (e.g. 35105)                          |  |
|  | - Protected by dynamic CSRF Token                           |  |
|  +------------------------------▲------------------------------+  |
|                                 |                                 |
|                                 | Connect-RPC over HTTPS          |
|                                 | Header: x-codeium-csrf-token    |
|                                 |                                 |
|  +------------------------------┴------------------------------+  |
|  | Antigravity Bridge Service (reviewai_bridge)               |  |
|  | - FastAPI Server on 127.0.0.1:8899                          |  |
|  | - Translates OpenAI POST /v1/chat/completions -> Connect-RPC |  |
|  | - Network Mode: host | PID Mode: host                       |  |
|  +------------------------------▲------------------------------+  |
|                                 |                                 |
|                                 | HTTP POST                       |
|                                 | http://127.0.0.1:8899           |
|                                 |                                 |
|  +------------------------------┴------------------------------+  |
|  | ReviewAI Backend Container (reviewai_backend)               |  |
|  | - LangGraph Multi-Agent Pipeline                           |  |
|  | - LLM_PROVIDER=antigravity                                  |  |
|  | - Network Mode: host                                        |  |
|  +-------------------------------------------------------------+  |
+-------------------------------------------------------------------+
```

---

## When the Bridge is Used

1. **ReviewAI Multi-Agent Analysis**: During PR automated reviews, all 6 parallel agents (`code_quality`, `security`, `sql_performance`, `refactoring`, `test_coverage`, `requirement_extraction`) issue prompts via `AntigravityProvider`.
2. **Local Testing & Continuous Integration**: When developers want to run full agentic reviews without consuming cloud API credits or facing API quota exhaustion.

---

## Key Security & Reliability Constraints

1. **Zero Credential Persistence**: OAuth tokens and account credentials are never stored, logged, or extracted. Requests inherit context strictly from the active host daemon.
2. **Loopback Binding**: The bridge binds exclusively to `127.0.0.1:8899` to ensure zero external network exposure.
3. **Explicit Error Classification**: If the local bridge is unreachable, `AntigravityProvider` raises an explicit provider invocation error rather than silently falling back to public free-tier Gemini API keys (when `ALLOW_LLM_FALLBACK=false`).
