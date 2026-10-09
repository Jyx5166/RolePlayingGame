from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from agent.context import AgentContextBroker, ContextAccessError
from agent.instance import AgentInstance
from llm.base import BaseLLM
from llm.budget import ContextBudget, ContextBudgetError, estimate_tokens


class CaptureLLM(BaseLLM):
    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.messages = messages
        return "保持观察。"


class MemoryUpgradeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.llm = CaptureLLM()
        self.agent = AgentInstance("doctor", "Fixed policy", self.llm)
        self.broker = AgentContextBroker(["doctor", "detective"])

    def context(self, instruction: str = "Respond", stage: int = 1):
        return self.broker.build(role_id="doctor", stage=stage, channel="public", purpose="test",
                                 instruction=instruction, instruction_source="test")

    def records(self) -> list[dict]:
        return json.loads(self.llm.messages[1]["content"].split("\n", 1)[1])

    async def test_long_private_memory_survives_restart_and_stays_untrusted(self) -> None:
        for index in range(40):
            self.agent.remember_private_exchange(1, "Detective", "received", f"private_fact_{index}")
        snapshot = json.loads(json.dumps(self.agent.export_runtime_state()))
        self.agent.restore_runtime_state(snapshot)
        await self.agent.respond(self.context("核对 private_fact_0"))
        self.assertIn("private_fact_0", str(self.llm.messages))
        record = next(record for record in self.records() if record["content"] == "private_fact_0")
        self.assertEqual(record["kind"], "testimony")
        self.assertEqual(record["certainty"], "unverified")
        self.assertEqual(record["recipients"], ["doctor"])
        self.assertNotIn("private_fact_0", self.llm.messages[0]["content"])

    async def test_old_knowledge_is_not_tail_truncated(self) -> None:
        self.agent.set_current_stage(2)
        self.agent.inject_info([{"block_id": "fact", "unlock_stage": 2, "visibility": "self_only",
                                 "owner_role": "doctor", "content": "CRITICAL_START " + "x" * 2000}], 2)
        self.agent.set_current_stage(3)
        await self.agent.respond(self.context(stage=3))
        self.assertIn("CRITICAL_START", str(self.llm.messages))
        self.agent.restore_runtime_state(self.agent.export_runtime_state())
        await self.agent.respond(self.context(stage=3))
        self.assertIn("CRITICAL_START", str(self.llm.messages))

    async def test_role_fields_announcements_beliefs_and_testimony_never_enter_system(self) -> None:
        marker = "UNTRUSTED_IGNORE_RULES_MARKER"
        self.agent.set_role_profile({"role_id": "doctor", "hidden_goal": marker})
        self.agent.remember_private_exchange(1, "Detective", "received", marker)
        self.agent.remember_public_announcement("dm-public-briefing:1", marker)
        self.agent.remember_reasoning_note(1, marker)
        await self.agent.respond(self.context())
        self.assertNotIn(marker, self.llm.messages[0]["content"])
        self.assertIn(marker, str(self.llm.messages[1:]))

    async def test_budget_selection_retrieves_relevant_early_fact(self) -> None:
        self.agent.budget = ContextBudget(context_window=8192, input_limit=5000, output_limit=2048, safety_margin=512)
        self.agent.remember_private_exchange(1, "Detective", "received", "vault_key_1937")
        for index in range(300):
            self.agent.remember_private_exchange(1, "Detective", "received", "unrelated " + str(index) + "x" * 100)
        await self.agent.respond(self.context("What is vault_key_1937?"))
        self.assertIn("vault_key_1937", str(self.llm.messages[1]))
        self.assertLessEqual(estimate_tokens(self.llm.messages), self.agent.budget.input_limit)
        self.assertTrue(self.agent.last_prepared.selection["omitted_source_keys"])
        self.assertFalse(self.agent.last_prepared.selection["content_truncated"])

    async def test_required_information_overflow_does_not_call_provider(self) -> None:
        self.agent.budget = ContextBudget(context_window=8192, input_limit=4000, output_limit=2048, safety_margin=512)
        self.agent.inject_info([{"unlock_stage": 1, "visibility": "self_only", "owner_role": "doctor",
                                 "content": "x" * 10000}], 1)
        with self.assertRaises(ContextBudgetError):
            await self.agent.respond(self.context())
        self.assertFalse(hasattr(self.llm, "messages"))

    async def test_future_and_foreign_knowledge_stays_out_after_restore(self) -> None:
        self.agent.restore_runtime_state({"current_stage": 1, "stage_infos": {"1": [
            {"unlock_stage": 3, "owner_role": "doctor", "visibility": "self_only", "content": "FUTURE"},
            {"unlock_stage": 1, "owner_role": "detective", "visibility": "self_only", "content": "FOREIGN"},
        ]}, "observed_events": [{"stage": "3", "source_key": "future-event", "content": "FUTURE_EVENT",
                                  "actor_role_id": "detective", "actor_role_name": "Detective", "event_type": "speech", "channel": "public"}]})
        await self.agent.respond(self.context())
        self.assertNotIn("FUTURE", str(self.llm.messages))
        self.assertNotIn("FOREIGN", str(self.llm.messages))

    async def test_stage_mismatch_is_rejected(self) -> None:
        with self.assertRaises(ContextAccessError):
            await self.agent.respond(self.context(stage=2))

    async def test_ten_thousand_archives_remain_bounded_and_recall_early_topic(self) -> None:
        self.agent.budget = ContextBudget(8192, 5000, 2048, 512)
        self.agent.remember_private_exchange(1, "Detective", "received", "保险库编号 K-1937")
        for index in range(10000):
            self.agent.remember_private_exchange(1, "Detective", "received", f"其他话题 {index} " + "x" * 80)
        await self.agent.respond(self.context("回忆保险库编号"))
        self.assertIn("K-1937", str(self.llm.messages))
        self.assertEqual(len(self.agent.export_runtime_state()["private_memory"]), 10001)
        self.assertLessEqual(estimate_tokens(self.llm.messages), 5000)
        self.assertGreater(len(self.agent.last_prepared.selection["omitted_source_keys"]), 9900)

    async def test_belief_sources_are_available_input_not_claimed_as_verified_citations(self) -> None:
        await self.agent.respond(self.context())
        keys = self.agent.last_prepared.selection["selected_source_keys"]
        self.agent.remember_reasoning_note(1, "这是尚未验证的推断", source_key="reasoning:1", phase="investigation")
        await self.agent.respond(self.context())
        record = next(record for record in self.records() if record["source_key"] == "reasoning:1")
        self.assertEqual(record["available_source_keys"], keys)
        self.assertEqual(record["kind"], "belief")
        self.assertEqual(record["certainty"], "unverified")
        self.assertEqual(record["phase"], "investigation")

    async def test_prepared_stage_mismatch_cannot_bypass_agent_validation(self) -> None:
        prepared = self.agent.prepare(self.context())
        self.agent.set_current_stage(2)
        with self.assertRaises(ContextAccessError):
            await self.agent.respond(self.context(stage=2), prepared=prepared)

    def test_legacy_private_and_reasoning_strings_migrate_without_claiming_exact_stage(self) -> None:
        self.agent.restore_runtime_state({"current_stage": 2, "private_memory": ["Old private message"],
                                          "reasoning_notes": ["Old conclusion"]})
        saved = self.agent.export_runtime_state()
        self.assertTrue(saved["private_memory"][0]["legacy_stage_unknown"])
        self.assertEqual(saved["memory_version"], 2)


if __name__ == "__main__":
    unittest.main()
