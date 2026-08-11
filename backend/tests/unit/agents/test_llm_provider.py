import unittest
import os
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from app.agents.llm_provider import get_llm_provider, OpenAIProvider, AntigravityProvider, GeminiProvider, AnthropicProvider, LLMResponse


class TestLLMProvider(unittest.TestCase):
    
    @patch.dict(os.environ, {"LLM_PROVIDER": "openai"})
    def test_get_llm_provider_openai(self):
        provider = get_llm_provider()
        self.assertIsInstance(provider, OpenAIProvider)

    @patch.dict(os.environ, {"LLM_PROVIDER": "antigravity"})
    def test_get_llm_provider_antigravity(self):
        provider = get_llm_provider()
        self.assertIsInstance(provider, AntigravityProvider)

    @patch.dict(os.environ, {"LLM_PROVIDER": "gemini"})
    def test_get_llm_provider_gemini(self):
        provider = get_llm_provider()
        self.assertIsInstance(provider, GeminiProvider)

    @patch.dict(os.environ, {"LLM_PROVIDER": "anthropic"})
    def test_get_llm_provider_anthropic(self):
        provider = get_llm_provider()
        self.assertIsInstance(provider, AnthropicProvider)

    @patch.dict(os.environ, {"LLM_PROVIDER": "unknown"})
    def test_get_llm_provider_unknown(self):
        with self.assertRaises(ValueError) as ctx:
            get_llm_provider()
        self.assertIn("Unknown LLM_PROVIDER", str(ctx.exception))

    @patch("httpx.AsyncClient.post")
    def test_antigravity_invoke_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"test": "success"}'}}],
            "model": "gemini-3.6-flash",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        }
        mock_post.return_value = mock_response

        provider = AntigravityProvider()

        async def run_test():
            resp = await provider.invoke("system", "user", json_mode=True)
            self.assertEqual(resp.content, '{"test": "success"}')
            self.assertEqual(resp.provider, "antigravity")
            self.assertTrue(resp.usage_available)
            self.assertIsNone(resp.error)

        asyncio.run(run_test())

    @patch("httpx.AsyncClient.post", side_effect=Exception("Connection refused"))
    def test_antigravity_invoke_unreachable(self, mock_post):
        provider = AntigravityProvider()

        async def run_test():
            resp = await provider.invoke("system", "user")
            self.assertEqual(resp.provider, "antigravity")
            self.assertIn("Antigravity local bridge error", resp.error)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
