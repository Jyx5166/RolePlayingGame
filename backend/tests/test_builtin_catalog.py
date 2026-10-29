from __future__ import annotations

from backend.tests.account_fixtures import new_test_account

from backend.tests.script_fixtures import advance_to_investigation

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from main import create_app
from loader.script_loader import ScriptLoader
from backend.tests.test_engine_flow import actual_input, build_engine


EXPECTED = {
    "fog_harbor_clocktower": ("雾港档案·钟楼夜宴", 4, 3),
    "rainy_night_letter": ("雨夜来信", 3, 2),
    "last_train": ("末班列车", 5, 4),
    "deep_sea_echo": ("深海回声", 4, 3),
    "old_house_corridor": ("旧宅回廊", 5, 3),
    "silent_theater": ("无声剧院", 6, 4),
}


class BuiltinCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.directory.name) / "catalog.db", allow_legacy_token_response=True)
        self.client = TestClient(self.app)
        token = self.client.post("/api/auth/register", json=new_test_account('catalog_owner')).json()["token"]
        self.headers = {"Authorization": "Bearer " + token}

    def tearDown(self) -> None:
        self.client.close()
        self.directory.cleanup()

    def test_catalog_has_six_real_scripts_with_actual_metadata_and_safe_previews(self) -> None:
        with patch.object(self.app.state.game_service, "dm_factory", side_effect=AssertionError("preview must not create agents")):
            response = self.client.get("/api/v1/scripts", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        items = {item["catalog_id"]: item for item in response.json()}
        self.assertEqual(set(items), set(EXPECTED))
        for script_id, (title, roles, stages) in EXPECTED.items():
            item = items[script_id]
            self.assertEqual((item["title"], item["role_count"], item["total_stages"]), (title, roles, stages))
            self.assertEqual(item["ai_agent_count"], roles - 1)
            self.assertEqual(item["source"], "builtin")
            for field in ("truth", "stage_knowledge", "hidden_goal", "hard_constraints", "evidence_chain"):
                self.assertNotIn(field, json.dumps(item))
            if script_id != "fog_harbor_clocktower":
                self.assertEqual(item["provenance"]["kind"], "original")
            match = self.client.get("/api/v1/scripts", params={"q": title}, headers=self.headers).json()
            self.assertEqual([entry["catalog_id"] for entry in match], [script_id])

    def test_schema_endpoint_matches_exported_artifact(self) -> None:
        response = self.client.get("/api/v1/scripts/schema", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        expected = json.loads((ROOT / "resources/schema/script.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(response.json(), expected)

    def test_each_builtin_can_be_inspected_prepared_and_activated(self) -> None:
        items = self.client.get("/api/v1/scripts", headers=self.headers).json()
        for item in items:
            with self.subTest(script=item["catalog_id"]):
                preview = self.client.post("/api/v1/scripts/inspect", headers=self.headers,
                    json={"script_id": item["catalog_id"], "mode": "deduction"})
                self.assertEqual(preview.status_code, 200, preview.text)
                game = self.client.post("/api/v1/game-preparations", headers=self.headers,
                    json={"catalog_id": item["catalog_id"], "version": item["version"]})
                self.assertEqual(game.status_code, 201, game.text)
                role_id = item["playable_roles"][0]["role_id"]
                active = self.client.post(f"/api/v1/games/{game.json()['id']}/activate", headers=self.headers,
                    json={"player_role_id": role_id})
                self.assertEqual(active.status_code, 200, active.text)
                notebook = self.client.get(f"/api/v1/games/{game.json()['id']}/notebook", headers=self.headers)
                self.assertEqual(notebook.status_code, 200, notebook.text)
                self.assertEqual(notebook.json()["role_id"], role_id)


class BuiltinRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_new_scripts_all_roles_all_stages_and_both_endings(self) -> None:
        loader = ScriptLoader(ROOT / "resources/scripts")
        for script_id in sorted(EXPECTED.keys() - {"fog_harbor_clocktower"}):
            script = loader.load(script_id)
            for player in script["roles"]:
                # Every advertised playable role must build a correctly scoped runtime.
                dm = build_engine()
                await dm.init_game_from_script(script, player["role_id"], "deduction")
                self.assertEqual(len(dm.agent_pool.role_ids()), len(script["roles"]) - 1)
                self.assertNotIn(player["role_id"], dm.agent_pool.role_ids())
            for correct in (True, False):
                with self.subTest(script=script_id, correct=correct):
                    dm = build_engine()
                    human = script["script_meta"]["recommended_player_role"]
                    await dm.init_game_from_script(script, human, "deduction")
                    acquired = set()
                    for stage in range(1, script["script_meta"]["total_stages"] + 1):
                        self.assertEqual(dm.state.current_stage_num, stage)
                        for role in script["roles"]:
                            if role["role_id"] == human:
                                continue
                            actual = actual_input(dm, role["role_id"])
                            self.assertNotIn(script["truth"]["full_story"], actual)
                            for other in script["roles"]:
                                for knowledge in other["stage_knowledge"].values():
                                    for block in knowledge["blocks"]:
                                        if block["unlock_stage"] > stage or (block["visibility"] == "self_only" and other["role_id"] != role["role_id"]):
                                            self.assertNotIn(block["content"], actual)
                        await advance_to_investigation(dm)
                        search = dm.mechanic_registry.get("search")
                        for target in script["mechanics_config"]["search"]["search_targets"]:
                            if target["unlock_stage"] != stage:
                                continue
                            for clue in target["clues"]:
                                result = await search.on_role_action(dm.state, human, {"target_id": target["id"]})
                                self.assertIsNotNone(result["clue"], result)
                                acquired.add(result["clue"]["id"])
                        dm.end_investigation("timeout")
                        if dm.stage_resolution_pending():
                            candidates = dm.get_stage_resolution()["vote"]["eligible_roles"]
                            culprit = script["truth"]["culprit_role_id"]
                            target = culprit if correct else next(role["role_id"] for role in candidates if role["role_id"] != culprit)
                            async def ballot(context):
                                chosen = target if context.role_id != target else next(role["role_id"] for role in candidates if role["role_id"] != target)
                                return chosen, False
                            # Deterministic valid ballots check engine outcomes, not model deduction.
                            with patch.object(dm, "_call_agent", side_effect=ballot):
                                await dm.cast_stage_vote(target)
                        result = await dm.advance_scene_phase()
                    chain_ids = {clue_id for step in script["truth"]["evidence_chain"] for clue_id in step["clue_ids"]}
                    self.assertTrue(chain_ids.issubset(acquired))
                    self.assertIsNotNone(result["replay"])
                    vote = dm.get_stage_resolution()["vote"]
                    self.assertEqual(vote["correct"], correct)
                    self.assertEqual(vote["truth_revealed"], correct)


if __name__ == "__main__":
    unittest.main()
