from __future__ import annotations

from backend.tests.account_fixtures import new_test_account

import asyncio
import json
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*")
os.environ["LLM_PROVIDER"] = "echo"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "app"))

from fastapi.testclient import TestClient
from main import create_app


class AuthAndHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.credentials = new_test_account("auth")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(
            create_app(
                Path(self.temp_dir.name) / "test.db",
                allow_legacy_token_response=True,
            )
        )
        self.script = json.loads(
            (BACKEND_ROOT / "resources" / "scripts" / "flame_mountain.json").read_text(encoding="utf-8")
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def register(self, prefix: str | None = None) -> dict[str, str]:
        credentials = self.credentials if prefix is None else new_test_account(prefix)
        response = self.client.post("/api/auth/register", json=credentials)
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def test_login_and_duplicate_username(self) -> None:
        self.register()
        duplicate = self.client.post("/api/auth/register", json={"username": self.credentials["username"].upper(), "password": self.credentials["password"]})
        self.assertEqual(duplicate.status_code, 400)
        login = self.client.post("/api/auth/login", json={"username": self.credentials["username"], "password": self.credentials["password"]})
        self.assertEqual(login.status_code, 200)
        me = self.client.get("/api/me", headers={"Authorization": f"Bearer {login.json()['token']}"})
        self.assertEqual(me.json()["username"], self.credentials["username"])

    def test_game_records_are_isolated_by_user(self) -> None:
        alice_headers = self.register("alice")
        bob_headers = self.register("bob_user")
        creation = self.client.post(
            "/api/games",
            headers=alice_headers,
            json={
                "category": "fantasy",
                "mode": "narrative",
                "player_role_id": "red_boy",
                "script": self.script,
            },
        )
        self.assertEqual(creation.status_code, 200)
        self.assertEqual(len(self.client.get("/api/games", headers=alice_headers).json()), 1)
        self.assertEqual(self.client.get("/api/games", headers=bob_headers).json(), [])
        forbidden = self.client.get(f"/api/games/{creation.json()['id']}", headers=bob_headers)
        self.assertEqual(forbidden.status_code, 404)

    def test_private_endpoints_require_login(self) -> None:
        self.assertEqual(self.client.get("/api/catalog").status_code, 401)
        self.assertEqual(self.client.get("/api/games").status_code, 401)

    def test_legacy_game_without_snapshot_is_migrated_on_resume(self) -> None:
        headers = self.register("legacy_snapshot")
        creation = self.client.post(
            "/api/games",
            headers=headers,
            json={
                "category": "fantasy",
                "mode": "narrative",
                "player_role_id": "red_boy",
                "script": self.script,
            },
        ).json()
        game_id = creation["id"]
        store = self.client.app.state.store
        user_id = store.user_for_token(
            headers["Authorization"].removeprefix("Bearer ")
        )["id"]
        with store._connect() as connection:
            connection.execute(
                "DELETE FROM game_runtime_snapshots WHERE game_id = ?",
                (game_id,),
            )
        self.client.app.state.game_service.sessions.clear()

        with self.client.websocket_connect(
            f"/game?token={headers['Authorization'].removeprefix('Bearer ')}"
            f"&game_id={game_id}"
        ) as ws:
            self.assertEqual(ws.receive_json()["type"], "game_init")

        migrated = store.get_runtime_snapshot(user_id, game_id)
        self.assertIsNotNone(migrated)
        self.assertEqual(migrated["version"], 1)

    def test_player_notebook_persists_manual_notes(self) -> None:
        headers = self.register("notebook_user")
        creation = self.client.post(
            "/api/games",
            headers=headers,
            json={
                "category": "fantasy",
                "mode": "narrative",
                "player_role_id": "red_boy",
                "script": self.script,
            },
        )
        game_id = creation.json()["id"]

        notebook = self.client.get(
            f"/api/games/{game_id}/notebook",
            headers=headers,
        )
        self.assertEqual(notebook.status_code, 200)
        self.assertIn(
            "personal_task",
            [entry["source_type"] for entry in notebook.json()["automatic"]],
        )

        saved = self.client.put(
            f"/api/games/{game_id}/notebook/manual",
            headers=headers,
            json={"content": "铁扇公主的证词仍需核对。"},
        )
        self.assertEqual(saved.status_code, 200)
        reloaded = self.client.get(
            f"/api/games/{game_id}/notebook",
            headers=headers,
        ).json()
        self.assertEqual(reloaded["manual_notes"], "铁扇公主的证词仍需核对。")

    def test_delete_game_is_owner_only_and_cascades_records(self) -> None:
        owner_headers = self.register("delete_owner")
        other_headers = self.register("delete_other")
        creation = self.client.post(
            "/api/games",
            headers=owner_headers,
            json={
                "category": "fantasy",
                "mode": "narrative",
                "player_role_id": "red_boy",
                "script": self.script,
            },
        )
        game_id = creation.json()["id"]

        forbidden = self.client.delete(
            f"/api/games/{game_id}",
            headers=other_headers,
        )
        self.assertEqual(forbidden.status_code, 404)
        deleted = self.client.delete(
            f"/api/games/{game_id}",
            headers=owner_headers,
        )
        self.assertEqual(deleted.json(), {"ok": True})
        self.assertEqual(self.client.get("/api/games", headers=owner_headers).json(), [])
        self.assertEqual(
            self.client.get(
                f"/api/games/{game_id}/notebook",
                headers=owner_headers,
            ).status_code,
            404,
        )

    def test_role_records_stay_private_until_game_completion(self) -> None:
        headers = self.register("audit_boundary")
        creation = self.client.post(
            "/api/games",
            headers=headers,
            json={
                "category": "fantasy",
                "mode": "narrative",
                "player_role_id": "red_boy",
                "script": self.script,
            },
        )
        response = self.client.get(
            f"/api/games/{creation.json()['id']}/role-records",
            headers=headers,
        )
        self.assertEqual(response.status_code, 409)

    def test_completed_role_records_include_persisted_agent_context_audit(
        self,
    ) -> None:
        headers = self.register("context_audit")
        creation = self.client.post(
            "/api/games",
            headers=headers,
            json={
                "category": "fantasy",
                "mode": "narrative",
                "player_role_id": "red_boy",
                "script": self.script,
            },
        ).json()
        game_id = creation["id"]
        service = self.client.app.state.game_service
        store = self.client.app.state.store
        dm = service.sessions[game_id]

        async def generate_agent_context() -> None:
            trigger = await dm.handle_human_speech("孙悟空，请说明你的来意。")
            await dm.schedule_ai_turns(trigger)

        asyncio.run(generate_agent_context())
        service.persist_engine_events(game_id, dm)
        store.update_game(game_id, 3, "completed", "replay")

        response = self.client.get(
            f"/api/games/{game_id}/role-records",
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        roles = {
            role["role_id"]: role
            for role in response.json()["roles"]
        }
        audits = roles["monkey_king"]["agent_context_audits"]
        self.assertTrue(audits)
        self.assertEqual(audits[0]["purpose"], "public_response")
        self.assertEqual(audits[0]["status"], "completed")
        self.assertIn("system_prompt", audits[0]["context"])
        self.assertTrue(audits[0]["context"]["messages"])

    def test_notebook_backfills_structured_dm_public_information(self) -> None:
        headers = self.register("structured_notebook")
        mystery_script = json.loads(
            (
                BACKEND_ROOT
                / "resources"
                / "scripts"
                / "fog_harbor_clocktower.json"
            ).read_text(encoding="utf-8")
        )
        # This regression covers archives created before the independent opening.
        mystery_script.pop("opening", None)
        creation = self.client.post(
            "/api/games",
            headers=headers,
            json={
                "category": "mystery",
                "mode": "deduction",
                "player_role_id": "shen_zhiwei",
                "script": mystery_script,
            },
        )
        game_id = creation.json()["id"]

        notebook = self.client.get(
            f"/api/games/{game_id}/notebook",
            headers=headers,
        )
        self.assertEqual(notebook.status_code, 200)
        source_types = {
            entry["source_type"]
            for entry in notebook.json()["automatic"]
        }
        self.assertTrue(
            {
                "story_background",
                "public_briefing",
                "public_tasks",
                "public_information",
            }.issubset(source_types)
        )

    def test_completed_legacy_game_recovers_available_activity_history(self) -> None:
        headers = self.register("legacy_audit")
        mystery_script = json.loads(
            (
                BACKEND_ROOT
                / "resources"
                / "scripts"
                / "fog_harbor_clocktower.json"
            ).read_text(encoding="utf-8")
        )
        creation = self.client.post(
            "/api/games",
            headers=headers,
            json={
                "category": "mystery",
                "mode": "deduction",
                "player_role_id": "shen_zhiwei",
                "script": mystery_script,
            },
        ).json()
        game_id = creation["id"]
        store = self.client.app.state.store
        store.add_event(
            game_id,
            "human_speech_echo",
            {
                "role_id": "shen_zhiwei",
                "content": "我要求重新核对停电时间。",
                "stage": 1,
            },
        )
        store.upsert_role_clue(
            game_id=game_id,
            role_id="shen_zhiwei",
            clue_id="clue_medicine_seal",
            stage=1,
            target_id="archive_desk",
            target_name="档案室书桌",
            truth_content="药瓶封签被重新粘贴过。",
            disclosure_mode="distorted",
            shared_content="药瓶封签完好无损。",
            shared_scope="public",
            target_role_id=None,
        )
        store.update_game(game_id, 3, "completed", "replay")

        audit = self.client.get(
            f"/api/games/{game_id}/role-records",
            headers=headers,
        )
        self.assertEqual(audit.status_code, 200)
        roles = {
            role["role_id"]: role
            for role in audit.json()["roles"]
        }
        human = roles["shen_zhiwei"]
        self.assertIn(
            "public_speech",
            [operation["event_type"] for operation in human["operations"]],
        )
        self.assertIn(
            "dm_hosting",
            [entry["source_type"] for entry in human["automatic_notebook"]],
        )
        self.assertEqual(human["clues"][0]["disclosure_mode"], "distorted")
        self.assertEqual(human["clues"][0]["truth_content"], "药瓶封签被重新粘贴过。")
        self.assertEqual(human["clues"][0]["shared_content"], "药瓶封签完好无损。")


if __name__ == "__main__":
    unittest.main()
