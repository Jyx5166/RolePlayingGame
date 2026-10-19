from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from game_service import GameService
from storage import AppStore


class NotebookPermissionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = AppStore(Path(self.directory.name) / "notebook.db")
        self.user_id = self.store.register("notebook_owner", "password123")["user"]["id"]
        self.script = json.loads((ROOT / "resources/scripts/fog_harbor_clocktower.json").read_text(encoding="utf-8"))
        self.role_id = self.script["roles"][0]["role_id"]
        # Historical stored games can contain data accepted by the old validator.
        self.probes = [
            ("dm_secret", "dm_only", "dm", 1),
            ("other_secret", "self_only", self.script["roles"][1]["role_id"], 1),
            ("future_public", "public", "dm", 2),
            ("future_private", "self_only", self.role_id, 2),
            ("allowed_private", "self_only", self.role_id, 1),
            ("allowed_public", "public", "dm", 1),
        ]
        for block_id, visibility, owner, unlock in self.probes:
            self.script["roles"][0]["stage_knowledge"]["stage_1"]["blocks"].append({
                "block_id": block_id, "type": "memory", "content": f"PROBE_{block_id}",
                "visibility": visibility, "owner_role": owner, "unlock_stage": unlock,
            })
        self.game = self.store.create_game(self.user_id, self.script, "mystery", "deduction", self.role_id)
        self.service = GameService(self.store, lambda: self.fail("Notebook reads must not create a model"))

    def tearDown(self) -> None:
        self.directory.cleanup()

    def probe_contents(self, notebook: dict) -> set[str]:
        return {entry["content"] for entry in notebook["automatic"] if entry["content"].startswith("PROBE_")}

    def seed_old_records(self) -> None:
        for block_id, visibility, _, _ in self.probes:
            self.store.add_notebook_entry(self.game["id"], self.role_id, "automatic",
                "public_information" if visibility == "public" else "role_script",
                f"role-script:1:{block_id}", 1, "Old note", f"PROBE_{block_id}")

    def test_backfill_applies_owner_visibility_and_stage_to_writes(self) -> None:
        notes = self.service.get_player_notebook(self.user_id, self.game["id"])
        self.assertEqual(self.probe_contents(notes), {"PROBE_allowed_private", "PROBE_allowed_public"})
        stored = self.store.list_notebook_entries(self.user_id, self.game["id"], self.role_id)
        self.assertFalse(any(entry["content"] in {"PROBE_dm_secret", "PROBE_other_secret", "PROBE_future_public", "PROBE_future_private"} for entry in stored))

    def test_previously_persisted_leaks_are_filtered_on_read(self) -> None:
        self.seed_old_records()
        notes = self.service.get_player_notebook(self.user_id, self.game["id"])
        self.assertEqual(self.probe_contents(notes), {"PROBE_allowed_private", "PROBE_allowed_public"})

    def test_delayed_blocks_appear_only_when_unlocked(self) -> None:
        self.seed_old_records()
        self.store.update_game(self.game["id"], 2, "playing", "investigation")
        notes = self.service.get_player_notebook(self.user_id, self.game["id"])
        self.assertEqual(self.probe_contents(notes), {
            "PROBE_allowed_private", "PROBE_allowed_public", "PROBE_future_public", "PROBE_future_private",
        })

    def test_unknown_script_sources_fail_closed_and_player_notes_survive(self) -> None:
        self.store.add_notebook_entry(self.game["id"], self.role_id, "automatic", "role_script", "untraceable", 1, "Unknown", "PROBE_unknown")
        self.store.add_notebook_entry(self.game["id"], self.role_id, "automatic", "public_information", "role-script:9:allowed_public", 9, "Future", "PROBE_allowed_public")
        self.store.add_notebook_entry(self.game["id"], self.role_id, "reasoning", "reasoning", "reasoning:1", 1, "My reasoning", "My own notes")
        self.service.save_player_manual_notes(self.user_id, self.game["id"], "Manual content")
        notes = self.service.get_player_notebook(self.user_id, self.game["id"])
        self.assertNotIn("PROBE_unknown", self.probe_contents(notes))
        self.assertTrue(all(entry["source_key"] != "role-script:9:allowed_public" for entry in notes["automatic"]))
        self.assertEqual(notes["manual_notes"], "Manual content")
        self.assertEqual(notes["reasoning_entries"][0]["content"], "My own notes")

    def test_other_user_cannot_read_notebook(self) -> None:
        other = self.store.register("other_notebook", "password123")["user"]["id"]
        with self.assertRaises(KeyError):
            self.service.get_player_notebook(other, self.game["id"])

    def test_completed_role_records_do_not_attribute_dm_secrets_to_role(self) -> None:
        self.seed_old_records()
        self.store.update_game(self.game["id"], 3, "completed", "replay")
        records = self.service.get_role_records(self.user_id, self.game["id"])
        role = next(role for role in records["roles"] if role["role_id"] == self.role_id)
        contents = {entry["content"] for entry in role["automatic_notebook"]}
        self.assertNotIn("PROBE_dm_secret", contents)
        self.assertNotIn("PROBE_other_secret", contents)
        self.assertIn("PROBE_future_private", contents)


if __name__ == "__main__":
    unittest.main()
