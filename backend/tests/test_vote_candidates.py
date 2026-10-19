from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend" / "app"))

from backend.tests.test_engine_flow import build_engine
from domain.state import ScenePhase
from llm.tools import parse_native_message
from runtime.contracts import RuntimeScope


class DecisionAuditStore:
    """In-memory audit sink: the real model/control path runs with a fake LLM."""

    def __init__(self):
        self.tools = {}

    def assert_scope(self, scope, **kwargs):
        return {"phase_epoch": 0}

    def start_model(self, *args):
        pass

    def finish_model(self, *args):
        pass

    def enqueue_tool(self, scope, call_id, *args):
        self.tools[call_id] = {"scope": scope}

    def finish_tool(self, call_id, result):
        self.tools[call_id]["result"] = result


class VoteCandidatesTest(unittest.IsolatedAsyncioTestCase):
    async def make_dm(self, eligible=None):
        dm = build_engine()
        script = dm.script_loader.load("fog_harbor_clocktower")
        if eligible is not None:
            script["stage_flow"]["stage_1"]["resolution"]["vote"]["eligible_role_ids"] = eligible
        await dm.init_game_from_script(script, "shen_zhiwei", "deduction")
        dm.state.scene_phase = ScenePhase.DM_HOSTING
        dm.prepare_stage_resolution()
        return dm

    def bind_control_runtime(self, dm):
        dm.workflow_enabled = True
        dm.runtime_store = DecisionAuditStore()
        for role_id in dm.state.ai_role_ids:
            agent = dm.agent_pool.get(role_id)
            scope = RuntimeScope(game_id=1, run_id="vote-test-run", context_id=f"context:{role_id}",
                                 agent_instance_id=agent.instance_id, actor_kind="role", actor_role_id=role_id)
            agent.runtime_scope = scope
            dm.context_broker.runtime_scopes[role_id] = scope

    def reply(self, target):
        return parse_native_message({"role": "assistant", "content": None, "tool_calls": [{
            "id": "vote-call", "type": "function", "function": {
                "name": "cast_role_vote", "arguments": json.dumps({"target_role_id": target}),
            },
        }]})

    async def test_every_eligible_voter_can_vote_for_self_without_ballot_rewriting(self):
        for transport in ("plain", "legacy_json"):
            with self.subTest(transport=transport):
                dm = await self.make_dm()
                candidates = dm._stage_vote_candidate_ids()
                prompts = []

                async def own_vote(context):
                    prompts.append(context.messages[-1].content)
                    value = context.role_id if transport == "plain" else json.dumps({"target_role_id": context.role_id})
                    return value, False

                with patch.object(dm, "_call_agent", new=AsyncMock(side_effect=own_vote)):
                    result = await dm.cast_stage_vote(dm.state.human_player_role_id)
                ballots = result["vote"]["ballots"]
                self.assertEqual(len(ballots), len(candidates))
                self.assertTrue(all(ballot["target_role_id"] == ballot["voter_role_id"] for ballot in ballots))
                for prompt in prompts:
                    listed = [line.split("=", 1)[1].split("；", 1)[0] for line in prompt.splitlines() if line.startswith("- role_id=")]
                    self.assertEqual(listed, candidates)
                self.assertEqual([item["votes"] for item in result["vote"]["tally"]], [1] * len(candidates))
                self.assertEqual(result["vote"]["selected_role_id"], min(candidates))

    async def test_human_and_agent_reject_unknown_and_known_ineligible_targets_atomically(self):
        for target in ("unknown_role", "xu_yanzhou"):
            with self.subTest(target=target):
                dm = await self.make_dm(["gu_linchuan", "zhou_jiming"])
                with patch.object(dm, "_call_agent", new=AsyncMock(return_value=(target, False))) as call:
                    with self.assertRaisesRegex(ValueError, "候选范围"):
                        await dm.cast_stage_vote(target)
                    call.assert_not_called()
                    with self.assertRaisesRegex(ValueError, "投票未完成"):
                        await dm.cast_stage_vote("gu_linchuan")
                resolution = dm.get_stage_resolution()
                self.assertTrue(resolution["vote"]["pending"])
                self.assertEqual(resolution["vote"]["ballots"], [])
                self.assertFalse(resolution["resolved"])
                self.assertEqual(dm.state.penalties, [])
                self.assertFalse(any(item.get("event_type") == "stage_vote" for item in dm.state.persistence_events))

    async def test_native_vote_enum_and_validation_share_the_script_candidates(self):
        eligible = ["gu_linchuan", "zhou_jiming"]
        for actor, target, expected_failed in (
            ("gu_linchuan", "gu_linchuan", False),
            ("xu_yanzhou", "gu_linchuan", False),
            ("xu_yanzhou", "xu_yanzhou", True),
            ("gu_linchuan", "unknown_role", True),
        ):
            with self.subTest(actor=actor, target=target):
                dm = await self.make_dm(eligible)
                self.bind_control_runtime(dm)
                agent = dm.agent_pool.get(actor)
                context = dm._build_agent_context(role_id=actor, channel="public_vote", purpose="stage_vote",
                    instruction="请从当前幕候选中投票，允许投自己。", instruction_source="dm_stage_vote")
                with patch.object(agent._llm, "chat_tools", new=AsyncMock(return_value=self.reply(target))) as call:
                    value, failed = await dm._call_agent(context)
                definition = call.call_args.args[1][0]["function"]
                self.assertEqual(definition["parameters"]["properties"]["target_role_id"]["enum"], eligible)
                self.assertEqual(failed, expected_failed)
                self.assertEqual(value, "" if expected_failed else target)
                record = next(iter(dm.runtime_store.tools.values()))["result"]
                self.assertEqual(record["status"], "rejected" if expected_failed else "succeeded")
                self.assertFalse(record["gameplay_committed"])
                self.assertTrue(dm.get_stage_resolution()["vote"]["pending"])

    async def test_final_decision_uses_its_own_eligible_list(self):
        dm = await self.make_dm(["gu_linchuan", "zhou_jiming"])
        dm.state.current_stage_num = dm.state.total_stages
        final = dm._stage_flow_config()["resolution"]["final_decision"]["eligible_role_ids"]
        self.assertEqual(dm._stage_vote_candidate_ids(), final)
        self.assertNotEqual(final, ["gu_linchuan", "zhou_jiming"])
        public = dm.prepare_stage_resolution()["vote"]["eligible_roles"]
        self.assertEqual([role["role_id"] for role in public], final)


if __name__ == "__main__":
    unittest.main()
