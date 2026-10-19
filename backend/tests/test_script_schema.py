from __future__ import annotations

from copy import deepcopy
import json
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "app"))

from loader.script_loader import ScriptLoader, ScriptValidationError
from loader.script_schema import ScriptDocument


class ScriptSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = ScriptLoader(BACKEND_ROOT / "resources" / "scripts")
        self.script = json.loads((BACKEND_ROOT / "resources" / "scripts" / "fog_harbor_clocktower.json").read_text(encoding="utf-8"))
        self.script["schema_version"] = "1.0"
        self.script["truth"].setdefault("evidence_chain", [{
            "conclusion": "药瓶封签被替换。", "clue_ids": ["clue_medicine_seal"],
            "reasoning": "封签与配药记录的冲突需要在复盘中解释。",
        }])

    def assert_invalid(self, script: dict, message: str) -> None:
        before = deepcopy(script)
        with self.assertRaisesRegex(ScriptValidationError, message):
            self.loader.validate(script)
        self.assertEqual(script, before, "validation must not mutate rejected input")

    def legacy_script(self, script_id: str) -> dict:
        script = self.loader.load(script_id)
        script.pop("schema_version", None)
        script["script_meta"].pop("provenance", None)
        script["truth"].pop("evidence_chain", None)
        # Resource migration prefixed the repeated public block IDs with the
        # containing role. Reconstruct pre-migration saved-game snapshots.
        for role in script["roles"]:
            for knowledge in role["stage_knowledge"].values():
                for block in knowledge["blocks"]:
                    if block["visibility"] == "public":
                        block["block_id"] = block["block_id"].removeprefix(role["role_id"] + "_")
        return script

    def test_versioned_and_legacy_validation_preserve_input(self) -> None:
        for versioned in (True, False):
            script = deepcopy(self.script)
            if not versioned:
                script.pop("schema_version")
                script["truth"].pop("evidence_chain")
            before = deepcopy(script)
            self.loader.validate(script)
            self.assertEqual(before, script)

    def test_versioned_narrative_can_omit_flow_and_evidence(self) -> None:
        script = self.loader.load("flame_mountain")
        script["schema_version"] = "1.0"
        script.pop("stage_flow", None)
        script["truth"].pop("evidence_chain", None)
        self.loader.validate(script)

    def test_narrative_empty_flow_is_valid_but_explicit_null_is_rejected(self) -> None:
        script = self.loader.load("flame_mountain")
        script["stage_flow"] = {}
        self.loader.validate(script)
        script["stage_flow"] = None
        self.assert_invalid(script, "stage_flow")

    def test_legacy_standard_saved_scripts_accept_identical_public_shared_ids(self) -> None:
        for script_id in ("flame_mountain", "fog_harbor_clocktower"):
            with self.subTest(script_id=script_id):
                script = self.legacy_script(script_id)
                public_ids = [block["block_id"] for role in script["roles"]
                              for knowledge in role["stage_knowledge"].values()
                              for block in knowledge["blocks"] if block["visibility"] == "public"]
                self.assertGreater(len(public_ids), len(set(public_ids)))
                before = deepcopy(script)
                self.loader.validate(script)
                self.assertEqual(script, before)

    def test_legacy_shared_public_ids_reject_nonidentical_blocks(self) -> None:
        for field, value in (("type", "other"), ("content", "不同的公开事实"),
                             ("owner_role", "*"), ("unlock_stage", 2)):
            with self.subTest(field=field):
                script = self.legacy_script("flame_mountain")
                public = next(block for block in script["roles"][1]["stage_knowledge"]["stage_1"]["blocks"]
                              if block["visibility"] == "public")
                public[field] = value
                self.assert_invalid(script, "Duplicate block_id")

    def test_legacy_duplicate_within_same_role_and_private_ids_are_rejected(self) -> None:
        script = self.legacy_script("flame_mountain")
        blocks = script["roles"][1]["stage_knowledge"]["stage_1"]["blocks"]
        public = next(block for block in blocks if block["visibility"] == "public")
        blocks.append(deepcopy(public))
        self.assert_invalid(script, "Duplicate block_id")
        script = self.legacy_script("flame_mountain")
        private = deepcopy(script["roles"][0]["stage_knowledge"]["stage_1"]["blocks"][0])
        script["roles"][1]["stage_knowledge"]["stage_1"]["blocks"].append(private)
        self.assert_invalid(script, "Duplicate block_id")

    def test_versioned_script_rejects_even_identical_public_shared_ids(self) -> None:
        script = self.legacy_script("flame_mountain")
        script["schema_version"] = "1.0"
        self.assert_invalid(script, "Duplicate block_id")

    def test_event_timeline_accepts_actual_timestamps(self) -> None:
        self.script["truth"]["complete_timeline"] = {"23:15": "配药记录被改写。", "23:26": "怀表停下。"}
        self.loader.validate(self.script)

    def test_schema_export_matches_authoring_model(self) -> None:
        path = BACKEND_ROOT / "resources" / "schema" / "script.schema.json"
        exported = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(exported, ScriptDocument.model_json_schema())
        self.assertEqual(exported, self.loader.json_schema())
        self.assertIn("schema_version", exported["required"])
        self.assertFalse(exported["$defs"]["InfoBlock"]["additionalProperties"])

    def test_unknown_version_is_rejected(self) -> None:
        self.script["schema_version"] = "2.0"
        self.assert_invalid(self.script, "schema_version")

    def test_opening_is_separate_validated_public_content(self) -> None:
        script = deepcopy(self.script)
        script["opening"] = {"title": "开幕 · 暴雨将至", "content": "故事背景与公开人物关系。"}
        before = deepcopy(script)
        self.loader.validate(script)
        self.assertEqual(script, before)
        for opening in ({"title": "开幕"}, {"title": "开幕", "content": " "},
                        {"title": "开幕", "content": "背景", "truth": "不可混入私密字段"}):
            invalid = deepcopy(script)
            invalid["opening"] = opening
            self.assert_invalid(invalid, "opening")
        script.pop("schema_version", None)
        script.pop("stage_flow")
        self.assert_invalid(script, "opening requires")

    def test_roles_cannot_use_dm_or_wildcard_permission_identifiers(self) -> None:
        for role_id in ("dm", "*"):
            with self.subTest(role_id=role_id):
                script = deepcopy(self.script)
                script["roles"][0]["role_id"] = role_id
                self.assert_invalid(script, "reserved permission identifier")

    def test_versioned_deduction_requires_flow_and_evidence(self) -> None:
        for field in ("stage_flow", "evidence_chain"):
            script = deepcopy(self.script)
            (script if field == "stage_flow" else script["truth"]).pop(field)
            self.assert_invalid(script, field)

    def test_unknown_nested_fields_and_type_coercion_are_rejected(self) -> None:
        variants = []
        for path, value in (
            (("roles", 0, "human_playable"), "true"),
            (("roles", 0, "personality"), 42),
            (("roles", 0, "accidental_full_truth"), "secret"),
            (("stage_flow", "stage_1", "investigation", "autonomy", "enabled"), 1),
        ):
            script = deepcopy(self.script)
            target = script
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            variants.append((script, str(path[-1])))
        for script, field in variants:
            with self.subTest(field=field):
                self.assert_invalid(script, field)

    def test_duplicate_roles_blocks_targets_and_clues_are_rejected(self) -> None:
        variants = []
        duplicate_role = deepcopy(self.script)
        duplicate_role["roles"].append(deepcopy(duplicate_role["roles"][0]))
        variants.append((duplicate_role, "Duplicate role_id"))
        duplicate_block = deepcopy(self.script)
        blocks = duplicate_block["roles"][0]["stage_knowledge"]["stage_1"]["blocks"]
        blocks.append(deepcopy(blocks[0]))
        variants.append((duplicate_block, "Duplicate block_id"))
        duplicate_target = deepcopy(self.script)
        targets = duplicate_target["mechanics_config"]["search"]["search_targets"]
        targets.append(deepcopy(targets[0]))
        variants.append((duplicate_target, "duplicate search target.id"))
        duplicate_clue = deepcopy(self.script)
        clues = duplicate_clue["mechanics_config"]["search"]["search_targets"][0]["clues"]
        clues.append(deepcopy(clues[0]))
        variants.append((duplicate_clue, "duplicate clue.id"))
        for script, message in variants:
            with self.subTest(message=message):
                self.assert_invalid(script, message)

    def test_stage_keys_must_match_total_stages(self) -> None:
        for field in ("stage_flow", "stage_knowledge"):
            script = deepcopy(self.script)
            target = script["stage_flow"] if field == "stage_flow" else script["roles"][0]["stage_knowledge"]
            target["stage_4"] = deepcopy(target["stage_3"])
            self.assert_invalid(script, "exactly")

    def test_unlock_and_availability_ranges_are_rejected(self) -> None:
        variants = []
        for path in (
            ("roles", 0, "stage_knowledge", "stage_1", "blocks", 0, "unlock_stage"),
            ("mechanics_config", "search", "search_targets", 0, "unlock_stage"),
            ("mechanics_config", "whisper", "role_available_from_stage", "shen_zhiwei"),
            ("hard_constraints", 0, "until_stage"),
        ):
            script = deepcopy(self.script)
            target = script
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = script["script_meta"]["total_stages"] + 1
            variants.append(script)
        for index, script in enumerate(variants):
            with self.subTest(index=index):
                self.assert_invalid(script, "within")

    def test_private_and_dm_ownership_must_match_scope(self) -> None:
        for visibility, owner in (("self_only", "gu_linchuan"), ("dm_only", "shen_zhiwei")):
            script = deepcopy(self.script)
            block = script["roles"][0]["stage_knowledge"]["stage_1"]["blocks"][0]
            block.update(visibility=visibility, owner_role=owner)
            self.assert_invalid(script, "owner_role")

    def test_role_references_must_exist_and_recommendation_must_be_playable(self) -> None:
        for field in ("role_arcs", "recommended_player_role"):
            script = deepcopy(self.script)
            if field == "role_arcs":
                script["truth"][field]["unknown_role"] = "unknown arc"
            else:
                script["script_meta"][field] = "unknown_role"
            self.assert_invalid(script, field)
        self.script["roles"][0]["human_playable"] = False
        self.script["script_meta"]["recommended_player_role"] = self.script["roles"][0]["role_id"]
        self.assert_invalid(self.script, "human-playable")

    def test_task_and_evidence_clue_references_must_exist(self) -> None:
        for location in ("task", "evidence"):
            script = deepcopy(self.script)
            if location == "task":
                script["stage_flow"]["stage_2"]["personal_task_checks"]["shen_zhiwei"][0]["clue_id"] = "unknown_clue"
            else:
                script["truth"]["evidence_chain"][0]["clue_ids"] = ["unknown_clue"]
            self.assert_invalid(script, "Unknown clue reference")

    def test_task_clue_cannot_require_future_target(self) -> None:
        self.script["stage_flow"]["stage_1"]["personal_task_checks"]["shen_zhiwei"] = [{
            "type": "clue_disclosure", "label": "过早披露", "channel": "public",
            "clue_id": "clue_aconite",
        }]
        self.assert_invalid(self.script, "not reachable by stage 1")

    def test_clue_reachability_considers_action_points(self) -> None:
        self.script["mechanics_config"]["search"]["ap_per_stage"] = [0]
        self.assert_invalid(self.script, "not reachable")

    def test_disabled_mechanic_and_unavailable_task_actions_are_rejected(self) -> None:
        script = deepcopy(self.script)
        script["mechanics_enabled"].remove("whisper")
        for config in script["stage_flow"].values():
            actions = config["investigation"]["enabled_actions"]
            if "whisper" in actions:
                actions.remove("whisper")
        self.assert_invalid(script, "disabled mechanic")
        self.script["stage_flow"]["stage_2"]["personal_task_checks"]["shen_zhiwei"] = [{
            "type": "clue_disclosure", "label": "私聊", "channel": "private",
            "clue_id": "clue_medicine_seal",
        }]
        self.assert_invalid(self.script, "whisper action")

    def test_penalty_cannot_target_a_stage_after_finale(self) -> None:
        self.script["stage_flow"]["stage_1"]["resolution"]["vote"]["penalty"]["target_stage_offset"] = 99
        self.assert_invalid(self.script, "penalty target stage")


if __name__ == "__main__":
    unittest.main()
