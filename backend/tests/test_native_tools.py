from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from pydantic import ValidationError

from llm.budget import ContextBudget, ContextBudgetError
from llm.openai_compatible import OpenAICompatibleLLM
from llm.tools import parse_native_message, parse_json_reply
from tools.contracts import SearchArguments, tool_definitions


class NativeToolsTest(unittest.IsolatedAsyncioTestCase):
    def message(self):
        return {"content": None, "reasoning_content": "opaque-provider-continuation", "tool_calls": [
            {"id": "provider_1", "type": "function", "function": {"name": "search_scene", "arguments": '{"target_id":"tower"}'}}]}

    async def test_native_request_and_opaque_continuation_are_preserved(self):
        client = AsyncMock()
        client.post.return_value = httpx.Response(200, request=httpx.Request("POST", "https://example.test"),
            json={"choices": [{"finish_reason": "tool_calls", "message": self.message()}], "usage": {"prompt_tokens": 42, "completion_tokens": 9}})
        with patch("llm.openai_compatible.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            llm = OpenAICompatibleLLM("test", "https://example.test", "test-key")
            reply = await llm.chat_tools([{"role": "user", "content": "搜证"}], tool_definitions("role"))
            self.assertEqual(reply.tool_calls[0].arguments, {"target_id": "tower"})
            self.assertEqual(reply.wire_message["reasoning_content"], "opaque-provider-continuation")
            self.assertEqual(llm.last_usage["completion_tokens"], 9)
            history = [{"role": "user", "content": "搜证"}, reply.wire_message,
                       {"role": "tool", "tool_call_id": "provider_1", "content": '{"status":"succeeded"}'}]
            await llm.chat_tools(history, tool_definitions("role"))
            sent = client.post.call_args.kwargs["json"]
            self.assertEqual(sent["messages"][1]["reasoning_content"], "opaque-provider-continuation")
            self.assertEqual(sent["tool_choice"], "auto")
            self.assertFalse(sent["stream"])

    async def test_provider_error_never_automatically_retries(self):
        client = AsyncMock()
        client.post.return_value = httpx.Response(503, request=httpx.Request("POST", "https://example.test"), json={"error": {"message": "unavailable"}})
        with patch("llm.openai_compatible.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            llm = OpenAICompatibleLLM("test", "https://example.test", "key")
            with self.assertRaisesRegex(RuntimeError, "503"):
                await llm.chat_tools([{"role": "user", "content": "hi"}], tool_definitions("role"))
            self.assertEqual(client.post.await_count, 1)
            self.assertIsNone(llm.last_usage)

    async def test_tool_definitions_count_against_input_budget(self):
        llm = OpenAICompatibleLLM("test", "https://example.test", "key", budget=ContextBudget(8192, 1000, 2048, 512))
        with patch("llm.openai_compatible.httpx.AsyncClient") as factory:
            with self.assertRaises(ContextBudgetError):
                await llm.chat_tools([{"role": "user", "content": "hi"}], tool_definitions("role"))
            factory.assert_not_called()
            self.assertFalse(llm.last_provider_invoked)

    def test_malformed_and_duplicate_native_calls_fail_closed(self):
        message = self.message()
        cases = [None, {"content": None}, {**message, "tool_calls": "bad"},
                 {**message, "tool_calls": message["tool_calls"] * 2},
                 {"tool_calls": [{"id": "1", "type": "function", "function": "bad"}]},
                 {"tool_calls": [{"id": "1", "type": "function", "function": {"name": "search_scene", "arguments": "[]"}}]}]
        for value in cases:
            with self.assertRaises((ValueError, ValidationError)):
                parse_native_message(value)

    def test_json_transport_is_explicit_and_schema_checked(self):
        reply = parse_json_reply('{"content":"","tool_calls":[{"name":"search_scene","arguments":{"target_id":"tower"}}]}')
        self.assertEqual(reply.transport, "validated_action_json")
        self.assertIsNone(reply.tool_calls[0].provider_call_id)
        for value in ('{"content":"","tool_calls":[]}', '{"tool_calls":{}}',
                      '{"tool_calls":[{"name":"x","arguments":{},"provider_call_id":"fake"}]}'):
            with self.assertRaises(ValueError):
                parse_json_reply(value)

    def test_runtime_ids_are_not_model_parameters(self):
        self.assertNotIn("game_id", json.dumps(tool_definitions("role")))
        with self.assertRaises(ValidationError):
            SearchArguments(target_id="tower", run_id="forged")
        with self.assertRaises(ValidationError):
            SearchArguments(target_id=" ")
