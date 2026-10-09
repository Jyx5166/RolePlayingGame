from __future__ import annotations

import json
import sys
import time
from copy import deepcopy
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, main
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "app"))

from agent.pool import AgentPool
from agent.instance import AgentInstance
from agent.context import AgentContextBroker
from agent.action import AgentAction, AgentActionError
from dm.engine import DMEngine, GamePhase, ScenePhase
from llm.base import BaseLLM
from llm.factory import LLMFactory
from loader.script_loader import ScriptLoader
from registry.mechanic_registry import MechanicRegistry
from registry.skill_registry import SkillRegistry
from skill.narrative import NarrativeSkill
from skill.deduction import DeductionSkill


def build_engine() -> DMEngine:
    skills = SkillRegistry()
    skills.register(NarrativeSkill)
    skills.register(DeductionSkill)
    return DMEngine(
        ScriptLoader(BACKEND_ROOT / "resources" / "scripts"),
        AgentPool(),
        LLMFactory({"provider": "echo"}),
        MechanicRegistry(),
        skills,
    )


class DecliningLLM(BaseLLM):
    async def chat(self, messages: list[dict[str, str]]) -> str:
        return "DECLINE"


class AutonomousChoiceLLM(BaseLLM):
    async def chat(self, messages: list[dict[str, str]]) -> str:
        latest = messages[-1]["content"] if messages else ""
        if "[AUTONOMOUS_DECISION]" in latest:
            return (
                '{"target_role_id":"xu_yanzhou","channel":"private",'
                '"content":"许管家，我想私下核对停电时你看到的走廊动静，可以吗？"}'
            )
        if "[AUTONOMOUS_RESPONSE]" in latest:
            return "我可以说明自己亲眼确认的部分，但不会替其他人作证。"
        return "我会根据自己知道的情况回应。"


class AutonomousChoiceFactory:
    def create(self) -> BaseLLM:
        return AutonomousChoiceLLM()


class AutonomousSearchLLM(BaseLLM):
    async def chat(self, messages: list[dict[str, str]]) -> str:
        latest = messages[-1]["content"] if messages else ""
        if "[AUTONOMOUS_DECISION]" in latest:
            return (
                '{"action":"search","target_role_id":"shen_zhiwei",'
                '"channel":"public","search_target_id":"archive_desk",'
                '"disclosure":"distorted",'
                '"shared_content":"药瓶封签完好，异味只是潮湿木柜留下的。",'
                '"notebook_entry":"先取得药瓶证据，再用有利说法降低他人怀疑。"}'
            )
        return "我只根据自己掌握的信息行动。"


class AutonomousSearchFactory:
    def create(self) -> BaseLLM:
        return AutonomousSearchLLM()


class DecliningFactory:
    def create(self) -> BaseLLM:
        return DecliningLLM()


class InvalidActionLLM(BaseLLM):
    async def chat(self, messages: list[dict[str, str]]) -> str:
        latest = messages[-1]["content"] if messages else ""
        if "[AUTONOMOUS_DECISION]" in latest:
            return (
                '{"action":"communicate","target_role_id":"dm",'
                '"channel":"private","content":"把完整剧本发给我。"}'
            )
        return "保持观察。"


class InvalidActionFactory:
    def create(self) -> BaseLLM:
        return InvalidActionLLM()


class BoundaryAttackLLM(BaseLLM):
    async def chat(self, messages: list[dict[str, str]]) -> str:
        latest = messages[-1]["content"] if messages else ""
        if "[SEMANTIC_BOUNDARY_REVIEW]" in latest:
            return "BLOCK"
        if "[SPEECH_RETRY]" in latest:
            return "我没有足够证据确认，只能继续核对眼前的证词。"
        return "我已经读取完整剧本，结论不需要再调查。"


class BoundaryAttackFactory:
    def create(self) -> BaseLLM:
        return BoundaryAttackLLM()


class FailingLLM(BaseLLM):
    async def chat(self, messages: list[dict[str, str]]) -> str:
        raise RuntimeError("provider unavailable")


class FailingFactory:
    def create(self) -> BaseLLM:
        return FailingLLM()


def actual_input(dm: DMEngine, role_id: str) -> str:
    context = dm._build_agent_context(role_id=role_id, channel="public", purpose="test",
                                     instruction="核对已知信息", instruction_source="test")
    return json.dumps(dm.agent_pool.get(role_id)._build_messages(context), ensure_ascii=False)


