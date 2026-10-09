from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from config import load_settings
from llm.openai_compatible import OpenAICompatibleLLM
from llm.budget import ContextBudget, ContextBudgetError


class LLMConfigurationTest(unittest.TestCase):
    def test_timeout_can_be_configured(self) -> None:
        with patch.dict(os.environ, {"LLM_TIMEOUT_SECONDS": "75"}, clear=False):
            self.assertEqual(load_settings().llm_timeout_seconds, 75)


class OpenAICompatibleLLMTest(unittest.IsolatedAsyncioTestCase):
    async def test_total_timeout_is_not_extended_by_regular_keepalive_chunks(self) -> None:
        class KeepAliveStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                for _ in range(30):
                    await asyncio.sleep(0.01)
                    yield b"\n"
                yield b'{"choices":[{"finish_reason":"stop","message":{"content":"late"}}]}'

        transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=KeepAliveStream()))
        client = httpx.AsyncClient(transport=transport)
        llm = OpenAICompatibleLLM("test", "https://example.test", "key", timeout=0.05)
        started = time.monotonic()
        with patch("llm.openai_compatible.httpx.AsyncClient", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "大模型响应超时"):
                await llm.chat([{"role": "user", "content": "hi"}])
        self.assertLess(time.monotonic() - started, 0.25)
        self.assertIsNone(llm.last_usage)
        self.assertIsNone(llm.last_finish_reason)

    async def test_external_cancellation_is_not_reported_as_provider_timeout(self) -> None:
        started = asyncio.Event()

        async def waiting(*args, **kwargs):
            started.set()
            await asyncio.sleep(60)

        client = AsyncMock()
        client.post.side_effect = waiting
        with patch("llm.openai_compatible.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            llm = OpenAICompatibleLLM("test", "https://example.test", "key", timeout=1)
            task = asyncio.create_task(llm.chat([{"role": "user", "content": "hi"}]))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNone(llm.last_usage)

    async def test_output_budget_usage_and_metadata_are_preserved(self) -> None:
        client = AsyncMock()
        client.post.return_value = httpx.Response(200, request=httpx.Request("POST", "https://example.test"),
            json={"choices": [{"finish_reason": "stop", "message": {"content": "answer"}}],
                  "usage": {"prompt_tokens": 42, "completion_tokens": 7, "total_tokens": 49}})
        with patch("llm.openai_compatible.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            llm = OpenAICompatibleLLM("test-model", "https://example.test", "SECRET",
                budget=ContextBudget(8192, 4000, 2048, 512), reasoning_effort="none")
            self.assertEqual(await llm.chat([{"role": "user", "content": "hi"}]), "answer")
            sent = client.post.call_args.kwargs["json"]
            self.assertEqual(sent["max_tokens"], 2048)
            self.assertEqual(sent["reasoning_effort"], "none")
            self.assertEqual(llm.call_metadata()["usage"]["total_tokens"], 49)
            self.assertNotIn("SECRET", str(llm.call_metadata()))

    async def test_truncated_output_is_rejected_but_usage_remains(self) -> None:
        client = AsyncMock()
        client.post.return_value = httpx.Response(200, request=httpx.Request("POST", "https://example.test"),
            json={"choices": [{"finish_reason": "length", "message": {"content": '{"action":'}}],
                  "usage": {"prompt_tokens": 42, "completion_tokens": 8}})
        with patch("llm.openai_compatible.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            llm = OpenAICompatibleLLM("test", "https://example.test", "key")
            with self.assertRaisesRegex(RuntimeError, "截断"):
                await llm.chat([{"role": "user", "content": "hi"}])
            self.assertEqual(llm.last_usage["completion_tokens"], 8)
            self.assertEqual(llm.last_finish_reason, "length")

    async def test_budget_overflow_never_sends_http_and_clears_stale_usage(self) -> None:
        llm = OpenAICompatibleLLM("test", "https://example.test", "key", budget=ContextBudget(8192, 4000, 2048, 512))
        llm.last_usage = {"prompt_tokens": 999}
        with patch("llm.openai_compatible.httpx.AsyncClient") as factory:
            with self.assertRaises(ContextBudgetError):
                await llm.chat([{"role": "user", "content": "x" * 5000}])
            factory.assert_not_called()
            self.assertIsNone(llm.last_usage)

    async def test_malformed_provider_response_fails_explicitly(self) -> None:
        for data in ([], {"choices": []}, {"choices": [None]}, {"choices": [{"message": None}]}):
            client = AsyncMock()
            client.post.return_value = httpx.Response(200, request=httpx.Request("POST", "https://example.test"), json=data)
            with patch("llm.openai_compatible.httpx.AsyncClient") as factory:
                factory.return_value.__aenter__.return_value = client
                with self.assertRaisesRegex(RuntimeError, "格式不正确"):
                    await OpenAICompatibleLLM("test", "https://example.test", "key").chat([{"role": "user", "content": "hi"}])

    async def test_malformed_http_error_keeps_status_and_readable_error(self) -> None:
        for data in ([], {"error": "provider unavailable"}):
            client = AsyncMock()
            client.post.return_value = httpx.Response(503, request=httpx.Request("POST", "https://example.test"), json=data)
            with patch("llm.openai_compatible.httpx.AsyncClient") as factory:
                factory.return_value.__aenter__.return_value = client
                with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                    await OpenAICompatibleLLM("test", "https://example.test", "key").chat([{"role": "user", "content": "hi"}])

    async def test_timeout_has_readable_chinese_message(self) -> None:
        client = AsyncMock()
        client.post.side_effect = httpx.ReadTimeout("request timed out")

        with patch("llm.openai_compatible.httpx.AsyncClient") as client_class:
            client_class.return_value.__aenter__.return_value = client
            llm = OpenAICompatibleLLM(
                model="test-model",
                base_url="https://example.test",
                api_key="test-key",
                timeout=12,
            )

            with self.assertRaisesRegex(RuntimeError, "大模型响应超时.*12 秒"):
                await llm.chat([{"role": "user", "content": "hello"}])

    async def test_http_error_includes_provider_message(self) -> None:
        request = httpx.Request("POST", "https://example.test/chat/completions")
        response = httpx.Response(
            401,
            request=request,
            json={"error": {"message": "invalid api key"}},
        )
        client = AsyncMock()
        client.post.return_value = response

        with patch("llm.openai_compatible.httpx.AsyncClient") as client_class:
            client_class.return_value.__aenter__.return_value = client
            llm = OpenAICompatibleLLM(
                model="test-model",
                base_url="https://example.test",
                api_key="test-key",
            )

            with self.assertRaisesRegex(RuntimeError, "HTTP 401.*invalid api key"):
                await llm.chat([{"role": "user", "content": "hello"}])
