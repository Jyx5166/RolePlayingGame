from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "app"))

from dm.permission import PermissionMatrix
from dm.validator import SpeechValidator
from loader.script_loader import ScriptLoader, ScriptValidationError


class LoaderPermissionValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = ScriptLoader(BACKEND_ROOT / "resources" / "scripts")
        self.script = self.loader.load("flame_mountain")

    def test_loads_flame_mountain_script(self) -> None:
        self.assertEqual(self.script["script_meta"]["script_id"], "flame_mountain")
        self.assertEqual(len(self.script["roles"]), 3)

    def test_permission_matrix_respects_stage(self) -> None:
        permission = PermissionMatrix(self.script)
        stage_1_text = permission.visible_text("red_boy", 1)
        stage_2_text = permission.visible_text("red_boy", 2)
        self.assertIn("孙悟空", stage_1_text)
        self.assertNotIn("铁扇公主", stage_1_text)
        self.assertIn("铁扇公主", stage_2_text)

    def test_ai_hard_constraint_blocks_future_info(self) -> None:
        validator = SpeechValidator(self.script)
        result = validator.validate_ai_speech("monkey_king", 1, "我看到观音现身了。")
        self.assertFalse(result.passed)
        self.assertIn("观音", result.message or "")

    def test_human_hard_constraint_warns_without_blocking(self) -> None:
        validator = SpeechValidator(self.script)
        result = validator.validate_human_speech("red_boy", 1, "我以后会成为善财童子。")
        self.assertTrue(result.passed)
        self.assertIn("终局", result.message or "")

    def test_scene_flow_rejects_unknown_personal_task_role(self) -> None:
        script = copy.deepcopy(self.loader.load("fog_harbor_clocktower"))
        script["stage_flow"]["stage_1"]["personal_tasks"]["unknown_role"] = "非法任务"
        with self.assertRaisesRegex(ScriptValidationError, "unknown roles"):
            self.loader.validate(script)

    def test_scene_flow_rejects_unsupported_action(self) -> None:
        script = copy.deepcopy(self.loader.load("fog_harbor_clocktower"))
        script["stage_flow"]["stage_1"]["investigation"]["enabled_actions"].append(
            "read_future_truth"
        )
        with self.assertRaisesRegex(ScriptValidationError, "enabled_actions is invalid"):
            self.loader.validate(script)

    def test_scene_flow_rejects_invalid_autonomy_interval(self) -> None:
        script = copy.deepcopy(self.loader.load("fog_harbor_clocktower"))
        script["stage_flow"]["stage_1"]["investigation"]["autonomy"][
            "interval_seconds"
        ] = 0
        with self.assertRaisesRegex(ScriptValidationError, "interval_seconds must be >= 1"):
            self.loader.validate(script)

    def test_scene_flow_rejects_invalid_end_condition_scope(self) -> None:
        script = copy.deepcopy(self.loader.load("fog_harbor_clocktower"))
        script["stage_flow"]["stage_1"]["investigation"]["end_conditions"][
            "actor_scope"
        ] = "agents_only"
        with self.assertRaisesRegex(ScriptValidationError, "actor_scope is invalid"):
            self.loader.validate(script)

    def test_final_decision_requires_known_culprit(self) -> None:
        script = copy.deepcopy(self.loader.load("fog_harbor_clocktower"))
        script["truth"]["culprit_role_id"] = "unknown_role"
        with self.assertRaisesRegex(ScriptValidationError, "culprit_role_id"):
            self.loader.validate(script)


if __name__ == "__main__":
    unittest.main()
