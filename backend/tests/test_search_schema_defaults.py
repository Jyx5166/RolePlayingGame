from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from mechanics.search import SearchMechanic


class SearchSchemaDefaultsTest(unittest.IsolatedAsyncioTestCase):
    async def test_omitted_exclusivity_matches_shared_schema_default(self) -> None:
        mechanic = SearchMechanic({"ap_per_stage": [1], "search_targets": [{
            "id": "desk", "clues": [{"id": "letter", "content": "A recoverable original letter"}],
        }]})
        state = SimpleNamespace(current_stage_num=1)
        first = await mechanic.on_role_action(state, "reader_one", {"target_id": "desk"})
        second = await mechanic.on_role_action(state, "reader_two", {"target_id": "desk"})
        self.assertEqual(first["clue"]["id"], "letter")
        self.assertEqual(second["clue"]["id"], "letter")

    async def test_explicit_exclusive_clue_remains_exclusive(self) -> None:
        mechanic = SearchMechanic({"ap_per_stage": [1], "search_targets": [{
            "id": "desk", "clues": [{"id": "letter", "content": "One physical original", "exclusivity": "exclusive"}],
        }]})
        state = SimpleNamespace(current_stage_num=1)
        first = await mechanic.on_role_action(state, "reader_one", {"target_id": "desk"})
        second = await mechanic.on_role_action(state, "reader_two", {"target_id": "desk"})
        self.assertIsNotNone(first["clue"])
        self.assertIsNone(second["clue"])


if __name__ == "__main__":
    unittest.main()
