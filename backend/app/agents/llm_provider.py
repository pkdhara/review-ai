import abc
import json
import time
import subprocess
import os
import asyncio
from typing import Any, Dict, Optional
from pydantic import BaseModel
from app.core.config import settings


class LLMResponse(BaseModel):
    content: str
    provider: str
    model: str
    duration_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: Optional[int] = None
    usage_available: bool = True
    estimated_cost: Optional[float] = None
    error: Optional[str] = None


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    async def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.05,
        json_mode: bool = False,
        **kwargs
    ) -> LLMResponse:
        pass


class OpenAIProvider(LLMProvider):
    def __init__(self, ai_provider: str = "openai", ai_key: str = ""):
        self.ai_provider = ai_provider
        self.ai_key = ai_key

    async def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.05,
        json_mode: bool = False,
        **kwargs
    ) -> LLMResponse:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
        
        t0 = time.monotonic()
        env_model = getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")
        target_model = kwargs.get("model") or getattr(settings, "model", env_model)
        llm_kwargs = {
            "model": target_model,
            "temperature": temperature,
            "api_key": self.ai_key or getattr(settings, "OPENAI_API_KEY", ""),
            "timeout": 120,
        }
        if json_mode:
            llm_kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        llm = ChatOpenAI(**llm_kwargs)

        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        
        try:
            response = await llm.ainvoke(messages)
            return self._parse_response(response, target_model, system_prompt, user_prompt, t0, getattr(llm, "model_name", target_model))
        except Exception as e:
            return self._error_response(e, target_model, t0)
            
    def _parse_response(self, response, target_model, system_prompt, user_prompt, t0, model_name):
        usage_meta = getattr(response, "usage_metadata", None) or {}
        resp_meta = getattr(response, "response_metadata", None) or {}
        token_usage = resp_meta.get("token_usage") or resp_meta.get("usage") or {}

        input_tokens = usage_meta.get("input_tokens") or token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0
        output_tokens = usage_meta.get("output_tokens") or token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
        total_tokens = usage_meta.get("total_tokens") or token_usage.get("total_tokens") or (input_tokens + output_tokens)

        cached_input_tokens = None
        if isinstance(usage_meta.get("input_token_details"), dict):
            cached_input_tokens = usage_meta["input_token_details"].get("cache_read")
        elif "cache_read_input_tokens" in token_usage:
            cached_input_tokens = token_usage.get("cache_read_input_tokens")

        return LLMResponse(
            content=response.content,
            provider=self.ai_provider,
            model=model_name,
            duration_ms=int((time.monotonic() - t0) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_input_tokens,
            usage_available=True,
        )

    def _error_response(self, e, target_model, t0):
        return LLMResponse(
            content="",
            provider=self.ai_provider,
            model=target_model,
            duration_ms=int((time.monotonic() - t0) * 1000),
            error=str(e)
        )


class AnthropicProvider(OpenAIProvider):
    async def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.05,
        json_mode: bool = False,
        **kwargs
    ) -> LLMResponse:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_anthropic import ChatAnthropic
        
        t0 = time.monotonic()
        env_model = getattr(settings, "ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
        target_model = kwargs.get("model") or getattr(settings, "anthropic_model", env_model)
        if "claude-sonnet-4-5" in target_model:
            target_model = "claude-3-5-sonnet-20241022"
            
        llm = ChatAnthropic(
            model=target_model,
            temperature=temperature,
            api_key=self.ai_key or getattr(settings, "ANTHROPIC_API_KEY", ""),
            timeout=120,
            max_tokens=8192,
        )
        
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        
        try:
            response = await llm.ainvoke(messages)
            return self._parse_response(response, target_model, system_prompt, user_prompt, t0, getattr(llm, "model", target_model))
        except Exception as e:
            return self._error_response(e, target_model, t0)


class GeminiProvider(OpenAIProvider):
    async def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.05,
        json_mode: bool = False,
        **kwargs
    ) -> LLMResponse:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_google_genai import ChatGoogleGenerativeAI
        
        t0 = time.monotonic()
        env_model = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
        target_model = kwargs.get("model") or getattr(settings, "gemini_model", env_model)
        key = self.ai_key or getattr(settings, "GEMINI_API_KEY", "") or getattr(settings, "GOOGLE_API_KEY", "")
        
        llm = ChatGoogleGenerativeAI(
            model=target_model,
            temperature=temperature,
            google_api_key=key,
            timeout=120,
        )
        
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        
        try:
            response = await llm.ainvoke(messages)
            return self._parse_response(response, target_model, system_prompt, user_prompt, t0, getattr(llm, "model", target_model))
        except Exception as e:
            return self._error_response(e, target_model, t0)


