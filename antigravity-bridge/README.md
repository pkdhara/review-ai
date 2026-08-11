# Antigravity Local LLM Bridge

> **OpenAI-Compatible Local RPC Gateway for Local Antigravity/Gemini Daemon**

---

## 1. Overview & Purpose

The **Antigravity Bridge** is a high-performance local proxy service built with FastAPI. It translates standard OpenAI-compatible REST requests (`POST /v1/chat/completions`) into internal Google Connect-RPC calls targeting the locally authenticated Antigravity Language Server daemon (`language_server_linux_x64`).

### Why It Exists
- **Zero API Credits / Cost**: Leverages your existing Google Account login authenticated through Antigravity without requiring separate Gemini API key credits.
- **Quota Exhaustion Bypass**: Eliminates public Gemini API free-tier 429 rate limits (`generativelanguage.googleapis.com` limits of 5 requests/minute).
- **OpenAI Interoperability**: Exposes standard `/v1/chat/completions` endpoints, making it seamlessly compatible with LangChain, LangGraph, and standard HTTP clients.

---

## 2. When to Use

Use the Antigravity Bridge when:
- `LLM_PROVIDER=antigravity` is set in `backend/.env`.
- You are developing or running ReviewAI automated PR reviews locally.
- You want zero-cost, high-throughput LLM generations backed by your local Antigravity authenticated Google session.

---

## 3. Architecture & How It Works

```
┌─────────────────────────┐
│     ReviewAI Backend    │ (Python / LangGraph)
└───────────┬─────────────┘
            │  HTTP POST http://127.0.0.1:8899/v1/chat/completions (OpenAI JSON Payload)
            ▼
┌─────────────────────────┐
│   Antigravity Bridge    │ (FastAPI Daemon on Port 8899)
└───────────┬─────────────┘
            │  1. Daemon Discovery: Scans /proc and /proc/net/tcp
            │  2. Extracts dynamic CSRF token & HTTPS port
            │  3. Formats Connect-RPC payload (GetModelResponse)
            ▼
┌─────────────────────────┐
│  Antigravity Daemon     │ (Host Process: language_server_linux_x64)
└───────────┬─────────────┘
            │  Authenticates using host Google OAuth session
            ▼
┌─────────────────────────┐
│    Google Backend AI    │ (Gemini 3.6 Flash / Pro)
└─────────────────────────┘
```

### Auto-Discovery Protocol
1. **PID & CSRF Token Extraction**: The bridge scans `/proc` to locate the `language_server_linux_x64` PID and parses its command-line arguments to retrieve the active `--csrf_token`.
2. **Dynamic Port Resolution**: Scans `/proc/net/tcp` for open local TCP sockets bound to the daemon PID to identify its dynamic HTTPS port.
3. **Connect-RPC Execution**: Formats requests using protobuf JSON over HTTPS (`https://127.0.0.1:<PORT>/antigravity.v1.AntigravityLanguageServerService/GetModelResponse`) with `x-codeium-csrf-token` headers.

---

## 4. Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /health` | GET | Health check returning daemon PID, HTTPS port, and readiness status |
| `POST /v1/chat/completions` | POST | OpenAI-compatible chat completions endpoint (supports JSON & SSE streaming) |
| `GET /v1/models` | GET | Returns available models (e.g., `gemini-3.6-flash`, `antigravity`) |

### Example Health Check Response
```json
{
  "status": "ok",
  "mode": "antigravity-local-daemon",
  "daemon_pid": "287392",
  "daemon_port": 35105
}
```

---

## 5. Docker & Network Configuration

The bridge container requires access to host process IDs and loopback networking to communicate with the host daemon:

```yaml
  antigravity-bridge:
    build:
      context: ./antigravity-bridge
      dockerfile: Dockerfile
    container_name: reviewai_bridge
    restart: unless-stopped
    network_mode: "host"
    pid: "host"
    environment:
      BRIDGE_PORT: 8899
```

To ensure `reviewai_backend` can connect directly to `http://127.0.0.1:8899`:
- `reviewai_backend` is configured with `network_mode: "host"` in `docker-compose.yml`.

---

## 6. Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `antigravity` | Primary provider selector in `backend/.env` |
| `ANTIGRAVITY_MODEL` | `gemini-3.6-flash` | Model identifier requested via bridge |
| `ALLOW_LLM_FALLBACK` | `false` | When `false`, prevents silent fallback to public Gemini API keys |
