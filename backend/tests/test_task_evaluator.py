from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from dm.task_evaluator import evaluate_task_check, validate_task_checks


class TaskEvaluatorTest(unittest.TestCase):
    def test_unknown_rule_and_duplicate_events_fail_closed(self) -> None:
        for check in (
            {"label": "任务", "type": "free_text"},
            {"label": "任务", "type": "activity_count", "event_types": ["search", "search"], "minimum": 2},
            {"label": "任务", "type": "activity_count", "event_types": ["search"], "minimum": True},
            {"label": "任务", "type": "clue_disclosure", "channel": "public", "mininum": 2},
        ):
            with self.subTest(check=check), self.assertRaises(ValueError):
                validate_task_checks([check], {"a", "b"})

    def test_repeated_public_clue_is_not_new_for_another_role(self) -> None:
        check = {"label": "首次披露", "type": "clue_disclosure", "channel": "public", "new_public": True}
        events = [
            {"type": "clue_disclosure", "stage": 1, "actor_role_id": "a", "clue_id": "clue", "scope": "public", "disclosure_mode": "truthful"},
            {"type": "clue_disclosure", "stage": 2, "actor_role_id": "b", "clue_id": "clue", "scope": "public", "disclosure_mode": "truthful"},
        ]
        result = evaluate_task_check(check, role_id="b", stage=2, counts={}, audit_log=events)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["count"], 0)

    def test_private_disclosure_must_match_role_and_recipient_and_stage(self) -> None:
        check = {"label": "向 b 披露", "type": "clue_disclosure", "channel": "private", "target_role_id": "b", "clue_id": "clue"}
        events = [{"type": "clue_disclosure", "stage": 2, "actor_role_id": "a", "target_role_id": "b", "clue_id": "clue", "scope": "private", "disclosure_mode": "truthful"}]
        for role, stage, status in (("a", 2, "completed"), ("b", 2, "failed"), ("a", 1, "failed")):
            self.assertEqual(evaluate_task_check(check, role_id=role, stage=stage, counts={}, audit_log=events)["status"], status)


if __name__ == "__main__":
    unittest.main()
