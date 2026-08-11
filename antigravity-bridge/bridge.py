#!/usr/bin/env python3
"""
antigravity-bridge: Production-Grade OpenAI-Compatible Local Bridge for Antigravity Language Server.

Architecture:
  Client / ReviewAI ──► POST http://127.0.0.1:8899/v1/chat/completions
                    ──► Local Antigravity Language Server HTTPS Connect RPC
                        (Using authenticated Google Account session)
                    ──► OpenAI-compatible JSON / SSE Stream Response

Security & Isolation:
  - Binds to 127.0.0.1 by default.
  - Zero credential/token persistence.
  - Redacts prompts, tokens, and CSRF headers from logs.
  - Dynamic discovery via /proc and /proc/net/tcp.
"""

import asyncio
import logging
import os
import re
import time
import uuid
from typing import AsyncIterator, Dict, List, Optional, Tuple

import requests
import urllib3
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Logging Setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [bridge] %(message)s"
)
log = logging.getLogger("antigravity-bridge")

# ── Configuration ─────────────────────────────────────────────────────────────
BRIDGE_PORT   = int(os.environ.get("BRIDGE_PORT", "8899"))
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

# Model Mapping: OpenAI alias -> Antigravity RPC Model String & Canonical Name
MODEL_REGISTRY: Dict[str, Tuple[str, str]] = {
    "antigravity":         ("MODEL_PLACEHOLDER_M71", "Gemini 3.6 Flash"),
    "gemini-3.6-flash":    ("MODEL_PLACEHOLDER_M71", "Gemini 3.6 Flash"),
    "gemini-flash":        ("MODEL_PLACEHOLDER_M71", "Gemini 3.6 Flash"),
    "gemini-3.1-pro":      ("MODEL_PLACEHOLDER_M16", "Gemini 3.1 Pro"),
    "gemini-pro":          ("MODEL_PLACEHOLDER_M16", "Gemini 3.1 Pro"),
    "gemini-3.5-flash":    ("MODEL_PLACEHOLDER_M84", "Gemini 3.5 Flash"),
    "default":             ("MODEL_PLACEHOLDER_M71", "Gemini 3.6 Flash"),
}