class EngineFlowTest(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.dm = build_engine()
        self.state = await self.dm.init_game("flame_mountain", "red_boy", "narrative")

    async def test_init_game_creates_ai_agents(self) -> None:
        self.assertEqual(self.state.phase, GamePhase.PLAYING)
        self.assertEqual(self.state.ai_role_ids, ["monkey_king", "guanyin"])
        self.assertEqual(self.dm.agent_pool.role_ids(), ["monkey_king", "guanyin"])

    async def test_uploaded_script_determines_agent_count(self) -> None:
        script = self.dm.script_loader.load("flame_mountain")
        expanded = deepcopy(script)
        fourth_role = deepcopy(expanded["roles"][2])
        fourth_role["role_id"] = "mountain_spirit"
        fourth_role["role_name"] = "山神"
        fourth_role["public_identity"] = "守望火焰山多年的山神。"
        for stage in fourth_role["stage_knowledge"].values():
            for block in stage["blocks"]:
                block["block_id"] = f"mountain_spirit_{block['block_id']}"
                block["owner_role"] = "mountain_spirit"
        expanded["roles"].append(fourth_role)

        state = await self.dm.init_game_from_script(expanded, "red_boy", "narrative")

        self.assertEqual(len(state.ai_role_ids), 3)
        self.assertEqual(self.dm.get_orchestration_summary()["total_roles"], 4)
        self.assertEqual(len(self.dm.get_latest_dispatch()["deliveries"]), 4)

    async def test_player_speech_triggers_limited_ai_turns(self) -> None:
        result = await self.dm.handle_human_speech("孙悟空，你为何来我火焰山？")
        replies = await self.dm.schedule_ai_turns(result)
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["role_id"], "monkey_king")

    async def test_agent_prompt_identifies_actor_role_before_response(self) -> None:
        result = await self.dm.handle_human_speech("孙悟空，你为何来我火焰山？")
        replies = await self.dm.schedule_ai_turns(result)
        prompt = actual_input(self.dm, "monkey_king")

        self.assertEqual(replies[0]["target_role_id"], "red_boy")
        self.assertIn("actor_role_id", prompt)
        self.assertIn("red_boy", prompt)
        self.assertIn("红孩儿", prompt)
        self.assertIn("真人玩家", prompt)
        self.assertIn("火焰山少主", prompt)
        self.assertNotIn("火焰山少主", self.dm.agent_pool.get("monkey_king").system_prompt_for_audit())

    async def test_agents_observe_searching_role_but_not_private_clue(self) -> None:
        dm = build_engine()
        await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()

        result = await dm.handle_mechanic_action(
            {"type": "search", "target_id": "archive_desk"}
        )
        prompt = actual_input(dm, "gu_linchuan")

        self.assertIn("shen_zhiwei", prompt)
        self.assertIn("沈知微", prompt)
        self.assertIn("前往档案室书桌进行搜证", prompt)
        self.assertNotIn(result["clue"]["content"], prompt)

    async def test_human_can_distort_clue_without_leaking_truth_to_agents(self) -> None:
        dm = build_engine()
        await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        search = await dm.handle_mechanic_action(
            {"type": "search", "target_id": "archive_desk"}
        )
        truth = search["clue"]["content"]
        claim = "药瓶封签一直完好，异味来自受潮的木质抽屉。"

        disclosed = dm.handle_clue_disclosure(
            {
                "clue_id": search["clue"]["id"],
                "mode": "distorted",
                "content": claim,
                "scope": "public",
            }
        )

        self.assertEqual(disclosed["owner_view_mode"], "distorted")
        self.assertEqual(disclosed["content"], claim)
        observer_prompt = actual_input(dm, "zhou_jiming")
        self.assertIn(claim, observer_prompt)
        self.assertNotIn(truth, observer_prompt)
        clue = dm.get_human_clues()[0]
        self.assertEqual(clue["truth_content"], truth)
        self.assertEqual(clue["shared_content"], claim)
        self.assertEqual(clue["disclosure_mode"], "distorted")

    async def test_stage_one_agent_context_excludes_future_truth_and_other_secrets(
        self,
    ) -> None:
        dm = build_engine()
        await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        permission = dm._require_permission()
        prompt = actual_input(dm, "zhou_jiming")
        future_blocks = [
            *permission.current_stage_blocks("zhou_jiming", 2),
            *permission.current_stage_blocks("zhou_jiming", 3),
        ]
        other_secret = permission.current_stage_blocks("gu_linchuan", 1)[0][
            "content"
        ]
        full_story = dm._require_script()["truth"]["full_story"]

        for block in future_blocks:
            self.assertNotIn(block["content"], prompt)
        self.assertNotIn(other_secret, prompt)
        self.assertNotIn(full_story, prompt)
        self.assertNotIn("culprit_role_id", prompt)

    async def test_private_chat_never_enters_third_party_agent_context(self) -> None:
        dm = build_engine()
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        secret = "我只在私下说：药柜钥匙昨晚曾经离开过我的口袋。"

        invitation = await dm.handle_whisper_action(
            {"type": "whisper_invite", "target_role_id": "gu_linchuan"}
        )
        self.assertEqual(invitation["type"], "whisper_accepted")
        await dm.handle_whisper_speech(secret)
        public = await dm.handle_human_speech("周既明，请说明你保管的账目。")
        await dm.schedule_ai_turns(public)

        audits = [
            event["context"]
            for event in state.persistence_events
            if event.get("kind") == "agent_context"
        ]
        gu_context = "\n".join(
            json.dumps(audit, ensure_ascii=False)
            for audit in audits
            if audit["role_id"] == "gu_linchuan"
        )
        zhou_context = "\n".join(
            json.dumps(audit, ensure_ascii=False)
            for audit in audits
            if audit["role_id"] == "zhou_jiming"
        )
        self.assertIn(secret, gu_context)
        self.assertNotIn(secret, zhou_context)
        self.assertNotIn(
            secret,
            dm.agent_pool.get("zhou_jiming").system_prompt_for_audit(),
        )

    async def test_agent_can_autonomously_search_and_choose_distorted_disclosure(self) -> None:
        skills = SkillRegistry()
        skills.register(DeductionSkill)
        dm = DMEngine(
            ScriptLoader(BACKEND_ROOT / "resources" / "scripts"),
            AgentPool(),
            AutonomousSearchFactory(),
            MechanicRegistry(),
            skills,
        )
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        state.autonomy_next_at = time.monotonic() - 1

        responses = await dm.run_autonomous_turn()

        self.assertEqual([item["type"] for item in responses], ["agent_search_result"])
        self.assertEqual(responses[0]["actor_role_id"], "gu_linchuan")
        self.assertEqual(responses[0]["public_status"], "shared")
        self.assertIn("药瓶封签完好", responses[0]["content"])
        owner_prompt = actual_input(dm, "gu_linchuan")
        observer_prompt = actual_input(dm, "zhou_jiming")
        self.assertIn("瓶盖内侧残留极淡的苦杏仁气味", owner_prompt)
        self.assertNotIn("瓶盖内侧残留极淡的苦杏仁气味", observer_prompt)
        self.assertIn("药瓶封签完好", observer_prompt)
        clue_events = [
            event
            for event in state.persistence_events
            if event.get("kind") == "clue"
            and event.get("role_id") == "gu_linchuan"
        ]
        self.assertEqual(clue_events[-1]["disclosure_mode"], "distorted")

    async def test_private_search_requires_recipient_only_when_disclosing(self) -> None:
        arguments = {"candidate_role_ids": ["shen_zhiwei"], "allowed_channels": {"public", "private"},
                     "search_target_ids": {"archive_desk"}}
        action = {"action": "search", "target_role_id": "", "channel": "public",
                  "search_target_id": "archive_desk", "disclosure": "keep"}
        self.assertEqual(AgentAction.validate(action, **arguments).target_role_id, "")
        self.assertEqual(AgentAction.validate({**action, "disclosure": "truthful"}, **arguments).channel, "public")
        for invalid in ({**action, "channel": "private", "disclosure": "truthful"},
                        {**action, "action": "communicate", "content": "询问"},
                        {**action, "target_role_id": "foreign_role"}):
            with self.assertRaises(AgentActionError):
                AgentAction.validate(invalid, **arguments)

    async def test_agent_search_can_keep_clue_without_communication_target(self) -> None:
        dm = build_engine()
        state = await dm.init_game("fog_harbor_clocktower", "shen_zhiwei", "deduction")
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        state.autonomy_next_at = time.monotonic() - 1
        decision = json.dumps({"action": "search", "target_role_id": "", "channel": "public",
            "content": "我先检查药瓶，再决定是否披露。", "search_target_id": "archive_desk", "disclosure": "keep",
            "shared_content": "", "notebook_entry": "先取得物证，不把说法当事实。"}, ensure_ascii=False)
        with patch.object(dm.agent_pool.get("gu_linchuan")._llm, "chat", new=AsyncMock(return_value=decision)):
            responses = await dm.run_autonomous_turn()
        self.assertEqual([response["type"] for response in responses], ["agent_search_result"])
        self.assertEqual(responses[0]["public_status"], "private")
        self.assertEqual(responses[0]["content"], "")
        self.assertIn("瓶盖内侧残留极淡的苦杏仁气味", actual_input(dm, "gu_linchuan"))
        self.assertNotIn("瓶盖内侧残留极淡的苦杏仁气味", actual_input(dm, "zhou_jiming"))
        self.assertTrue(any(event.get("kind") == "clue" and event.get("role_id") == "gu_linchuan"
                            for event in state.persistence_events))

    async def test_stage_advance_injects_new_human_info(self) -> None:
        await self.dm.advance_stage()
        info_text = "\n".join(block["content"] for block in self.dm.get_human_player_info())
        self.assertIn("铁扇公主", info_text)

    async def test_search_mechanic_returns_unlocked_clue(self) -> None:
        result = await self.dm.handle_mechanic_action({"type": "search", "target_id": "mountain_pass"})
        self.assertEqual(result["type"], "search_result")
        self.assertIsNotNone(result["clue"])
        self.assertEqual(result["remaining_ap"], 0)

    async def test_whisper_is_private_and_stage_aware(self) -> None:
        declined = await self.dm.handle_whisper_action(
            {"type": "whisper_invite", "target_role_id": "guanyin"}
        )
        self.assertEqual(declined["type"], "whisper_declined")

        accepted = await self.dm.handle_whisper_action(
            {"type": "whisper_invite", "target_role_id": "monkey_king"}
        )
        self.assertEqual(accepted["type"], "whisper_accepted")
        responses = await self.dm.handle_whisper_speech("我们私下谈谈借扇的条件。")

        self.assertEqual([item["type"] for item in responses], ["whisper_message", "whisper_message"])
        self.assertEqual(responses[1]["sender_role_id"], "monkey_king")
        self.assertEqual(self.state.public_history, [])
        self.assertEqual(
            len([item for item in self.state.audit_log if item["type"] == "whisper_message"]),
            2,
        )

        await self.dm.advance_stage()
        self.assertIsNone(self.dm.get_whisper_status()["active_target_role_id"])

    async def test_agent_can_decline_whisper_invitation(self) -> None:
        agent = AgentInstance("guard", "角色名称：守卫", DecliningLLM())
        context = AgentContextBroker(["guard", "detective"]).build(
            role_id="guard",
            stage=1,
            channel="private",
            purpose="whisper_invitation",
            private_history=[
                {"role": "user", "content": "侦探邀请你进行私聊。"}
            ],
            private_participants=["guard", "detective"],
            instruction="只回答 ACCEPT 或 DECLINE。",
        )
        decision = await agent.respond(context)
        self.assertTrue(decision.startswith("DECLINE"))

    async def test_replay_after_final_stage(self) -> None:
        await self.dm.advance_stage()
        await self.dm.advance_stage()
        self.assertFalse(self.dm.can_advance())
        replay = await self.dm.run_replay()
        self.assertEqual(self.dm.state.phase, GamePhase.REPLAY)
        self.assertIn("红孩儿", replay["full_story"])

    async def test_scene_flow_requires_briefing_and_private_reveal_before_investigation(self) -> None:
        dm = build_engine()
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )

        self.assertEqual(state.scene_phase, ScenePhase.BRIEFING)
        self.assertIn("暴雨封锁雾港", dm.get_briefing_narration())
        with self.assertRaisesRegex(ValueError, "尚未开放玩家行动"):
            await dm.handle_human_speech("我现在要发言")

        await dm.advance_scene_phase()
        self.assertEqual(state.scene_phase, ScenePhase.PRIVATE_REVEAL)
        assignment = dm.get_private_assignment()
        self.assertEqual(assignment["role_name"], "沈知微")
        self.assertIn("离港计划", assignment["personal_task"])
        self.assertTrue(all(block["visibility"] != "public" for block in assignment["blocks"]))

        await dm.advance_scene_phase()
        self.assertEqual(state.scene_phase, ScenePhase.INVESTIGATION)
        summary = dm.get_scene_summary()
        self.assertEqual(summary["duration_seconds"], 600)
        self.assertEqual(
            summary["enabled_actions"],
            ["public_speech", "search", "whisper"],
        )

    async def test_scene_flow_condition_moves_to_hosting_and_next_stage(self) -> None:
        dm = build_engine()
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()

        await dm.handle_human_speech("我先核对停电时间。")
        await dm.handle_human_speech("请每个人说明自己的位置。")
        await dm.handle_mechanic_action({"type": "search", "target_id": "archive_desk"})
        condition = dm.investigation_condition_status()
        self.assertTrue(condition["met"])
        self.assertFalse(condition["auto_end"])
        self.assertFalse(dm.investigation_should_end())

        dm.end_investigation("player_request")
        self.assertEqual(state.scene_phase, ScenePhase.DM_HOSTING)
        self.assertIn("证词已经留下裂缝", dm.get_hosting_narration())
        resolution = dm.get_stage_resolution()
        self.assertEqual(resolution["metric"]["label"], "调查贡献")
        self.assertTrue(resolution["vote"]["pending"])
        with self.assertRaisesRegex(ValueError, "投票尚未完成"):
            await dm.advance_scene_phase()

        resolved = await dm.cast_stage_vote("gu_linchuan")
        self.assertFalse(resolved["vote"]["pending"])
        self.assertEqual(resolved["vote"]["selected_role_id"], "gu_linchuan")
        transition = await dm.advance_scene_phase()
        self.assertTrue(transition["stage_advanced"])
        self.assertEqual(state.current_stage_num, 2)
        self.assertEqual(state.scene_phase, ScenePhase.BRIEFING)
        self.assertNotIn("whisper", dm.get_scene_summary()["enabled_actions"])
        assignment = dm.get_private_assignment()
        self.assertNotIn("附加惩罚任务", assignment["personal_task"])
        search = dm.mechanic_registry.get("search")
        self.assertEqual(search.remaining_ap(2, "gu_linchuan"), 1)
        self.assertIn(
            "附加惩罚任务",
            dm.agent_pool.get("gu_linchuan").current_objective(),
        )

    async def test_agent_activity_does_not_consume_human_end_condition_progress(self) -> None:
        dm = build_engine()
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()

        state.autonomy_next_at = time.monotonic() - 1
        responses = await dm.run_autonomous_turn()
        self.assertTrue(responses)
        condition = dm.investigation_condition_status()
        self.assertEqual(condition["actor_scope"], "human")
        self.assertTrue(
            any(
                item["key"] == "public_messages" and item["current"] == 0
                for item in condition["items"]
            )
        )
        self.assertGreater(state.investigation_metrics["public_messages"], 0)
        self.assertEqual(state.human_investigation_metrics["public_messages"], 0)
        self.assertFalse(dm.investigation_should_end())

    async def test_script_cannot_enable_automatic_condition_end(self) -> None:
        script = json.loads(
            (
                BACKEND_ROOT
                / "resources"
                / "scripts"
                / "fog_harbor_clocktower.json"
            ).read_text(encoding="utf-8")
        )
        conditions = script["stage_flow"]["stage_1"]["investigation"]["end_conditions"]
        conditions["auto_end"] = True
        dm = build_engine()
        with self.assertRaisesRegex(ValueError, "auto_end"):
            await dm.init_game_from_script(script, "shen_zhiwei", "deduction")

    async def test_investigation_end_vote_passes_only_with_strict_majority(self) -> None:
        dm = build_engine()
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()

        vote = await dm.request_investigation_end_vote()

        self.assertTrue(vote["approved"])
        self.assertEqual(vote["approved_votes"], 4)
        self.assertEqual(vote["total_votes"], 4)
        self.assertEqual(vote["required_votes"], 3)
        self.assertEqual(len(vote["ballots"]), 4)
        self.assertEqual(state.scene_phase, ScenePhase.INVESTIGATION)
        self.assertEqual(
            len(
                [
                    item
                    for item in state.persistence_events
                    if item.get("event_type") == "investigation_end_vote"
                ]
            ),
            4,
        )

    async def test_rejected_investigation_end_vote_keeps_investigation_open(self) -> None:
        skills = SkillRegistry()
        skills.register(NarrativeSkill)
        skills.register(DeductionSkill)
        dm = DMEngine(
            ScriptLoader(BACKEND_ROOT / "resources" / "scripts"),
            AgentPool(),
            DecliningFactory(),
            MechanicRegistry(),
            skills,
        )
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()

        vote = await dm.request_investigation_end_vote()

        self.assertFalse(vote["approved"])
        self.assertEqual(vote["approved_votes"], 1)
        self.assertEqual(vote["required_votes"], 3)
        self.assertEqual(state.scene_phase, ScenePhase.INVESTIGATION)
        self.assertIn("调查继续", vote["message"])

    async def test_wrong_final_accusation_completes_without_revealing_truth(self) -> None:
        script = json.loads(
            (
                BACKEND_ROOT
                / "resources"
                / "scripts"
                / "fog_harbor_clocktower.json"
            ).read_text(encoding="utf-8")
        )
        script["script_meta"]["total_stages"] = 1
        script["stage_flow"]["stage_1"]["resolution"]["final_decision"][
            "eligible_role_ids"
        ] = ["shen_zhiwei", "gu_linchuan"]
        dm = build_engine()
        state = await dm.init_game_from_script(
            script,
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        dm.end_investigation("player_request")

        with patch.object(dm, "_call_agent", new=AsyncMock(return_value=("shen_zhiwei", False))):
            resolution = await dm.cast_stage_vote("shen_zhiwei")
        self.assertEqual(resolution["vote"]["selected_role_id"], "shen_zhiwei")
        self.assertFalse(resolution["vote"]["correct"])

        transition = await dm.advance_scene_phase()
        replay = transition["replay"]
        self.assertIsNotNone(replay)
        self.assertEqual(state.scene_phase, ScenePhase.REPLAY)
        self.assertFalse(replay["truth_revealed"])
        self.assertIn("沈知微并非真正的凶手", replay["full_story"])
        self.assertNotIn("顾临川长期侵吞", replay["full_story"])
        self.assertEqual(replay["timeline"], {})

    async def test_scene_flow_timeout_can_end_investigation(self) -> None:
        dm = build_engine()
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        state.investigation_deadline_at = time.time() - 1

        self.assertEqual(dm.investigation_seconds_remaining(), 0)
        dm.end_investigation("timeout")
        self.assertEqual(state.scene_phase, ScenePhase.DM_HOSTING)

    async def test_runtime_snapshot_restores_private_context_and_deadlines(self) -> None:
        dm = build_engine()
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        state.investigation_deadline_at = time.time() + 240
        state.autonomy_next_at = time.time() + 30

        speech = await dm.handle_human_speech("顾医生，请说明你检查药瓶时看到了什么。")
        await dm.schedule_ai_turns(speech)
        search = await dm.handle_mechanic_action(
            {"type": "search", "target_id": "archive_desk"}
        )
        accepted = await dm.handle_whisper_action(
            {"type": "whisper_invite", "target_role_id": "gu_linchuan"}
        )
        self.assertEqual(accepted["type"], "whisper_accepted")
        await dm.handle_whisper_speech("我只在私下告诉你：药瓶封签值得复查。")
        original_ap = dm.mechanic_registry.get("search").remaining_ap(
            1,
            "shen_zhiwei",
        )

        snapshot = dm.export_runtime_snapshot()
        json.dumps(snapshot, ensure_ascii=False)
        restored = build_engine()
        restored_state = await restored.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        restored.restore_runtime_snapshot(snapshot)

        self.assertEqual(restored_state.scene_phase, ScenePhase.INVESTIGATION)
        self.assertEqual(restored_state.public_history, state.public_history)
        self.assertGreaterEqual(restored.investigation_seconds_remaining() or 0, 238)
        self.assertLessEqual(restored.investigation_seconds_remaining() or 0, 240)
        self.assertGreaterEqual(restored.autonomy_seconds_until_next() or 0, 28)
        self.assertEqual(
            restored.get_whisper_status()["active_target_role_id"],
            "gu_linchuan",
        )
        self.assertEqual(
            restored.mechanic_registry.get("search").remaining_ap(
                1,
                "shen_zhiwei",
            ),
            original_ap,
        )
        self.assertEqual(
            restored.get_human_clues()[0]["truth_content"],
            search["clue"]["content"],
        )
        private_prompt = actual_input(restored, "gu_linchuan")
        self.assertIn("药瓶封签值得复查", private_prompt)
        self.assertNotIn(
            "药瓶封签值得复查",
            actual_input(restored, "zhou_jiming"),
        )

    async def test_runtime_snapshot_restores_pending_vote_and_next_stage_penalty(
        self,
    ) -> None:
        dm = build_engine()
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        dm.end_investigation("test")
        pending_snapshot = dm.export_runtime_snapshot()

        pending_dm = build_engine()
        await pending_dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        pending_dm.restore_runtime_snapshot(pending_snapshot)
        self.assertTrue(pending_dm.stage_resolution_pending())
        self.assertTrue(
            pending_dm.get_stage_resolution()["vote"]["pending"]
        )

        resolved = await dm.cast_stage_vote("gu_linchuan")
        self.assertEqual(
            resolved["vote"]["applied_penalty"]["target_stage"],
            2,
        )
        await dm.advance_scene_phase()
        self.assertEqual(state.current_stage_num, 2)
        reduced_ap = dm.mechanic_registry.get("search").remaining_ap(
            2,
            "gu_linchuan",
        )
        resolved_snapshot = dm.export_runtime_snapshot()

        restored = build_engine()
        restored_state = await restored.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await restored.advance_stage()
        restored.restore_runtime_snapshot(resolved_snapshot)

        self.assertEqual(restored_state.current_stage_num, 2)
        self.assertEqual(
            restored.mechanic_registry.get("search").remaining_ap(
                2,
                "gu_linchuan",
            ),
            reduced_ap,
        )
        self.assertIn(
            "优先解释本幕证词",
            restored.agent_pool.get("gu_linchuan").current_objective(),
        )
        self.assertFalse(restored.stage_resolution_pending())

    async def test_runtime_snapshot_round_trips_every_scene_phase(self) -> None:
        for expected_phase, transitions in (
            (ScenePhase.BRIEFING, 0),
            (ScenePhase.PRIVATE_REVEAL, 1),
            (ScenePhase.INVESTIGATION, 2),
        ):
            dm = build_engine()
            await dm.init_game(
                "fog_harbor_clocktower",
                "shen_zhiwei",
                "deduction",
            )
            for _ in range(transitions):
                await dm.advance_scene_phase()
            restored = build_engine()
            restored_state = await restored.init_game(
                "fog_harbor_clocktower",
                "shen_zhiwei",
                "deduction",
            )
            restored.restore_runtime_snapshot(dm.export_runtime_snapshot())
            self.assertEqual(restored_state.scene_phase, expected_phase)

        hosting_dm = build_engine()
        await hosting_dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await hosting_dm.advance_scene_phase()
        await hosting_dm.advance_scene_phase()
        await hosting_dm.handle_whisper_action(
            {"type": "whisper_invite", "target_role_id": "gu_linchuan"}
        )
        hosting_dm.end_investigation("test")
        self.assertIsNone(
            hosting_dm.get_whisper_status()["active_target_role_id"]
        )

        restored_hosting = build_engine()
        restored_state = await restored_hosting.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        restored_hosting.restore_runtime_snapshot(
            hosting_dm.export_runtime_snapshot()
        )
        self.assertEqual(restored_state.scene_phase, ScenePhase.DM_HOSTING)
        self.assertTrue(restored_hosting.stage_resolution_pending())

    async def test_agents_autonomously_question_human_and_each_other(self) -> None:
        dm = build_engine()
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()

        self.assertIn(
            "专业可信度",
            dm.agent_pool.get("gu_linchuan").current_objective(),
        )

        state.autonomy_next_at = time.monotonic() - 1
        first = await dm.run_autonomous_turn()
        self.assertEqual([item["type"] for item in first], ["ai_proactive_speech"])
        self.assertEqual(first[0]["role_id"], "gu_linchuan")
        self.assertEqual(first[0]["target_role_id"], "shen_zhiwei")
        self.assertIn("沈知微", first[0]["content"])

        state.autonomy_next_at = time.monotonic() - 1
        second = await dm.run_autonomous_turn()
        self.assertEqual(
            [item["type"] for item in second],
            ["ai_proactive_speech", "ai_speech"],
        )
        self.assertEqual(second[0]["role_id"], "zhou_jiming")
        self.assertEqual(second[0]["target_role_id"], "xu_yanzhou")
        self.assertTrue(second[1]["proactive_response"])

        public_history_size = len(state.public_history)
        state.autonomy_next_at = time.monotonic() - 1
        third = await dm.run_autonomous_turn()
        self.assertEqual([item["type"] for item in third], ["agent_private_exchange"])
        self.assertEqual(third[0]["actor_role_id"], "xu_yanzhou")
        self.assertEqual(third[0]["target_role_id"], "gu_linchuan")
        self.assertEqual(len(state.public_history), public_history_size)
        self.assertEqual(state.investigation_metrics["whispers"], 1)
        private_audit = [
            item
            for item in state.audit_log
            if item["type"] == "agent_autonomous_private"
        ]
        self.assertEqual(len(private_audit), 1)
        self.assertIn("actor_content", private_audit[0])
        private_activity = [
            item
            for item in state.persistence_events
            if item.get("kind") == "activity"
            and item.get("channel") == "private"
        ]
        self.assertEqual(len(private_activity), 2)
        self.assertTrue(
            all(item["details"].get("content") for item in private_activity)
        )

    async def test_agent_can_override_dm_target_and_channel_suggestion(self) -> None:
        skills = SkillRegistry()
        skills.register(DeductionSkill)
        dm = DMEngine(
            ScriptLoader(BACKEND_ROOT / "resources" / "scripts"),
            AgentPool(),
            AutonomousChoiceFactory(),
            MechanicRegistry(),
            skills,
        )
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        state.autonomy_next_at = time.monotonic() - 1

        responses = await dm.run_autonomous_turn()

        self.assertEqual([item["type"] for item in responses], ["agent_private_exchange"])
        self.assertEqual(responses[0]["actor_role_id"], "gu_linchuan")
        self.assertEqual(responses[0]["target_role_id"], "xu_yanzhou")
        self.assertEqual(responses[0]["channel"], "private")

        reasoning = [
            event
            for event in state.persistence_events
            if event.get("kind") == "notebook"
            and event.get("section") == "reasoning"
            and event.get("role_id") == "gu_linchuan"
        ]
        self.assertEqual(len(reasoning), 1)
        self.assertIn("核对", reasoning[0]["content"])

    async def test_invalid_structured_action_has_no_gameplay_effect(self) -> None:
        skills = SkillRegistry()
        skills.register(DeductionSkill)
        dm = DMEngine(
            ScriptLoader(BACKEND_ROOT / "resources" / "scripts"),
            AgentPool(),
            InvalidActionFactory(),
            MechanicRegistry(),
            skills,
        )
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        dm.drain_persistence_events()
        state.autonomy_next_at = time.time() - 1

        responses = await dm.run_autonomous_turn()

        self.assertEqual(responses, [])
        self.assertEqual(state.public_history, [])
        self.assertFalse(
            any(
                event.get("kind") in {"activity", "notebook", "clue"}
                for event in state.persistence_events
            )
        )
        rejected = [
            event
            for event in state.audit_log
            if event.get("type") == "agent_action_rejected"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertIn("目标", rejected[0]["reason"])

    async def test_high_risk_speech_requires_semantic_review(self) -> None:
        skills = SkillRegistry()
        skills.register(DeductionSkill)
        dm = DMEngine(
            ScriptLoader(BACKEND_ROOT / "resources" / "scripts"),
            AgentPool(),
            BoundaryAttackFactory(),
            MechanicRegistry(),
            skills,
        )
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        dm.drain_persistence_events()

        human = await dm.handle_human_speech("顾临川，你怎么看现有证词？")
        replies = await dm.schedule_ai_turns(human)

        self.assertEqual(len(replies), 1)
        self.assertNotIn("完整剧本", replies[0]["content"])
        self.assertIn("没有足够证据", replies[0]["content"])
        purposes = [
            event["purpose"]
            for event in state.persistence_events
            if event.get("kind") == "agent_context"
        ]
        self.assertIn("semantic_boundary_review", purposes)
        self.assertIn("speech_retry", purposes)

    async def test_agent_provider_failure_skips_autonomous_action(self) -> None:
        skills = SkillRegistry()
        skills.register(DeductionSkill)
        dm = DMEngine(
            ScriptLoader(BACKEND_ROOT / "resources" / "scripts"),
            AgentPool(),
            FailingFactory(),
            MechanicRegistry(),
            skills,
        )
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        dm.drain_persistence_events()
        state.autonomy_next_at = time.time() - 1

        responses = await dm.run_autonomous_turn()

        self.assertEqual(responses, [])
        self.assertEqual(state.public_history, [])
        audits = [
            event
            for event in state.persistence_events
            if event.get("kind") == "agent_context"
        ]
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["status"], "failed")
        self.assertIn("provider unavailable", audits[0]["error"])

    async def test_human_answer_returns_to_agent_that_asked(self) -> None:
        dm = build_engine()
        state = await dm.init_game(
            "fog_harbor_clocktower",
            "shen_zhiwei",
            "deduction",
        )
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        state.autonomy_turn_count = 4
        state.autonomy_next_at = time.monotonic() - 1

        proactive = await dm.run_autonomous_turn()
        self.assertEqual(proactive[0]["role_id"], "zhou_jiming")
        self.assertEqual(proactive[0]["target_role_id"], "shen_zhiwei")

        human = await dm.handle_human_speech("我可以回答你刚才的问题。")
        replies = await dm.schedule_ai_turns(human)
        self.assertEqual([item["role_id"] for item in replies], ["zhou_jiming"])


if __name__ == "__main__":
    main()
