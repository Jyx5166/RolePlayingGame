from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from backend.verification.live_game_check import CountedDeepSeek, FULL_GAME_SEARCH_TARGETS, RequestLedger, RequestLimitExceeded
from backend.verification.summarize_live_acceptance import group
from llm.openai_compatible import OpenAICompatibleLLM
from dm.permission import PermissionMatrix
from loader.script_loader import ScriptLoader


class LiveAcceptanceGuardTest(unittest.IsolatedAsyncioTestCase):
    async def test_client_failures_and_cancellations_keep_reserved_slots_and_redact_key(self):
        settings = SimpleNamespace(llm_model="test", llm_base_url="https://api.deepseek.com",
            llm_api_key="FAKE_TEST_KEY", llm_timeout_seconds=120, llm_context_window=32768,
            llm_input_limit=23000, llm_output_limit=8192, llm_safety_margin=1024, llm_reasoning_effort="")
        ledger = RequestLedger(2)
        client = CountedDeepSeek(ledger, settings)
        with patch.object(OpenAICompatibleLLM, "chat", new=AsyncMock(side_effect=RuntimeError("FAKE_TEST_KEY"))):
            with self.assertRaises(RuntimeError):
                await client.chat([{"role": "user", "content": "test"}])
        self.assertEqual(ledger.calls[0]["status"], "failed")
        self.assertNotIn("FAKE_TEST_KEY", ledger.calls[0]["error"])
        with patch.object(OpenAICompatibleLLM, "chat", new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await client.chat([{"role": "user", "content": "test"}])
        self.assertEqual(ledger.calls[1]["status"], "canceled")
        self.assertIsNone(ledger.calls[1].get("usage"))
        with self.assertRaises(RequestLimitExceeded):
            await client.chat([{"role": "user", "content": "test"}])

    async def test_synthetic_calls_are_grouped_by_actual_profile_not_global_section(self):
        call = {"section": "full_game_stage_2", "messages": [{"role": "user", "content":
            "[ROLE_MEMORY_DATA]\n" + json.dumps([{"kind": "role_profile", "owner_role_id": "qa_c_doctor"}])}]}
        self.assertEqual(group(call), "synthetic_wrong_endings")
        self.assertEqual(group({"section": "memory_provider_default", "messages": []}), "memory_provider_default")

    async def test_original_game_search_targets_exist_and_are_unlocked(self):
        script = json.loads((PROJECT / "backend/resources/scripts/fog_harbor_clocktower.json").read_text(encoding="utf-8"))
        targets = {target["id"]: target for target in script["mechanics_config"]["search"]["search_targets"]}
        for stage, target_ids in FULL_GAME_SEARCH_TARGETS.items():
            for target_id in target_ids:
                self.assertIn(target_id, targets)
                self.assertLessEqual(targets[target_id]["unlock_stage"], stage)

    async def test_exact_hundred_call_limit_rejects_the_hundred_and_first(self):
        ledger = RequestLedger(100)
        with patch("builtins.print"):
            for _ in range(100):
                ledger.reserve([], "", 8192)
            with self.assertRaises(RequestLimitExceeded):
                ledger.reserve([], "", 8192)
        self.assertEqual(len(ledger.calls), 100)

    async def test_timeout_fixture_is_a_valid_separate_script(self):
        script = json.loads((PROJECT / "backend/verification/fixtures/wrong_ending_timeout.json").read_text(encoding="utf-8"))
        ScriptLoader(PROJECT / "backend/resources/scripts").validate(script)
        self.assertEqual(len(PermissionMatrix(script).role_ids), 3)
        self.assertEqual(script["script_meta"]["total_stages"], 1)
        self.assertEqual(script["stage_flow"]["stage_1"]["investigation"]["duration_seconds"], 5)

    async def test_shared_limit_never_reserves_more_than_authorized_calls(self):
        ledger = RequestLedger(3)

        async def request():
            try:
                return ledger.reserve([], "", 8192)["number"]
            except RequestLimitExceeded:
                return None

        results = await asyncio.gather(*(request() for _ in range(20)))
        self.assertEqual([number for number in results if number], [1, 2, 3])
        self.assertEqual(len(ledger.calls), 3)

    async def test_failed_and_canceled_reservations_are_not_refunded(self):
        ledger = RequestLedger(2)
        ledger.reserve([], "", 8192)["status"] = "failed"
        ledger.reserve([], "", 8192)["status"] = "canceled"
        with self.assertRaises(RequestLimitExceeded):
            ledger.reserve([], "none", 1024)

    async def test_limit_and_persisted_running_record(self):
        for value in (0, 101):
            with self.assertRaises(ValueError):
                RequestLedger(value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calls.json"
            ledger = RequestLedger(100, path)
            ledger.reserve([{"role": "user", "content": "synthetic"}], "", 8192)
            self.assertIn('"reserved_requests": 1', path.read_text(encoding="utf-8"))
            self.assertIn('"status": "running"', path.read_text(encoding="utf-8"))
