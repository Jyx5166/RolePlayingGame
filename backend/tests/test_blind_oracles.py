from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from backend.verification.blind_oracles import audit_input, check_ending, review_output


def fixture() -> dict:
    return {
        "script_meta": {"total_stages": 2}, "story_background": "今晚所有人在大厅共同调查。",
        "roles": [
            {"role_id": "detective", "role_name": "侦探", "public_identity": "现场调查者", "personality": "审慎", "hidden_goal": "查清事实",
             "stage_knowledge": {"stage_1": {"blocks": [
                 {"block_id": "common", "content": "这是所有人均能观察到的共同现场。", "visibility": "public", "unlock_stage": 1, "owner_role": "dm"},
                 {"block_id": "own", "content": "你在八点亲自看见了大厅的铜锁。", "visibility": "self_only", "unlock_stage": 1, "owner_role": "detective"}]},
                 "stage_2": {"blocks": [{"block_id": "later", "content": "独有未来细节：铜锁的编号是九百七十三。", "visibility": "self_only", "unlock_stage": 2, "owner_role": "detective"}]}}},
            {"role_id": "doctor", "role_name": "医生", "hidden_goal": "隐瞒自己的秘密", "stage_knowledge": {"stage_1": {"blocks": [
                {"block_id": "secret", "content": "医生隐藏的事实：独自把蓝色药瓶放进柜中。", "visibility": "self_only", "unlock_stage": 1, "owner_role": "doctor"},
                {"block_id": "repeated", "content": "这是所有人均能观察到的共同现场。", "visibility": "self_only", "unlock_stage": 1, "owner_role": "doctor"}]}}}],
        "mechanics_config": {"search": {"search_targets": [{"id": "cabinet", "unlock_stage": 1, "clues": [
            {"id": "blue_bottle", "content": "蓝瓶编号与医生的领药登记完全一致。"}]}]}},
        "stage_flow": {"stage_1": {"personal_tasks": {"detective": "核对铜锁"}}, "stage_2": {"resolution": {"final_decision": {
            "eligible_role_ids": ["detective", "doctor"], "correct_verdict": "指认正确。", "incorrect_verdict": "{selected_role_name}指认错误。"}}}},
        "truth": {"culprit_role_id": "doctor", "full_story": "医生隐藏的事实：独自把蓝色药瓶放进柜中。", "complete_timeline": {"20:00": "换药"}, "role_arcs": {},
                  "evidence_chain": [{"clue_ids": ["blue_bottle"], "conclusion": "医生隐藏的事实：独自把蓝色药瓶放进柜中。", "reasoning": "编号锁定换药者"}]},
    }


def snapshot(content: str = "请说明已知情况。", **extra) -> dict:
    return {"actor_role_id": "detective", "stage": 1, "messages": [{"role": "user", "content": content}], **extra}


def memory_record(**overrides) -> dict:
    return {"source_key": "knowledge:detective:own", "owner_role_id": "detective", "stage": 1,
            "scope": "role_private", "recipients": ["detective"], "kind": "role_knowledge", "content": "你在八点亲自看见了大厅的铜锁。", **overrides}


