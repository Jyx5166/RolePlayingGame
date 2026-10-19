from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "app"))

from agent.context import AgentContextBroker
from agent.instance import AgentInstance
from dm.validator import SpeechValidator
from llm.echo import EchoLLM
from loader.script_loader import ScriptLoader
from main import create_app


class RoleAttributionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = json.loads((BACKEND / "tests/fixtures/role_attribution_regressions.json").read_text(encoding="utf-8"))["cases"]

    def case(self, script_id, capture_id=None):
        fixture = next(case for case in self.fixtures if case["script_id"] == script_id and (capture_id is None or case["capture_id"] == capture_id))
        script = ScriptLoader(BACKEND / "resources/scripts").load(script_id)
        role = next(role for role in script["roles"] if role["role_id"] == fixture["role_id"])
        agent = AgentInstance(role["role_id"], "Fixed policy", EchoLLM())
        agent.set_role_profile(role)
        agent.set_role_roster([{key: row[key] for key in ("role_id", "role_name", "public_identity")} for row in script["roles"]])
        for stage in range(1, fixture["stage"] + 1):
            agent.inject_info(role["stage_knowledge"][f"stage_{stage}"]["blocks"], stage)
        agent.set_current_stage(fixture["stage"])
        return fixture, script, agent, SpeechValidator(script)

    def test_captured_meng_lan_cannot_adopt_jiang_qiao_first_person_testimony(self):
        fixture, _, agent, validator = self.case("old_house_corridor")
        result = validator.validate_role_attribution(agent.role_id, fixture["stage"], fixture["speech"],
                                                    agent._memory_records() + fixture["public_sources"])
        self.assertFalse(result.passed, fixture["capture_id"])
        self.assertEqual(result.category, "role_attribution")
        quoted = '姜峤说：“我的鞋底登记的是横纹橡胶底。”这仍是他的证词，我没有核实。'
        self.assertTrue(validator.validate_role_attribution(agent.role_id, 3, quoted,
                        agent._memory_records() + fixture["public_sources"]).passed)
        self.assertTrue(validator.validate_role_attribution(agent.role_id, 3,
                        "20:12我经过北回廊门口时看见裴砚的长木箱。", agent._memory_records()).passed)

    def test_captured_tao_wen_cannot_speak_under_ren_rui_name(self):
        fixture, _, agent, validator = self.case("last_train")
        result = validator.validate_role_attribution(agent.role_id, fixture["stage"], fixture["speech"], agent._memory_records())
        self.assertFalse(result.passed, fixture["capture_id"])
        self.assertEqual(result.category, "role_attribution")
        for speech in ("我是陶闻，我没有拿过那把锤子。", '任瑞说：“我没有杀人。”这不是我的亲历。'):
            self.assertTrue(validator.validate_role_attribution(agent.role_id, 4, speech, agent._memory_records()).passed)

    def test_captured_chen_cheng_cannot_call_unsupported_handover_verified(self):
        fixture, _, agent, validator = self.case("deep_sea_echo")
        result = validator.validate_role_attribution(agent.role_id, fixture["stage"], fixture["speech"], agent._memory_records())
        self.assertFalse(result.passed, fixture["capture_id"])
        self.assertEqual(result.category, "unsupported_personal_action")
        # The real authorized memory contains emergency-bag delivery, not key delivery.
        grounded = "我能确认的事实如下：21:50我送应急包到驾驶台，22:00后返回医务间。"
        self.assertTrue(validator.validate_role_attribution(agent.role_id, 3, grounded, agent._memory_records()).passed)
        # Stating a new positive transfer as one's claim is not a source.
        lie = "我声称21:50把应急总钥匙交给陆潮；这只是我的说法。"
        self.assertFalse(validator.validate_role_attribution(agent.role_id, 3, lie, agent._memory_records()).passed)
        own = {"kind": "role_knowledge", "owner_role_id": agent.role_id, "first_person_role_id": agent.role_id,
               "stage": 1, "content": "你曾把应急总钥匙交给陆潮。"}
        self.assertTrue(validator.validate_role_attribution(agent.role_id, 3,
                        "我能确认的事实如下：我把应急总钥匙交给陆潮。", [own]).passed)

    def test_committed_own_action_or_named_scene_evidence_can_support_a_handover(self):
        _, _, agent, validator = self.case("deep_sea_echo")
        content = "我能确认的事实如下：我把应急总钥匙交给陆潮。"
        action = {"kind": "observed_action", "actor_role_id": agent.role_id, "event_verified": True,
                  "stage": 1, "content": "你把应急总钥匙交给陆潮。"}
        clue = {"kind": "search_fact", "owner_role_id": agent.role_id, "stage": 1,
                "content": "现场记录显示：陈澄把应急总钥匙交给陆潮。"}
        for record in (action, clue):
            self.assertTrue(validator.validate_role_attribution(agent.role_id, 3, content, [record]).passed)
        foreign = {**action, "actor_role_id": "lu_chao"}
        self.assertFalse(validator.validate_role_attribution(agent.role_id, 3, content, [foreign]).passed)
        testimony = {**clue, "kind": "testimony", "speaker_role_id": "lu_chao"}
        self.assertFalse(validator.validate_role_attribution(agent.role_id, 3, content, [testimony]).passed)

    def test_live_retest_chen_cannot_reframe_old_self_testimony_as_experience(self):
        fixture, _, agent, validator = self.case("deep_sea_echo", "df6d3c3dd9554f21ac835e0fc4cc1d01")
        result = validator.validate_role_attribution(agent.role_id, 3, fixture["speech"],
                        agent._memory_records() + fixture["public_sources"])
        self.assertFalse(result.passed, fixture["capture_id"])
        self.assertEqual(result.category, "unsupported_personal_action")
        for prefix in ("我亲自经历的是：", "", "我声称", "我本人回忆："):
            speech = prefix + "我把应急门钥匙交给陆潮。"
            self.assertFalse(validator.validate_role_attribution(agent.role_id, 3, speech, fixture["public_sources"]).passed)

    def test_action_negation_uncertainty_plans_and_other_actors_remain_allowed(self):
        _, _, agent, validator = self.case("deep_sea_echo")
        for speech in ("我没有把应急门钥匙交给陆潮。", "我无法确认是否把应急门钥匙交给陆潮。",
                       "我打算把应急门钥匙交给陆潮。", "如果我把应急门钥匙交给陆潮，门锁就值得复查。",
                       "我看见陆潮把应急门钥匙交给苏闻。", "他说：我把应急门钥匙交给陆潮。",
                       "我只在旁边看着，后来他把应急门钥匙交给陆潮。",
                       "我可以谎称把应急门钥匙交给陆潮，但我没有这么做。"):
            self.assertTrue(validator.validate_role_attribution(agent.role_id, 3, speech, agent._memory_records()).passed, speech)
        foreign_action_in_own_knowledge = {"kind":"role_knowledge", "owner_role_id":agent.role_id,
            "first_person_role_id":agent.role_id, "stage":1, "content":"你看见沈珂把应急门钥匙交给陆潮。"}
        self.assertFalse(validator.validate_role_attribution(agent.role_id, 3,
            "我把应急门钥匙交给陆潮。", [foreign_action_in_own_knowledge]).passed)

    def test_live_retest_meng_cannot_paraphrase_foreign_property_as_own(self):
        fixture, _, agent, validator = self.case("old_house_corridor", "ef0c1f1a90334e629d800b1410a94aed")
        records = agent._memory_records() + fixture["public_sources"]
        result = validator.validate_role_attribution(agent.role_id, 3, fixture["speech"], records)
        self.assertFalse(result.passed, fixture["capture_id"])
        self.assertEqual(result.category, "role_attribution")
        for speech in ('姜峤说：“我身上沾的红色不是血迹，是南档案房印泥。”',
                       "我身上的红色污点不是来自南档案房印泥。", "我身上的红色可能是南档案房印泥。"):
            self.assertTrue(validator.validate_role_attribution(agent.role_id, 3, speech, records).passed, speech)
        known = {"kind":"role_knowledge", "owner_role_id":agent.role_id, "first_person_role_id":agent.role_id,
                 "stage":1, "content":"你身上的红色污点来自南档案房印泥。"}
        self.assertTrue(validator.validate_role_attribution(agent.role_id, 3,
            "我身上沾的红色不是血迹，是南档案房印泥。", records+[known]).passed)

    def test_live_probe_shared_negative_is_not_exclusive_to_the_first_speaker(self):
        fixture, _, agent, validator = self.case("old_house_corridor", "8b5e0fa7d15f4d3a958dcf2eec3ca548")
        records = agent._memory_records() + fixture["public_sources"]
        self.assertTrue(validator.validate_role_attribution(agent.role_id, 3, fixture["speech"], records).passed)
        for speech in ("我当晚没有进过北回廊验收现场。", "我鞋底登记的不是横纹橡胶底。",
                       "我不确定当晚是否进过北回廊验收现场。"):
            self.assertTrue(validator.validate_role_attribution(agent.role_id, 3, speech, records).passed, speech)
        for speech in ("我鞋底登记的是横纹橡胶底。", "我身上沾的红色不是血迹，是南档案房印泥。"):
            self.assertFalse(validator.validate_role_attribution(agent.role_id, 3, speech, records).passed, speech)

    def test_quotation_marks_around_an_object_do_not_excuse_identity_theft(self):
        fixture, _, agent, validator = self.case("old_house_corridor")
        result = validator.validate_role_attribution(agent.role_id, 3,
            '我鞋底登记的是横纹橡胶底，旁边有个“木箱”。', agent._memory_records() + fixture["public_sources"])
        self.assertFalse(result.passed)
        ink = validator.validate_role_attribution(agent.role_id, 3,
            '我身上的红色污点来自南档案房印泥，不是血迹。', agent._memory_records() + fixture["public_sources"])
        self.assertFalse(ink.passed)

    def test_distinct_characters_can_share_a_general_intention_or_uncertainty(self):
        _, _, agent, validator = self.case("old_house_corridor")
        for speech in ("我听到你的询问了。我会说明自己亲自确认的情况，不替其他人作证。",
                       "我只能说明自己亲自确认的情况，不替其他人作证。",
                       "我不知道当时是否有人经过这里。", "我打算先核对现场记录再给出判断。",
                       "我没有亲眼看到案发的整个过程。"):
            testimony = {"kind": "testimony", "stage": 3, "speaker_role_id": "jiang_qiao",
                         "speaker_role_name": "姜峤", "content": speech}
            self.assertTrue(validator.validate_role_attribution(agent.role_id, 3, speech, [testimony]).passed, speech)

    def test_foreign_transfer_or_quoted_claim_is_not_a_personal_action(self):
        _, _, agent, validator = self.case("deep_sea_echo")
        for content in ('我能确认的事实如下：陆潮说：“我把应急总钥匙交给陈澄。”',
                        "我不能确认是否把应急总钥匙交给陆潮。", "我没有把应急总钥匙交给陆潮。"):
            self.assertTrue(validator.validate_role_attribution(agent.role_id, 3, content, agent._memory_records()).passed, content)

    def test_assistant_history_is_a_quoted_source_and_not_the_current_actors_turn(self):
        broker = AgentContextBroker(["meng_lan", "jiang_qiao"])
        context = broker.build(role_id="meng_lan", stage=3, channel="public", purpose="reply",
            public_history=[{"role": "assistant", "actor_role_id": "jiang_qiao", "actor_role_name": "姜峤",
                             "source_key": "observed-event:3:46", "content": "我的鞋底登记的是横纹橡胶底。"}])
        message = context.to_llm_messages()[0]
        self.assertEqual(message["role"], "user")
        data = json.loads(message["content"].split("\n", 1)[1])
        self.assertEqual(data["speaker_role_id"], "jiang_qiao")
        self.assertEqual(data["epistemic_status"], "unverified_testimony")
        self.assertEqual(data["quote"], "我的鞋底登记的是横纹橡胶底。")

    def test_memory_owner_is_not_speaker_and_speech_is_not_a_verified_action(self):
        _, _, agent, _ = self.case("old_house_corridor")
        agent.remember_private_exchange(3, "姜峤", "received", "我把钥匙交给了别人。", counterpart_role_id="jiang_qiao")
        agent.observe_event({"source_key": "speech", "stage": 3, "channel": "public", "event_type": "public_speech",
                             "actor_role_id": "jiang_qiao", "actor_role_name": "姜峤", "content": "我已经搜过这里。"})
        agent.observe_event({"source_key": "search", "stage": 3, "channel": "public_action", "event_type": "search",
                             "actor_role_id": "jiang_qiao", "actor_role_name": "姜峤", "content": "前往现场搜证；结果私有。"})
        agent.restore_runtime_state(agent.export_runtime_state())
        records = agent._memory_records()
        private = next(row for row in records if row.get("direction") == "received")
        self.assertEqual(private["owner_role_id"], "meng_lan")
        self.assertEqual(private["first_person_role_id"], "jiang_qiao")
        speech = next(row for row in records if row["source_key"] == "speech")
        action = next(row for row in records if row["source_key"] == "search")
        self.assertEqual(speech["kind"], "testimony")
        self.assertFalse(speech["statement_verified"])
        self.assertEqual(action["epistemic_status"], "verified_action_receipt")
        self.assertFalse(action["statement_verified"])