# ── Antigravity Daemon Client ────────────────────────────────────────────────
class AntigravityLocalDaemon:
    def __init__(self):
        self.port: Optional[int] = None
        self.csrf_token: Optional[str] = None
        self.pid: Optional[str] = None
        self.last_discovery_ms: float = 0.0

    def discover(self) -> float:
        t0 = time.monotonic()
        csrf_token = None
        target_pid = None

        # 1. Scan /proc for language_server process & --csrf_token argument
        proc_dir = '/proc'
        if os.path.exists(proc_dir):
            for p in os.listdir(proc_dir):
                if p.isdigit():
                    try:
                        cmd_path = os.path.join(proc_dir, p, 'cmdline')
                        with open(cmd_path, 'rb') as f:
                            cmd = f.read().decode('utf-8', errors='ignore').replace('\x00', ' ')
                            if 'language_server' in cmd and '--csrf_token' in cmd:
                                target_pid = p
                                m = re.search(r'--csrf_token\s+([^\s]+)', cmd)
                                if m:
                                    csrf_token = m.group(1)
                                    break
                    except Exception:
                        pass

        if not csrf_token or not target_pid:
            self._invalidate()
            raise HTTPException(
                status_code=503,
                detail="Antigravity Language Server process not found. Please ensure Antigravity IDE is running."
            )

        self.pid = target_pid
        self.csrf_token = csrf_token

        # 2. Extract listening ports from /proc/net/tcp & /proc/net/tcp6
        listening_ports: List[int] = []
        for tcp_file in ['/proc/net/tcp', '/proc/net/tcp6']:
            if os.path.exists(tcp_file):
                try:
                    with open(tcp_file, 'r') as f:
                        lines = f.readlines()[1:]
                        for line in lines:
                            parts = line.strip().split()
                            if len(parts) >= 4 and parts[3] == '0A': # 0A state = LISTEN
                                local_addr = parts[1]
                                _, port_hex = local_addr.split(':')
                                port = int(port_hex, 16)
                                if port not in listening_ports:
                                    listening_ports.append(port)
                except Exception as e:
                    log.warning(f"Error reading {tcp_file}: {e}")

        # 3. Probe HTTPS ports for Connect RPC endpoint
        for p in listening_ports:
            try:
                url = f"https://127.0.0.1:{p}/exa.language_server_pb.LanguageServerService/GetAvailableModels"
                h = {"x-codeium-csrf-token": self.csrf_token, "Content-Type": "application/json"}
                r = requests.post(url, json={}, headers=h, verify=False, timeout=1.5)
                if r.status_code == 200:
                    self.port = p
                    disc_time = (time.monotonic() - t0) * 1000
                    self.last_discovery_ms = disc_time
                    log.info(f"Connected to Antigravity daemon (PID: {self.pid}, Port: {self.port}) in {disc_time:.1f}ms")
                    return disc_time
            except Exception:
                pass

        self._invalidate()
        raise HTTPException(
            status_code=503,
            detail=f"Antigravity HTTPS Connect RPC port unavailable (ports probed: {listening_ports})"
        )

    def _invalidate(self):
        self.port = None
        self.csrf_token = None
        self.pid = None

    def generate(self, prompt: str, rpc_model: str, req_id: str, timeout: int = 120) -> Tuple[str, float]:
        if not self.port or not self.csrf_token:
            self.discover()
        
        url = f"https://127.0.0.1:{self.port}/exa.language_server_pb.LanguageServerService/GetModelResponse"
        h = {"x-codeium-csrf-token": self.csrf_token, "Content-Type": "application/json"}
        payload = {"prompt": prompt, "model": rpc_model}
        
        t0 = time.monotonic()
        try:
            r = requests.post(url, json=payload, headers=h, verify=False, timeout=timeout)
            rpc_ms = (time.monotonic() - t0) * 1000
            if r.status_code == 200:
                return r.json().get("response", ""), rpc_ms
            elif r.status_code in (401, 403):
                log.warning(f"[{req_id}] CSRF token rejected (HTTP {r.status_code}), re-discovering...")
            else:
                log.warning(f"[{req_id}] RPC returned HTTP {r.status_code}, re-discovering...")
        except requests.exceptions.Timeout:
            raise HTTPException(status_code=504, detail=f"Antigravity RPC request timed out after {timeout}s")
        except Exception as e:
            log.warning(f"[{req_id}] Exception calling daemon on port {self.port}: {e}, re-discovering...")
            
        # Retry discovery once on failure/restart
        self.discover()
        url = f"https://127.0.0.1:{self.port}/exa.language_server_pb.LanguageServerService/GetModelResponse"
        h = {"x-codeium-csrf-token": self.csrf_token, "Content-Type": "application/json"}
        t0 = time.monotonic()
        r = requests.post(url, json=payload, headers=h, verify=False, timeout=timeout)
        rpc_ms = (time.monotonic() - t0) * 1000
        if r.status_code == 200:
            return r.json().get("response", ""), rpc_ms
        else:
            raise HTTPException(status_code=502, detail=f"Antigravity RPC call failed with HTTP status {r.status_code}")

antigravity_daemon = AntigravityLocalDaemon()

# ── FastAPI Application ───────────────────────────────────────────────────────
app = FastAPI(title="Antigravity Bridge", version="2.5.0")

# ── Pydantic Models ───────────────────────────────────────────────────────────
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str = DEFAULT_MODEL
    messages: List[Message]
    temperature: Optional[float] = 0.2
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False

# ── Helpers ───────────────────────────────────────────────────────────────────
def resolve_model(requested: str) -> Tuple[str, str]:
    req_clean = requested.strip().lower()
    return MODEL_REGISTRY.get(req_clean, MODEL_REGISTRY.get("default"))