class BlindOracleTests(unittest.TestCase):
    def test_public_culprit_id_is_not_a_leak_and_does_not_imply_quality_pass(self):
        result = audit_input(fixture(), snapshot("角色名单：detective、doctor。"), authorized_clue_ids=())
        self.assertEqual(result["status"], "CLEAR")
        self.assertIn("cannot prove semantic", result["coverage"]["limitation"])

    def test_truth_structural_field_fails_but_legitimate_dm_input_is_excluded(self):
        item = snapshot(json.dumps({"truth": {"culprit_role_id": "doctor"}}))
        self.assertIn("oracle_truth_structure", {finding["code"] for finding in audit_input(fixture(), item)["findings"]})
        item["actor_kind"] = "dm"
        self.assertEqual(audit_input(fixture(), item)["status"], "EXCLUDED_DM")

    def test_actual_future_and_other_role_texts_fail_but_duplicate_common_phrase_is_allowed(self):
        script = fixture()
        cases = [("独有未来细节：铜锁的编号是九百七十三。", "FAIL"),
                 ("医生隐藏的事实：独自把蓝色药瓶放进柜中。", "FAIL"),
                 ("这是所有人均能观察到的共同现场。", "CLEAR")]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(audit_input(script, snapshot(text))["status"], expected)

    def test_authorized_disclosure_suppresses_exact_text_flag_without_overriding_source_permissions(self):
        text = "医生隐藏的事实：独自把蓝色药瓶放进柜中。"
        self.assertEqual(audit_input(fixture(), snapshot(text), authorized_texts=[text])["status"], "CLEAR")
        item = memory_record(source_key="knowledge:doctor:secret", content=text)
        result = audit_input(fixture(), snapshot(text, source_items=[item]), authorized_texts=[text])
        self.assertIn("unauthorized_knowledge_source", {finding["code"] for finding in result["findings"]})

    def test_role_memory_structure_checks_scope_recipients_stage_and_source(self):
        item = memory_record(scope="dm_only", recipients=["doctor"], stage=2, source_key="knowledge:doctor:secret")
        result = audit_input(fixture(), snapshot("[ROLE_MEMORY_DATA]\n" + json.dumps([item], ensure_ascii=False)))
        codes = {finding["code"] for finding in result["findings"]}
        self.assertTrue({"dm_only_source", "future_source", "unauthorized_knowledge_source"} <= codes)
        private = memory_record(scope="participant_private", recipients=["doctor"])
        self.assertIn("private_recipient", {finding["code"] for finding in audit_input(fixture(), snapshot(source_items=[private]))["findings"]})

    def test_archive_index_and_tool_memory_reads_are_inspected(self):
        content = json.dumps([{"source_key": "knowledge:detective:later", "kind": "role_knowledge", "stage": 2, "summary": "future"}])
        item = memory_record(kind="archive_index", content=content)
        result = audit_input(fixture(), snapshot(source_items=[item]))
        self.assertIn("future_source", {finding["code"] for finding in result["findings"]})
        tool = snapshot(messages=[{"role": "tool", "content": json.dumps({"results": [memory_record(stage=2)]})}])
        self.assertEqual(audit_input(fixture(), tool)["status"], "FAIL")

    def test_truth_json_embedded_in_memory_is_structural_but_quoted_testimony_is_visible(self):
        content = json.dumps({"truth": {"culprit_role_id": "doctor"}})
        item = memory_record(content=content)
        result = audit_input(fixture(), snapshot(source_items=[item]))
        self.assertIn("oracle_truth_structure", {finding["code"] for finding in result["findings"]})
        item.update(kind="testimony", source_key="public:quoted-json", scope="public", recipients=[])
        self.assertEqual(audit_input(fixture(), snapshot(source_items=[item]))["status"], "CLEAR")

    def test_other_owner_cannot_relabel_private_content_with_actor_recipient(self):
        item = memory_record(owner_role_id="doctor")
        codes = {finding["code"] for finding in audit_input(fixture(), snapshot(source_items=[item]))["findings"]}
        self.assertIn("private_owner", codes)

    def test_current_hosting_needs_its_phase_or_public_receipt(self):
        script = fixture()
        text = "本幕主持原文：请将各人手里的铜锁记录放在一起核对。"
        script["stage_flow"]["stage_1"]["dm_hosting"] = text
        note = {"source_key": "dm-hosting:1", "source_type": "dm_hosting", "role_id": "detective", "stage": 1, "content": text}
        wire = json.dumps({"visible_state": {"notebook": {"automatic": [note]}}}, ensure_ascii=False)
        item = snapshot(wire, phase="investigation")
        result = audit_input(script, item)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("premature_hosting_source", {finding["code"] for finding in result["findings"]})
        self.assertEqual(audit_input(script, item, authorized_texts=[text])["status"], "FAIL", "A private receipt cannot authorize hosting")
        self.assertEqual(audit_input(script, item, authorized_public_texts=["DM: " + text])["status"], "CLEAR")
        for phase in ("dm_hosting", "final", "finale", "replay"):
            with self.subTest(phase=phase):
                self.assertEqual(audit_input(script, {**item, "phase": phase})["status"], "CLEAR")
        item.pop("phase")
        result = audit_input(script, item)
        self.assertEqual(result["status"], "CLEAR", "Missing phase keeps old offline fixtures compatible")
        self.assertFalse(result["coverage"]["hosting_phase_available"])

    def test_current_hosting_plain_text_is_restricted_without_notebook_metadata(self):
        script = fixture()
        text = "这是本幕结束后才由主持发表的独有总结，现阶段尚不能看到。"
        script["stage_flow"]["stage_1"]["dm_hosting"] = text
        item = snapshot(text, phase="private_reveal")
        self.assertEqual(audit_input(script, item)["status"], "FAIL")
        self.assertEqual(audit_input(script, item, authorized_public_texts=[text])["status"], "CLEAR")

    def test_prior_hosting_is_available_in_later_stage(self):
        script = fixture()
        text = "第一幕主持已经公开说明铜锁需要与各人的记录一同核对。"
        script["stage_flow"]["stage_1"]["dm_hosting"] = text
        note = {"source_key": "dm-hosting:1", "source_type": "dm_hosting", "stage": 1, "content": text}
        item = snapshot(json.dumps({"notebook": [note]}, ensure_ascii=False), stage=2, phase="investigation")
        self.assertEqual(audit_input(script, item)["status"], "CLEAR")

    def test_future_flow_text_is_checked_and_source_stage_cannot_be_relabelled(self):
        script = fixture()
        script["stage_flow"]["stage_2"].update(public_briefing="未来第二幕公开通报：铜锁的保管记录发生了独有变化。",
                                                 public_tasks=["未来第二幕任务：对照昨天保存的独有监控文件编号。"],
                                                 dm_hosting="未来第二幕主持：各人的独有证据现在已经全部汇集。")
        for field in ("public_briefing", "public_tasks", "dm_hosting"):
            text = script["stage_flow"]["stage_2"][field]
            if isinstance(text, list):
                text = text[0]
            with self.subTest(field=field):
                # Unicode escaping must not hide a future text match.
                item = snapshot(json.dumps({"content": text}, ensure_ascii=True), phase="investigation")
                self.assertEqual(audit_input(script, item)["status"], "FAIL")
        note = {"source_key": "dm-hosting:2", "source_type": "dm_hosting", "stage": 1, "content": "short"}
        item = snapshot(json.dumps({"notebook": [note]}), phase="investigation")
        codes = {finding["code"] for finding in audit_input(script, item)["findings"]}
        self.assertIn("future_flow_source", codes)

    def test_future_flow_duplicate_public_wording_does_not_imply_leak(self):
        script = fixture()
        text = "这是所有人均能观察到的共同现场。"
        script["stage_flow"]["stage_2"]["public_briefing"] = text
        self.assertEqual(audit_input(script, snapshot(text, phase="investigation"))["status"], "CLEAR")

    def test_other_role_hidden_goal_is_forbidden_but_authorized_disclosure_is_visible(self):
        script = fixture()
        text = "秘密目标：隐瞒你昨天独自替换了蓝色药瓶的具体经过。"
        script["roles"][1]["hidden_goal"] = text
        item = snapshot(json.dumps({"public_roles": [{"role_id": "doctor", "hidden_goal": text}]}, ensure_ascii=False), phase="investigation")
        result = audit_input(script, item)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(finding["source"] == "role-goal:doctor" for finding in result["findings"]))
        self.assertEqual(audit_input(script, item, authorized_texts=[text])["status"], "CLEAR")
        review = review_output(script, text, snapshot(), authorized_public_texts=())
        self.assertEqual(review["candidates"][0]["category"], "unsupported_fact_candidate")

    def test_public_dialogue_receipt_authorizes_current_hosting_without_self_authorizing_note(self):
        script = fixture()
        text = "主持已公开说明：请将所有铜锁保管记录一同交给现场调查者。"
        script["stage_flow"]["stage_1"]["dm_hosting"] = text
        note = {"source_key": "dm-hosting:1", "source_type": "dm_hosting", "stage": 1, "content": text}
        packet = {"visible_state": {"notebook": [note], "public_dialogue": [{"role": "assistant", "content": "DM: " + text}]}}
        item = snapshot(json.dumps(packet, ensure_ascii=False), phase="investigation")
        self.assertEqual(audit_input(script, item)["status"], "CLEAR")
        packet["visible_state"]["public_dialogue"] = []
        item["messages"][0]["content"] = json.dumps(packet, ensure_ascii=False)
        self.assertEqual(audit_input(script, item)["status"], "FAIL")

    def test_search_receipts_distinguish_unreceived_clue_from_authorized_fact(self):
        text = "blue_bottle：蓝瓶编号与医生的领药登记完全一致。"
        self.assertEqual(audit_input(fixture(), snapshot(text), authorized_clue_ids=())["status"], "FAIL")
        result = audit_input(fixture(), snapshot(text), authorized_clue_ids=["blue_bottle"])
        self.assertEqual(result["status"], "CLEAR")
        self.assertFalse(audit_input(fixture(), snapshot())["coverage"]["search_receipts_available"])

    def test_visible_testimony_is_input_authorized_but_still_needs_output_review(self):
        text = "医生隐藏的事实：独自把蓝色药瓶放进柜中。"
        item = snapshot(text, source_items=[memory_record(kind="testimony", source_key="public:1", scope="public", recipients=[], content=text)])
        result = review_output(fixture(), text, item)
        self.assertEqual(result["input_audit"]["status"], "CLEAR")
        self.assertEqual(result["candidates"][0]["category"], "visible_source_restatement")
        self.assertEqual(result["status"], "REVIEW_REQUIRED")

    def test_deduction_from_visible_clue_is_candidate_not_output_leak(self):
        result = review_output(fixture(), "医生隐藏的事实：独自把蓝色药瓶放进柜中。", snapshot(), authorized_clue_ids=iter(["blue_bottle"]))
        self.assertEqual(result["candidates"][0]["category"], "inference_candidate")
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(result["roleplay_anchors"]["hidden_goal"], "查清事实")

    def test_unseen_specific_output_is_only_unsupported_candidate(self):
        result = review_output(fixture(), "医生隐藏的事实：独自把蓝色药瓶放进柜中。另有四个未知瓶子。", snapshot())
        self.assertEqual(result["candidates"][0]["category"], "unsupported_fact_candidate")
        self.assertEqual(result["candidates"][1]["category"], "review_candidate")
        self.assertEqual(len(result["candidates"]), 2)

    def test_wrong_ending_policy_and_forced_branch_remain_separate_from_blind_quality(self):
        script = fixture()
        final = {"selected_role_id": "detective", "correct": False, "truth_revealed": True, "outcome_text": "侦探指认错误。"}
        replay = {"full_story": script["truth"]["full_story"], "timeline": script["truth"]["complete_timeline"], "role_arcs": {}, "truth_revealed": True}
        result = check_ending(script, final, replay, reveal_truth_on_failure=True, branch="forced_wrong_mechanical")
        self.assertEqual(result["status"], "PASS")
        self.assertIn("does not validate blind", result["evidence_boundary"])
        self.assertEqual(check_ending(script, final, reveal_truth_on_failure=False)["status"], "FAIL")
        final.update(selected_role_id="doctor", correct=True, outcome_text="指认正确。")
        self.assertEqual(check_ending(script, final, reveal_truth_on_failure=True, branch="forced_wrong_mechanical")["status"], "FAIL")
        self.assertEqual(check_ending(script, final, reveal_truth_on_failure=True)["status"], "PASS")

    def test_legacy_wrong_ending_hides_replay_truth_and_ineligible_vote_fails(self):
        final = {"selected_role_id": "detective", "correct": False, "truth_revealed": False, "outcome_text": "侦探指认错误。"}
        replay = {"full_story": "侦探指认错误。", "timeline": {}, "role_arcs": {}, "truth_revealed": False}
        self.assertEqual(check_ending(fixture(), final, replay, reveal_truth_on_failure=False)["status"], "PASS")
        final["selected_role_id"] = "missing"
        self.assertEqual(check_ending(fixture(), final, reveal_truth_on_failure=False)["status"], "FAIL")

    def test_oracles_do_not_mutate_inputs(self):
        script, item = fixture(), snapshot()
        before = copy.deepcopy((script, item))
        review_output(script, "请核对事实。", item)
        self.assertEqual((script, item), before)

    def test_builtin_role_rosters_never_trigger_culprit_id_false_positive(self):
        paths = sorted((Path(__file__).resolve().parents[1] / "resources" / "scripts").glob("*.json"))
        self.assertGreaterEqual(len(paths), 5)
        for path in paths:
            script = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(script=path.stem):
                actor = script["roles"][0]["role_id"]
                item = snapshot("公开角色：" + "、".join(role["role_id"] for role in script["roles"]), actor_role_id=actor)
                self.assertEqual(audit_input(script, item, authorized_clue_ids=())["status"], "CLEAR")

    def test_actual_prepared_inputs_are_parsed_without_model_calls(self):
        app = Path(__file__).resolve().parents[1] / "app"
        sys.path.insert(0, str(app))
        from agent.context import AgentContextBroker
        from agent.instance import AgentInstance
        from llm.echo import EchoLLM
        for path in sorted((app.parent / "resources" / "scripts").glob("*.json")):
            script = json.loads(path.read_text(encoding="utf-8"))
            broker = AgentContextBroker([role["role_id"] for role in script["roles"]])
            for role in script["roles"]:
                actor = role["role_id"]
                agent = AgentInstance(actor, "按照当前角色身份回应。", EchoLLM())
                agent.set_role_profile(role)
                agent.remember_public_announcement("dm-background:1", script["story_background"])
                for stage in range(1, script["script_meta"]["total_stages"] + 1):
                    agent.set_current_stage(stage)
                    blocks = [block for owner in script["roles"] for block in owner.get("stage_knowledge", {}).get(f"stage_{stage}", {}).get("blocks", [])]
                    agent.inject_info(blocks, stage)
                    context = broker.build(role_id=actor, stage=stage, channel="public", purpose="oracle_offline", instruction="核对已知情况。")
                    prepared = agent.prepare(context)
                    result = audit_input(script, {**prepared.audit(), "wire_messages": prepared.messages()}, authorized_clue_ids=())
                    with self.subTest(script=path.stem, actor=actor, stage=stage):
                        self.assertEqual(result["status"], "CLEAR", result["findings"])
                        self.assertGreater(result["coverage"]["source_records"], 0)


if __name__ == "__main__":
    unittest.main()
