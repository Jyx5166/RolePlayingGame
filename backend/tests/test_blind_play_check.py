from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.verification.blind_play_check import BlindAcceptance, parse_decision, resume_fenced_decision


class BlindPlayerProtocolTest(unittest.TestCase):
    def test_manual_fence_resume_preserves_vote_and_checks_saved_scope(self):
        shot = {"actor_role_id": "doctor", "actor_kind": "human", "stage": 3, "phase": "investigation", "purpose": "搜证后：更新假设",
                "output": '```json\n{"search_order":[],"vote_role_id":"lawyer"}\n```',
                "wire_messages": [{"content": json.dumps({"visible_state": {"public_roles": [{"role_id": "doctor"}, {"role_id": "lawyer"}],
                                         "search_status": {"targets": []}}})}]}
        self.assertEqual(resume_fenced_decision(shot, actor="doctor", stage=3)["vote_role_id"], "lawyer")
        for actor, stage in (("lawyer", 3), ("doctor", 4)):
            with self.assertRaises(ValueError):
                resume_fenced_decision(shot, actor=actor, stage=stage)
        shot["output"] = '```json\n{"vote_role_id":"oracle_culprit"}\n```'
        with self.assertRaises(ValueError):
            resume_fenced_decision(shot, actor="doctor", stage=3)
        shot["output"] = 'additional prose\n```json\n{}\n```'
        with self.assertRaises(ValueError):
            resume_fenced_decision(shot, actor="doctor", stage=3)

    def test_optional_null_is_preserved_and_stale_action_is_reported(self):
        value = parse_decision('{"search_order":["desk"],"private_role_id":null,"private_question":null,"vote_role_id":"lawyer"}',
                               {"doctor", "lawyer"}, set(), previously_visible_targets={"desk"})
        self.assertIsNone(value["private_question"])
        self.assertEqual(value["vote_role_id"], "lawyer")
        self.assertEqual(value["_action_rejections"][0]["target_id"], "desk")
        with self.assertRaises(ValueError):
            parse_decision('{"search_order":["future_room"]}', {"doctor"}, set(), previously_visible_targets={"desk"})

    def test_decision_uses_only_gui_ids_and_does_not_fix_invalid_votes(self):
        decision = parse_decision('{"search_order":["desk"],"vote_role_id":"doctor"}', {"doctor", "lawyer"}, {"desk"})
        self.assertEqual(decision["vote_role_id"], "doctor")
        for raw in ('{"vote_role_id":"oracle_culprit"}', '{"search_order":["future_room"]}', '{"search_order":["desk","desk"]}', '```json\n{}\n```'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_decision(raw, {"doctor", "lawyer"}, {"desk"})

    def test_player_projection_excludes_audit_oracle_and_future_metadata(self):
        qa = BlindAcceptance.__new__(BlindAcceptance)
        qa.case = {"title": "Public title", "game_id": 7}
        qa.user_id = 1
        qa.working = []
        qa.received = [{"type": "developer_audit", "truth": "FORBIDDEN_ORACLE"}]
        state = SimpleNamespace(human_player_role_id="doctor", public_history=[])
        phase = {"phase": "investigation", "stage": 1, "total_stages": 2, "stage_title": "Opening", "public_tasks": [], "enabled_actions": ["search"], "resolution": {"truth": "FORBIDDEN_ORACLE"}}
        qa.dm = SimpleNamespace(state=state, get_scene_summary=lambda: phase, get_public_roles=lambda: [{"role_id": "doctor", "public_identity": "Public doctor"}])
        qa.service = Mock()
        qa.service.get_player_notebook.return_value = {
            "role_id": "doctor", "clues": [], "automatic": [{"source_type": "role_script", "content": "OWN_KNOWLEDGE"}],
            "reasoning_entries": [], "manual_notes": "", "script": {"truth": "FORBIDDEN_ORACLE"},
        }
        with patch("ws.handlers.search_status", return_value={"targets": [{"id": "desk"}], "remaining_ap": 1}):
            visible = json.dumps(qa.visible())
        self.assertIn("OWN_KNOWLEDGE", visible)
        self.assertNotIn("FORBIDDEN_ORACLE", visible)
        self.assertNotIn("resolution", visible)


if __name__ == "__main__":
    unittest.main()