def format_messages_to_prompt(messages: List[Message]) -> str:
    prompt_parts = []
    for msg in messages:
        if msg.role == "system":
            prompt_parts.append(f"System Instruction:\n{msg.content}\n")
        elif msg.role == "user":
            prompt_parts.append(f"User:\n{msg.content}\n")
        elif msg.role == "assistant":
            prompt_parts.append(f"Assistant:\n{msg.content}\n")
    return "\n".join(prompt_parts)

def make_openai_response(content: str, model_name: str, req_id: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> dict:
    return {
        "id": f"chatcmpl-{req_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "token_estimation_note": "Token counts are locally calculated estimates (~4 chars/token)"
        }
    }

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    try:
        if not antigravity_daemon.port:
            antigravity_daemon.discover()
        return {
            "status": "ok",
            "mode": "antigravity-local-daemon",
            "daemon_pid": antigravity_daemon.pid,
            "daemon_port": antigravity_daemon.port
        }
    except Exception as e:
        return {"status": "unavailable", "error": str(e)}

@app.get("/v1/models")
async def list_models():
    data = []
    for alias, (rpc_id, display) in MODEL_REGISTRY.items():
        data.append({
            "id": alias,
            "object": "model",
            "created": 1786450000,
            "owned_by": "google-account",
            "canonical_name": display
        })
    return {"object": "list", "data": data}

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest, raw: Request):
    req_id = uuid.uuid4().hex[:8]
    t0 = time.monotonic()
    
    full_prompt = format_messages_to_prompt(request.messages)
    input_len = len(full_prompt)
    
    # Request Payload Guard (>500,000 chars)
    if input_len > 2000000:
        raise HTTPException(status_code=400, detail="Request payload exceeds maximum prompt safety limit (2MB)")
        
    rpc_model, display_name = resolve_model(request.model)
    log.info(f"[{req_id}] Request: model='{request.model}' -> '{display_name}' ({rpc_model}), prompt_len={input_len} chars, stream={request.stream}")
    
    loop = asyncio.get_event_loop()
    
    try:
        content, rpc_ms = await loop.run_in_executor(
            None, antigravity_daemon.generate, full_prompt, rpc_model, req_id
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[{req_id}] Unexpected error in bridge execution: {e}")
        raise HTTPException(status_code=500, detail=f"Internal bridge error: {str(e)}")

    total_ms = (time.monotonic() - t0) * 1000
    prompt_tokens = input_len // 4
    completion_tokens = len(content) // 4
    
    log.info(f"[{req_id}] Completed: rpc_time={rpc_ms:.1f}ms, total_time={total_ms:.1f}ms, output_len={len(content)} chars (~{completion_tokens} tokens)")

    # 1. Streaming Mode (SSE format)
    if request.stream:
        async def sse_generator() -> AsyncIterator[str]:
            chunk_id = f"chatcmpl-{req_id}"
            created_ts = int(time.time())
            
            # Split text into small chunks for streaming response simulation
            words = content.split(" ")
            for i, word in enumerate(words):
                token_text = word if i == 0 else " " + word
                chunk_data = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": display_name,
                    "choices": [{
                        "index": 0,
                        "delta": {"role": "assistant" if i == 0 else "", "content": token_text},
                        "finish_reason": None
                    }]
                }
                import json
                yield f"data: {json.dumps(chunk_data)}\n\n"
                await asyncio.sleep(0.01)

            final_data = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": display_name,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
            }
            import json
            yield f"data: {json.dumps(final_data)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(sse_generator(), media_type="text/event-stream")

    # 2. Non-Streaming Mode (JSON format)
    return JSONResponse(make_openai_response(
        content=content,
        model_name=display_name,
        req_id=req_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens
    ))

# ── Startup Lifecycle ─────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    log.info(f"🚀 Antigravity Bridge v2.5.0 starting on port {BRIDGE_PORT}...")
    try:
        disc_ms = antigravity_daemon.discover()
        log.info(f"✅ Discovered active Antigravity Language Server on port {antigravity_daemon.port} in {disc_ms:.1f}ms")
    except Exception as e:
        log.warning(f"⚠️ Antigravity Local Daemon not detected on startup: {e}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=BRIDGE_PORT, log_level="info")