class AntigravityProvider(LLMProvider):
    def __init__(self, worktree_path: str = None):
        self.model = os.environ.get("ANTIGRAVITY_MODEL", "gemini-3.6-flash")
        self.timeout = int(os.environ.get("ANTIGRAVITY_TIMEOUT_SECONDS", "120"))
        self.worktree_path = worktree_path

    async def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.05,
        json_mode: bool = False,
        **kwargs
    ) -> LLMResponse:
        t0 = time.monotonic()
        full_prompt = f"System Instruction:\n{system_prompt}\n\nUser:\n{user_prompt}"
        if json_mode:
            full_prompt += "\n\nCRITICAL: Return ONLY valid JSON."

        import httpx
        bridge_urls = [
            "http://127.0.0.1:8899/v1/chat/completions",
            "http://localhost:8899/v1/chat/completions",
            "http://host.docker.internal:8899/v1/chat/completions"
        ]
        
        last_error_msg = ""
        for bridge_url in bridge_urls:
            try:
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": temperature,
                    "stream": False
                }
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(bridge_url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"]
                        returned_model = data.get("model", self.model)
                        return LLMResponse(
                            content=content,
                            provider="antigravity",
                            model=returned_model,
                            duration_ms=int((time.monotonic() - t0) * 1000),
                            usage_available=True,
                            input_tokens=data.get("usage", {}).get("prompt_tokens", len(full_prompt) // 4),
                            output_tokens=data.get("usage", {}).get("completion_tokens", len(content) // 4),
                            total_tokens=data.get("usage", {}).get("total_tokens", (len(full_prompt) + len(content)) // 4)
                        )
                    else:
                        last_error_msg = f"HTTP {resp.status_code}: {resp.text}"
            except Exception as e:
                last_error_msg = str(e)

        # Do NOT silently fall back to Gemini API key when antigravity is explicitly requested
        allow_fallback = os.environ.get("ALLOW_LLM_FALLBACK", "false").strip().lower() == "true"
        if allow_fallback:
            gemini_key = getattr(settings, "GEMINI_API_KEY", "") or getattr(settings, "GOOGLE_API_KEY", "")
            if gemini_key:
                return await GeminiProvider(ai_provider="gemini", ai_key=gemini_key).invoke(
                    system_prompt=system_prompt, user_prompt=user_prompt, temperature=temperature, json_mode=json_mode, **kwargs
                )

        return LLMResponse(
            content="",
            provider="antigravity",
            model=self.model,
            duration_ms=int((time.monotonic() - t0) * 1000),
            error=f"Antigravity local bridge error (endpoint unreachable): {last_error_msg}"
        )


def get_llm_provider(ai_provider: str = "", ai_key: str = "", worktree_path: str = None) -> LLMProvider:
    # Use LLM_PROVIDER env var if set, otherwise fallback to ai_provider parameter or default to openai
    env_provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    provider_type = env_provider if env_provider else (ai_provider.lower() if ai_provider else "openai")
    
    if provider_type == "antigravity":
        return AntigravityProvider(worktree_path=worktree_path)
    elif provider_type in ("gemini", "google"):
        return GeminiProvider(ai_provider=provider_type, ai_key=ai_key)
    elif provider_type == "anthropic":
        return AnthropicProvider(ai_provider=provider_type, ai_key=ai_key)
    elif provider_type == "openai":
        return OpenAIProvider(ai_provider=provider_type, ai_key=ai_key)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider_type}")