class ArchiveAttributionTest(unittest.IsolatedAsyncioTestCase):
    async def test_index_and_paged_read_preserve_speaker_and_refresh_old_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / "test.db")
            service = app.state.game_service
            user = service.store.register("attribution_owner", "secret12")["user"]["id"]
            script = ScriptLoader(BACKEND / "resources/scripts").load("fog_harbor_clocktower")
            game = service.store.prepare_game(user, script, "builtin", "v")
            await service.activate_game(user, game["id"], "shen_zhiwei")
            _, dm = await service.get_engine(user, game["id"])
            agent = dm.agent_pool.get("gu_linchuan")
            agent.remember_private_exchange(1, "周既明", "received", "我把钥匙交给了别人。",
                                            source_key="quoted-handover", counterpart_role_id="zhou_jiming")
            record = next(row for row in agent._memory_records() if row["source_key"] == "quoted-handover")
            old = {key: value for key, value in record.items() if key not in {"speaker_role_id", "speaker_role_name", "first_person_role_id"}}
            archive = service.memory_archive
            archive.sync(agent.runtime_scope, [old])
            archive.sync(agent.runtime_scope, [record])
            entry = next(row for row in archive.index(agent.runtime_scope, 1, "钥匙") if row["source_key"] == "quoted-handover")
            self.assertEqual(entry["speaker_role_id"], "zhou_jiming")
            read = archive.retrieve(agent.runtime_scope, 1, memory_id=entry["memory_id"], chunk_chars=5)["records"][0]
            self.assertEqual(read["first_person_role_id"], "zhou_jiming")
            self.assertEqual(read["certainty"], "unverified")
            self.assertFalse(read["statement_verified"])
            self.assertFalse(read["complete"])

    async def test_native_public_entry_rejects_identity_swap_before_any_model_review(self):
        from types import SimpleNamespace
        from tools.contracts import NoteArguments
        from tools.domain import GameActions, DomainActionError
        from runtime.contracts import RuntimeScope
        fixture = json.loads((BACKEND / "tests/fixtures/role_attribution_regressions.json").read_text(encoding="utf-8"))["cases"][1]
        script = ScriptLoader(BACKEND / "resources/scripts").load("last_train")
        state = SimpleNamespace(ai_role_ids=[fixture["role_id"]], record_sequence=0, current_stage_num=4, public_history=[])
        agent = SimpleNamespace(_memory_records=lambda: [])
        dm = SimpleNamespace(_require_state=lambda: state, _require_permission=lambda: object(),
            _require_investigation_action=lambda action: None, _require_validator=lambda: SpeechValidator(script),
            agent_pool=SimpleNamespace(get=lambda role_id: agent))
        scope = RuntimeScope(game_id=1, run_id="r", context_id="c", agent_instance_id="i", actor_kind="role", actor_role_id=fixture["role_id"])
        actions = GameActions(dm)
        with patch.object(actions, "_validate_content", new=AsyncMock()) as review:
            with self.assertRaises(DomainActionError):
                await actions.role_tool(scope, "speak_public", NoteArguments(content="任瑞：我没有杀人。"))
        review.assert_not_awaited()
        self.assertEqual(state.public_history, [])


if __name__ == "__main__":
    unittest.main()
