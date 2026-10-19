from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "app"))

from authoring_validation import inspect_authoring
from loader.script_loader import ScriptLoader


def authoring_fixture() -> dict:
    """A small playable two-act mystery with three mechanically obtainable clues."""
    script = {
        "schema_version": "1.0",
        "script_meta": {"script_id": "sealed_letter", "title": "失落的封蜡", "total_stages": 2,
                        "supported_skills": ["deduction"]},
        "story_background": "旧宅主人失踪，信使秦岚与修复师陈默被请来核对一封遗信。",
        "opening": {"title": "开幕 · 旧约", "content": "秦岚曾为旧宅送信，陈默负责修复纸张。今夜两人因一封二十年前的遗信重逢，主人却没有赴约。"},
        "roles": [{"role_id": role_id, "role_name": name, "human_playable": True,
                   "public_identity": identity,
                   "stage_knowledge": {f"stage_{stage}": {"blocks": [{
                       "block_id": f"{role_id}_{stage}", "type": "memory", "visibility": "self_only",
                       "owner_role": role_id, "unlock_stage": stage,
                       "content": f"我是{name}。这是第{stage}次核对旧信时才想起的私人经历。",
                   }]} for stage in (1, 2)}}
                  for role_id, name, identity in (("qin", "秦岚", "旧宅信使"), ("chen", "陈默", "纸张修复师"))],
        "mechanics_enabled": ["search"],
        "mechanics_config": {"search": {"ap_per_stage": [1, 1], "search_targets": [
            {"id": "desk", "unlock_stage": 1, "clues": [{"id": "letter", "content": "原信的日期清晰可见。"}]},
            {"id": "shelf", "unlock_stage": 1, "clues": [{"id": "seal", "content": "封蜡边缘留有修复粉末。"}]},
            {"id": "cabinet", "unlock_stage": 2, "clues": [{"id": "receipt", "content": "领料簿只有陈默的签名。"}]},
        ]}},
        "stage_flow": {},
        "truth": {"culprit_role_id": "chen", "full_story": "陈默提前拿走了旧信，并以新的封蜡掩饰拆封痕迹。领料簿、原信日期和粉末残留共同证明篡改发生在陈默修复期间。秦岚虽然与主人有旧怨，仍按约送到了原件。",
                  "evidence_chain": [{"conclusion": "封蜡在修复期间被替换。", "clue_ids": ["letter", "seal", "receipt"],
                                      "reasoning": "原信日期早于修复，封蜡粉末与仅由陈默领取的修复材料一致，排除送信前篡改。"}]},
    }
    for stage in (1, 2):
        resolution = {"title": "本幕核对", "metric": {"key": "facts", "label": "已核事实", "unit": "条"},
                      "scoring_rules": [{"label": "公开证据", "event_types": ["public_speech"], "points_per_event": 1, "max_points": 2}]}
        if stage == 2:
            resolution["final_decision"] = {"prompt": "谁替换了封蜡？", "eligible_role_ids": ["qin", "chen"],
                                             "correct_verdict": "指认证据一致。", "incorrect_verdict": "请复核证据。"}
        script["stage_flow"][f"stage_{stage}"] = {
            "title": f"第 {stage} 幕", "public_briefing": f"第{stage}次调查开始，众人围绕新发现的信件核对记录。",
            "public_tasks": ["核对原件与证词"], "investigation": {"enabled_actions": ["public_speech", "search"]},
            "resolution": resolution, "dm_hosting": "主持人请各位核对已经公开的证据，再决定如何解释差异。",
        }
    return script


def authoring_plan() -> dict:
    return {"timeline_events": [
        {"event_id": "delivery", "time": "20:10", "role_ids": ["qin"], "location": "前厅", "event": "交付原信。"},
        {"event_id": "repair", "time": "20:10", "role_ids": ["chen"], "location": "修复室", "event": "领取修复材料。"},
    ], "clue_links": [
        {"clue_id": "letter", "requires_clue_ids": [], "available_stage": 1, "conclusion": "原信早已存在。"},
        {"clue_id": "seal", "requires_clue_ids": ["letter"], "available_stage": 1, "conclusion": "封蜡材料与原信年代不合。"},
        {"clue_id": "receipt", "requires_clue_ids": ["seal"], "available_stage": 2, "conclusion": "领料记录可核对修复者。"},
    ]}


class AuthoringValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.script, self.plan = authoring_fixture(), authoring_plan()

    def failed(self, report: dict, code: str | None = None) -> list[dict]:
        self.assertFalse(report["passed"], report)
        self.assertTrue(report["errors"])
        return [check for check in report["checks"] if check["status"] == "failed" and (code is None or check["code"] == code)]

    def test_valid_fixture_passes_real_loader_and_report_without_mutation(self) -> None:
        ScriptLoader(".").validate(self.script)
        before = deepcopy((self.script, self.plan))
        report = inspect_authoring(self.script, self.plan)
        self.assertTrue(report["passed"], report)
        self.assertEqual([], report["errors"])
        self.assertEqual(before, (self.script, self.plan))
        self.assertEqual(4, sum(check["code"] == "role_readability" for check in report["checks"]))
        self.assertTrue(any("尚未证明" in warning for warning in report["warnings"]))

    def test_old_import_without_opening_or_private_body_remains_accepted_with_warnings(self) -> None:
        self.script.pop("opening")
        self.script["roles"][0]["stage_knowledge"]["stage_2"]["blocks"] = []
        ScriptLoader(".").validate(self.script)
        report = inspect_authoring(self.script)
        self.assertTrue(report["passed"], report)
        self.assertTrue(any(check["code"] == "opening_independent" and check["status"] == "warning" for check in report["checks"]))
        self.assertTrue(any(check["code"] == "role_readability" and check["status"] == "warning" for check in report["checks"]))
        self.assertFalse(any(check["code"] in ("timeline_plan", "clue_dependencies") and check["status"] == "passed" for check in report["checks"]))

    def test_generated_script_requires_an_independent_opening(self) -> None:
        self.script.pop("opening")
        self.assertTrue(self.failed(inspect_authoring(self.script, self.plan), "opening_independent"))

    def test_opening_copied_from_first_act_is_not_independent_despite_punctuation(self) -> None:
        self.script["opening"]["content"] = self.script["stage_flow"]["stage_1"]["public_briefing"].replace("，", "，\n ")
        self.assertTrue(self.failed(inspect_authoring(self.script, self.plan), "opening_independent"))

    def test_future_locked_private_text_cannot_count_as_current_role_book(self) -> None:
        self.script["roles"][0]["stage_knowledge"]["stage_1"]["blocks"][0]["unlock_stage"] = 2
        ScriptLoader(".").validate(self.script)
        checks = self.failed(inspect_authoring(self.script, self.plan), "role_readability")
        self.assertEqual("roles.0.stage_knowledge.stage_1", checks[0]["path"])

    def test_public_or_dm_only_text_cannot_replace_a_private_role_book(self) -> None:
        for visibility, owner in (("public", "*"), ("dm_only", "dm")):
            with self.subTest(visibility=visibility):
                script = deepcopy(self.script)
                script["roles"][0]["stage_knowledge"]["stage_1"]["blocks"][0].update(visibility=visibility, owner_role=owner)
                self.assertTrue(self.failed(inspect_authoring(script, self.plan), "role_readability"))

    def test_wrong_private_owner_is_rejected_by_existing_contract(self) -> None:
        self.script["roles"][0]["stage_knowledge"]["stage_1"]["blocks"][0]["owner_role"] = "chen"
        self.assertTrue(self.failed(inspect_authoring(self.script, self.plan), "schema_contract"))

    def test_missing_duplicate_unknown_or_unreachable_evidence_references_fail(self) -> None:
        variants = []
        for ids in (["absent"], ["letter", "letter"]):
            script = deepcopy(self.script)
            script["truth"]["evidence_chain"][0]["clue_ids"] = ids
            variants.append(script)
        script = deepcopy(self.script)
        script["truth"]["evidence_chain"] = []
        variants.append(script)
        script = deepcopy(self.script)
        target = script["mechanics_config"]["search"]["search_targets"][2]
        target["clues"].insert(0, {"id": "prefix", "content": "必须先发现的柜门封条。"})
        variants.append(script)  # Only one AP remains once this target unlocks.
        for script in variants:
            with self.subTest(chain=script["truth"]["evidence_chain"]):
                self.assertTrue(self.failed(inspect_authoring(script, self.plan), "schema_contract"))

    def test_disabled_search_and_unlock_after_final_cannot_supply_key_evidence(self) -> None:
        for change in ("disabled", "locked"):
            script = deepcopy(self.script)
            if change == "disabled":
                for config in script["stage_flow"].values():
                    config["investigation"]["enabled_actions"] = ["public_speech"]
            else:
                script["mechanics_config"]["search"]["search_targets"][2]["unlock_stage"] = 3
            with self.subTest(change=change):
                self.assertTrue(self.failed(inspect_authoring(script, self.plan), "schema_contract"))

    def test_placeholder_or_tautological_reasoning_and_duplicate_steps_fail(self) -> None:
        for reason in ("TODO", "待补充", self.script["truth"]["evidence_chain"][0]["conclusion"]):
            script = deepcopy(self.script)
            script["truth"]["evidence_chain"][0]["reasoning"] = reason
            with self.subTest(reason=reason):
                self.assertTrue(self.failed(inspect_authoring(script, self.plan), "evidence_chain"))
        self.script["truth"]["evidence_chain"] *= 2
        self.assertTrue(self.failed(inspect_authoring(self.script, self.plan), "evidence_chain"))

    def test_individually_reachable_clues_can_exceed_collective_final_act_ap(self) -> None:
        search = self.script["mechanics_config"]["search"]
        search["search_targets"] = [{"id": f"target_{index}", "unlock_stage": 2,
                                     "clues": [{"id": f"clue_{index}", "content": f"关键原件 {index}"}]} for index in range(3)]
        self.script["truth"]["evidence_chain"][0]["clue_ids"] = [f"clue_{index}" for index in range(3)]
        ScriptLoader(".").validate(self.script)  # Each is reachable, but the two-role team has only two AP.
        checks = self.failed(inspect_authoring(self.script), "evidence_ap_budget")
        self.assertIn("至少需要 3 次", checks[0]["message"])
        self.assertIn("预算为 2 次", checks[0]["message"])

    def test_culprit_name_in_public_background_is_not_automatically_a_spoiler(self) -> None:
        self.assertIn("陈默", self.script["opening"]["content"])
        self.assertTrue(inspect_authoring(self.script, self.plan)["passed"])

    def test_explicit_truth_in_any_public_narration_surface_fails(self) -> None:
        for surface in ("opening", "background", "briefing", "hosting", "tasks"):
            script = deepcopy(self.script)
            if surface == "opening":
                script["opening"]["content"] += "本案凶手就是陈默。"
            elif surface == "background":
                script["story_background"] += "陈默才是真凶。"
            elif surface == "tasks":
                script["stage_flow"]["stage_1"]["public_tasks"] += ["culprit_role_id: chen"]
            else:
                field = "public_briefing" if surface == "briefing" else "dm_hosting"
                script["stage_flow"]["stage_1"][field] += "真凶正是陈默。"
            with self.subTest(surface=surface):
                self.assertTrue(self.failed(inspect_authoring(script, self.plan), "public_disclosure"))

    def test_quoted_suspicion_is_warned_instead_of_judged_as_confirmed_truth(self) -> None:
        self.script["opening"]["content"] += "有人说凶手是陈默，但这只是传言，尚无证据。"
        report = inspect_authoring(self.script, self.plan)
        self.assertTrue(report["passed"], report)
        self.assertTrue(any(check["code"] == "public_disclosure" and check["status"] == "warning" for check in report["checks"]))

    def test_unrelated_following_question_does_not_hide_a_direct_reveal(self) -> None:
        self.script["opening"]["content"] += "凶手就是陈默。你们有什么问题？"
        self.assertTrue(self.failed(inspect_authoring(self.script, self.plan), "public_disclosure"))

    def test_copying_complete_truth_into_a_public_act_fails(self) -> None:
        self.script["stage_flow"]["stage_1"]["public_briefing"] = self.script["truth"]["full_story"]
        checks = self.failed(inspect_authoring(self.script, self.plan), "public_disclosure")
        self.assertTrue(any("完整真相" in check["message"] for check in checks))

    def test_same_role_at_same_time_in_two_locations_fails(self) -> None:
        self.plan["timeline_events"][1]["role_ids"] = ["qin"]
        checks = self.failed(inspect_authoring(self.script, self.plan), "timeline_plan")
        self.assertTrue(any("不同地点" in check["message"] for check in checks))

    def test_iso_offsets_normalize_to_same_instant(self) -> None:
        self.plan["timeline_events"][0]["time"] = "2026-10-19T20:10:00+08:00"
        self.plan["timeline_events"][1].update(time="2026-10-19T12:10:00Z", role_ids=["qin"])
        self.assertTrue(self.failed(inspect_authoring(self.script, self.plan), "timeline_plan"))

    def test_bad_timeline_format_and_unknown_role_are_actionable_failures(self) -> None:
        for updates in ({"time": "25:90"}, {"time": "2026-02-30T20:10:00"}, {"role_ids": ["absent"]}, {"location": " "}):
            plan = deepcopy(self.plan)
            plan["timeline_events"][0].update(updates)
            with self.subTest(updates=updates):
                self.assertTrue(self.failed(inspect_authoring(self.script, plan), "timeline_plan"))

    def test_repeated_event_ids_fail_without_fabricating_conflicts(self) -> None:
        self.plan["timeline_events"][1]["event_id"] = "delivery"
        checks = self.failed(inspect_authoring(self.script, self.plan), "timeline_plan")
        self.assertIn("event_id", checks[0]["message"])

    def test_clue_dependencies_cannot_reference_unknown_duplicate_or_late_clues(self) -> None:
        for updates in ({"requires_clue_ids": ["missing"]}, {"requires_clue_ids": ["letter", "letter"]},
                        {"available_stage": 1}, {"available_stage": True}, {"conclusion": "待补充"}):
            plan = deepcopy(self.plan)
            plan["clue_links"][2].update(updates)
            with self.subTest(updates=updates):
                self.assertTrue(self.failed(inspect_authoring(self.script, plan), "clue_dependencies"))

    def test_dependency_declared_later_than_its_conclusion_fails(self) -> None:
        self.script["mechanics_config"]["search"]["search_targets"][0]["unlock_stage"] = 2
        self.plan["clue_links"][0]["available_stage"] = 2
        self.assertTrue(self.failed(inspect_authoring(self.script, self.plan), "clue_dependency_order"))

    def test_actual_early_clue_cannot_be_declared_as_later_release(self) -> None:
        self.plan["clue_links"][0]["available_stage"] = 2
        self.assertTrue(self.failed(inspect_authoring(self.script,self.plan),"clue_dependencies"))

    def test_every_clue_requires_a_dependency_design(self) -> None:
        self.plan["clue_links"] = self.plan["clue_links"][:1]
        self.assertTrue(self.failed(inspect_authoring(self.script,self.plan),"clue_dependency_coverage"))

    def test_generated_ai_roles_also_need_their_own_reading(self) -> None:
        self.script["roles"][1]["human_playable"] = False
        self.script["roles"][1]["stage_knowledge"]["stage_1"]["blocks"] = []
        self.assertTrue(self.failed(inspect_authoring(self.script,self.plan),"role_readability"))

    def test_dependency_cycle_and_self_dependency_fail(self) -> None:
        for dependency in ("seal", "letter"):
            plan = deepcopy(self.plan)
            plan["clue_links"][0]["requires_clue_ids"] = [dependency]
            with self.subTest(dependency=dependency):
                self.assertTrue(self.failed(inspect_authoring(self.script, plan), "clue_dependency_cycle"))

    def test_long_acyclic_plan_does_not_depend_on_python_recursion_depth(self) -> None:
        count = 1005
        clues = [{"id": f"c_{index}", "content": f"有编号的原件 {index}"} for index in range(count)]
        self.script["mechanics_config"]["search"] = {"ap_per_stage": [count], "search_targets": [{"id": "archive", "clues": clues}]}
        self.script["truth"]["evidence_chain"][0]["clue_ids"] = [f"c_{count - 1}"]
        self.plan["clue_links"] = [{"clue_id": f"c_{index}", "requires_clue_ids": [f"c_{index - 1}"] if index else [],
                                    "available_stage": 1, "conclusion": f"第{index}份原件可以由前一编号的索引核对。"} for index in range(count)]
        report = inspect_authoring(self.script, self.plan)
        self.assertTrue(report["passed"], report["errors"])

    def test_missing_plan_sections_warn_but_do_not_claim_a_successful_audit(self) -> None:
        report = inspect_authoring(self.script, {})
        self.assertTrue(report["passed"], report)
        for code in ("timeline_plan", "clue_dependencies"):
            self.assertEqual(["warning"], [check["status"] for check in report["checks"] if check["code"] == code])

    def test_malformed_documents_return_reports_without_mutation_or_exceptions(self) -> None:
        for script in ({}, {"roles": []}, None, []):
            before = deepcopy(script)
            with self.subTest(script=script):
                self.assertTrue(self.failed(inspect_authoring(script), "schema_contract"))
                self.assertEqual(before, script)
        self.assertTrue(self.failed(inspect_authoring(self.script, []), "authoring_plan"))


if __name__ == "__main__":
    unittest.main()
