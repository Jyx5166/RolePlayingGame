from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from llm.base import BaseLLM
from llm.budget import ContextBudget, ContextBudgetError
from llm.tools import ToolModelReply
from backend.verification.blind_budget import (
    BlindBudgetError, BudgetAmbiguityError, BudgetedLLM,
    BudgetedOpenAICompatibleLLM, MoneyRequestLedger, Pricing,
)

CONTEXT = {"script": "blind_case", "phase": "investigation", "actor": "role_a", "purpose": "role_turn"}
MESSAGES = [{"role": "user", "content": "hi"}]


class FakeLLM(BaseLLM):
    supports_native_tools = True
    model = "fake-model"
    provider = "offline_fake"

    def __init__(self, *, usage=None, error: Exception | None = None) -> None:
        self.budget = ContextBudget(1600, 1000, 500, 100)
        self.usage = usage
        self.error = error
        self.calls = 0
        self.started = asyncio.Event()
        self.wait = False

    async def chat(self, messages):
        self.calls += 1
        self.last_provider_invoked = True
        self.started.set()
        if self.wait:
            await asyncio.Event().wait()
        self.last_usage = self.usage
        self.last_finish_reason = "stop"
        if self.error:
            raise self.error
        return "answer"

    async def chat_tools(self, messages, definitions, *, transport="native_tools"):
        await self.chat(messages)
        return ToolModelReply("answer", (), {"role": "assistant", "content": "answer"}, transport)


class BlindBudgetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "requests.json"
        self.pricing = Pricing("1000", "2000", "https://provider.test/pricing", "2026-10-14", "fake-model")

    def ledger(self, **kwargs):
        return MoneyRequestLedger(self.path, self.pricing, **kwargs)

    def disk(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    async def test_reservation_is_persisted_before_provider_dispatch(self):
        ledger = self.ledger()
        delegate = FakeLLM(usage={"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110})
        original = delegate.chat
        async def inspected(messages):
            pending = self.disk()["calls"][0]
            self.assertEqual(pending["status"], "reserved")
            self.assertEqual(Decimal(pending["accounted_upper_cny"]), Decimal("2"))
            return await original(messages)
        delegate.chat = inspected
        llm = BudgetedLLM(delegate, ledger, CONTEXT)
        self.assertEqual(await llm.chat(MESSAGES), "answer")
        self.assertEqual(ledger.accounted_upper_cny, Decimal("0.12"))
        self.assertEqual(llm.call_metadata()["usage"]["total_tokens"], 110)
        self.assertTrue(llm.call_metadata()["provider_invoked"])
        self.assertEqual(self.disk()["calls"][0]["actor"], "role_a")

    async def test_total_cap_and_request_cap_share_across_clients(self):
        ledger = self.ledger(max_cny="3")
        first, second = FakeLLM(), FakeLLM()
        await BudgetedLLM(first, ledger, CONTEXT).chat(MESSAGES)
        with self.assertRaises(BlindBudgetError):
            await BudgetedLLM(second, ledger, CONTEXT).chat_tools(MESSAGES, [])
        self.assertEqual((first.calls, second.calls), (1, 0))
        self.assertEqual(ledger.accounted_upper_cny, Decimal("2"))
        other_path = self.path.with_name("request_cap.json")
        capped = MoneyRequestLedger(other_path, self.pricing, request_limit=1)
        await BudgetedLLM(FakeLLM(), capped, CONTEXT).chat(MESSAGES)
        llm = BudgetedLLM(second, capped, CONTEXT)
        with self.assertRaises(BlindBudgetError):
            await llm.chat(MESSAGES)
        self.assertEqual(second.calls, 0)
        self.assertFalse(llm.call_metadata()["provider_invoked"])

    async def test_tools_are_validated_and_full_limits_reserved(self):
        ledger = self.ledger()
        delegate = FakeLLM()
        llm = BudgetedLLM(delegate, ledger, CONTEXT)
        with self.assertRaises(ContextBudgetError):
            await llm.chat_tools(MESSAGES, [{"description": "x" * 1100}])
        self.assertEqual(delegate.calls, 0)
        self.assertEqual(ledger.calls, [])
        await llm.chat_tools(MESSAGES, [{"description": "valid schema"}])
        row = ledger.calls[0]
        self.assertEqual(row["reserved_input_tokens"], 1000)
        self.assertEqual(Decimal(row["reserved_cny"]), Decimal("2"))
        self.assertGreater(row["estimated_input_tokens"], delegate.budget.validate(MESSAGES))

    async def test_validated_json_tool_transport_does_not_double_reserve(self):
        ledger = self.ledger()
        delegate = FakeLLM()
        llm = BudgetedLLM(delegate, ledger, CONTEXT)
        await llm.chat_tools(MESSAGES, [], transport="validated_action_json")
        self.assertEqual(len(ledger.calls), 1)
        self.assertEqual(delegate.calls, 1)

    async def test_missing_malformed_and_failed_usage_keep_full_reservation(self):
        ledger = self.ledger()
        cases = [None, {"prompt_tokens": 2}, {"prompt_tokens": True, "completion_tokens": 2},
                 {"prompt_tokens": "2", "completion_tokens": 2},
                 {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 5}]
        for usage in cases:
            await BudgetedLLM(FakeLLM(usage=usage), ledger, CONTEXT).chat(MESSAGES)
        failed = FakeLLM(usage={"prompt_tokens": 2, "completion_tokens": 2}, error=RuntimeError("SECRET_API_KEY"))
        with self.assertRaisesRegex(BlindBudgetError, "Provider call failed: RuntimeError") as caught:
            await BudgetedLLM(failed, ledger, CONTEXT).chat(MESSAGES)
        self.assertNotIn("SECRET_API_KEY", str(caught.exception))
        self.assertNotIn("SECRET_API_KEY", self.path.read_text(encoding="utf-8"))
        self.assertEqual(ledger.accounted_upper_cny, Decimal("12"))
        self.assertEqual(failed.calls, 1)

    async def test_cancellation_retains_durable_reservation_and_propagates(self):
        ledger = self.ledger()
        delegate = FakeLLM()
        delegate.wait = True
        task = asyncio.create_task(BudgetedLLM(delegate, ledger, CONTEXT).chat(MESSAGES))
        await delegate.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.disk()["calls"][0]["status"], "canceled")
        self.assertEqual(ledger.accounted_upper_cny, Decimal("2"))

    async def test_usage_exceeding_bound_freezes_future_calls(self):
        ledger = self.ledger()
        delegate = FakeLLM(usage={"prompt_tokens": 1001, "completion_tokens": 1})
        # Even when cost is BELOW full reservation, a token bound violation is ambiguous.
        llm = BudgetedLLM(delegate, ledger, CONTEXT)
        with self.assertRaises(BudgetAmbiguityError):
            await llm.chat(MESSAGES)
        with self.assertRaises(BlindBudgetError):
            await llm.chat_tools(MESSAGES, [])
        self.assertEqual(delegate.calls, 1)
        self.assertEqual(ledger.accounted_upper_cny, Decimal("2"))
        self.assertIsNotNone(self.disk()["frozen_reason"])

    async def test_cost_above_reservation_records_actual_upper_bound(self):
        ledger = self.ledger()
        llm = BudgetedLLM(FakeLLM(usage={"prompt_tokens": 1000, "completion_tokens": 501}), ledger, CONTEXT)
        with self.assertRaises(BudgetAmbiguityError):
            await llm.chat(MESSAGES)
        self.assertEqual(ledger.accounted_upper_cny, Decimal("2.002"))

    async def test_cache_and_reasoning_details_never_reduce_or_double_charge_usage(self):
        ledger = self.ledger()
        usage = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110,
                 "prompt_cache_hit_tokens": 100, "prompt_cache_miss_tokens": 0,
                 "completion_tokens_details": {"reasoning_tokens": 9}}
        await BudgetedLLM(FakeLLM(usage=usage), ledger, CONTEXT).chat(MESSAGES)
        self.assertEqual(ledger.accounted_upper_cny, Decimal("0.12"))
        self.assertEqual(ledger.calls[0]["usage"]["completion_tokens_details.reasoning_tokens"], 9)

    async def test_live_client_configuration_assignments_reach_provider_payload(self):
        ledger = self.ledger()
        llm = BudgetedOpenAICompatibleLLM("fake-model", "https://provider.test", "SECRET_API_KEY",
            ledger=ledger, context=CONTEXT, budget=ContextBudget(1600, 1000, 500, 100))
        llm.reasoning_effort = "none"
        llm.budget = ContextBudget(1600, 1000, 400, 100)
        client = AsyncMock()
        client.post.return_value = httpx.Response(200, request=httpx.Request("POST", "https://provider.test"),
            json={"choices": [{"finish_reason": "stop", "message": {"content": "answer"}}],
                  "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        with patch("llm.openai_compatible.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            await llm.chat_tools(MESSAGES, [])
        payload = client.post.call_args.kwargs["json"]
        self.assertEqual(payload["max_tokens"], 400)
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertEqual(ledger.calls[0]["reserved_completion_tokens"], 400)
        self.assertEqual(llm.call_metadata()["output_limit"], 400)

    async def test_parallel_clients_cannot_both_spend_last_reservation(self):
        ledger = self.ledger(max_cny="3")
        delegates = [FakeLLM(), FakeLLM()]
        results = await asyncio.gather(*(BudgetedLLM(client, ledger, CONTEXT).chat(MESSAGES)
                                         for client in delegates), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, BlindBudgetError) for result in results), 1)
        self.assertEqual(sum(client.calls for client in delegates), 1)
        self.assertEqual(len(ledger.calls), 1)

    async def test_negative_raw_provider_usage_cannot_be_hidden_by_adapter(self):
        ledger = self.ledger()
        client = AsyncMock()
        client.post.return_value = httpx.Response(200, request=httpx.Request("POST", "https://provider.test"),
            json={"choices": [{"finish_reason": "stop", "message": {"content": "answer", "reasoning_content": "PRIVATE_THOUGHT"}}],
                  "usage": {"prompt_tokens": 10, "completion_tokens": 5, "prompt_cache_hit_tokens": -1}})
        llm = BudgetedOpenAICompatibleLLM("fake-model", "https://provider.test", "SECRET_API_KEY",
            ledger=ledger, context=CONTEXT, budget=ContextBudget(1600, 1000, 500, 100))
        with patch("llm.openai_compatible.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            with self.assertRaises(BudgetAmbiguityError):
                await llm.chat(MESSAGES)
        stored = self.path.read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE_THOUGHT", stored)
        self.assertNotIn("SECRET_API_KEY", stored)
        self.assertEqual(ledger.accounted_upper_cny, Decimal("2"))

    async def test_persistence_failure_prevents_provider_call(self):
        ledger = self.ledger()
        delegate = FakeLLM()
        with patch("backend.verification.blind_budget.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(BlindBudgetError):
                await BudgetedLLM(delegate, ledger, CONTEXT).chat(MESSAGES)
        self.assertEqual(delegate.calls, 0)
        self.assertIsNotNone(ledger.frozen_reason)

    async def test_resume_preserves_incomplete_reservations(self):
        ledger = self.ledger()
        ledger.reserve(input_limit=1000, output_limit=500, context=CONTEXT,
                       model="fake-model", transport="chat", estimated_input_tokens=26)
        resumed = MoneyRequestLedger(self.path, self.pricing, resume=True)
        self.assertEqual(resumed.accounted_upper_cny, Decimal("2"))
        self.assertEqual(resumed.calls[0]["status"], "interrupted_unknown")
        with self.assertRaises(BlindBudgetError):
            MoneyRequestLedger(self.path, self.pricing)

    async def test_authorized_limits_and_money_require_exact_types(self):
        for kwargs in ({"max_cny": "20.01"}, {"max_cny": 20.0}, {"request_limit": 301}, {"request_limit": True}):
            with self.assertRaises(ValueError):
                self.ledger(**kwargs)
        self.assertEqual(self.pricing.cost(7, 13), Decimal("0.033"))


if __name__ == "__main__":
    unittest.main()
