from __future__ import annotations

from backend.tests.account_fixtures import new_test_account

import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "app"))
from main import create_app
from storage import AppStore
from backend.tests.script_fixtures import single_stage_script, advance_to_investigation


class ScriptSessionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name) / "test.db", allow_legacy_token_response=True)
        self.client = TestClient(self.app)
        self.headers = {"Authorization": "Bearer " + self.client.post("/api/auth/register", json=new_test_account('script_owner')).json()["token"]}
        self.other = {"Authorization": "Bearer " + self.client.post("/api/auth/register", json=new_test_account('other_owner')).json()["token"]}
        self.script = json.loads((ROOT / "backend/resources/scripts/fog_harbor_clocktower.json").read_text(encoding="utf-8"))
        self.item = self.client.get("/api/v1/scripts", headers=self.headers).json()[0]

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def prepare(self) -> dict:
        response = self.client.post("/api/v1/game-preparations", headers=self.headers, json={"catalog_id": self.item["catalog_id"], "version": self.item["version"]})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def activate(self, game_id: int, role_id: str = "shen_zhiwei"):
        return self.client.post(f"/api/v1/games/{game_id}/activate", headers=self.headers, json={"player_role_id": role_id})

    def test_catalog_and_inspection_do_not_create_agents_or_expose_secrets(self) -> None:
        with patch.object(self.app.state.game_service, "dm_factory", side_effect=AssertionError("must not create DM")):
            for path in ("/api/v1/scripts", "/api/v1/scripts/example"):
                response = self.client.get(path, headers=self.headers)
                self.assertEqual(response.status_code, 200)
                for secret in ("full_story", "stage_knowledge", "hard_constraints"):
                    self.assertNotIn(secret, response.text)
            self.prepare()
        self.assertFalse(self.app.state.game_service.sessions)

    def test_publication_search_matches_title_or_tag_and_is_owner_scoped(self) -> None:
        for title, tags in (("恐怖夜宴", ["悬疑"]), ("雾山夜宴", ["中式恐怖"])):
            response = self.client.post("/api/v1/scripts", headers=self.headers, json={"script": self.script, "title": title, "tags": tags})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["workflow_steps"][-1], "published")
        results = self.client.get("/api/v1/scripts?q=恐怖", headers=self.headers).json()
        self.assertEqual({item["title"] for item in results}, {"恐怖夜宴", "雾山夜宴"})
        self.assertEqual(self.client.get("/api/v1/scripts?q=不存在", headers=self.headers).json(), [])
        self.assertEqual(len(self.client.get("/api/v1/scripts", headers=self.other).json()), 6)
        hidden = self.client.post("/api/v1/game-preparations", headers=self.other, json={"catalog_id": results[0]["catalog_id"], "version": results[0]["version"]})
        self.assertEqual(hidden.status_code, 404)

    def test_invalid_publication_creates_neither_script_nor_game(self) -> None:
        for changes in ({"title": " "}, {"tags": ["a" * 25]}, {"script": {"truth": {}}}):
            body = {"script": self.script, "title": "测试剧本", "tags": ["悬疑"], **changes}
            self.assertEqual(self.client.post("/api/v1/scripts", headers=self.headers, json=body).status_code, 400)
        self.assertEqual(len(self.client.get("/api/v1/scripts", headers=self.headers).json()), 6)
        self.assertEqual(self.client.get("/api/v1/games", headers=self.headers).json(), [])

    def test_same_script_entries_allocate_distinct_empty_scopes_and_snapshots(self) -> None:
        first, second = self.prepare(), self.prepare()
        self.assertNotEqual(first["id"], second["id"])
        self.assertIsNone(first["player_role_id"])
        self.assertEqual(first["status"], "preparing")
        store = self.app.state.store
        with store._connect() as connection:
            groups = [{row["context_id"] for row in connection.execute("SELECT context_id FROM game_context_scopes WHERE game_id = ?", (game["id"],))} for game in (first, second)]
            self.assertEqual(len(groups[0]), len(self.script["roles"]) + 1)
            self.assertTrue(groups[0].isdisjoint(groups[1]))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM game_runtime_snapshots").fetchone()[0], 0)
        self.assertEqual(store.get_game(1, first["id"], include_script=True)["script"], self.script)

    def test_preparation_retry_reuses_id_and_rejects_different_payload(self) -> None:
        body = {"catalog_id": self.item["catalog_id"], "version": self.item["version"], "request_id": "retry-entry-0001"}
        first = self.client.post("/api/v1/game-preparations", headers=self.headers, json=body).json()
        second = self.client.post("/api/v1/game-preparations", headers=self.headers, json=body).json()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.app.state.store.list_games(1)), 1)
        conflict = self.client.post("/api/v1/game-preparations", headers=self.headers, json={**body, "version": "other-version"})
        self.assertEqual(conflict.status_code, 409)
        other = self.client.post("/api/v1/game-preparations", headers=self.other, json=body).json()
        self.assertNotEqual(first["id"], other["id"])

    def test_activation_is_same_game_role_locked_and_retry_safe(self) -> None:
        game = self.prepare()
        self.assertEqual(self.activate(game["id"], "not_a_role").status_code, 409)
        self.assertFalse(self.app.state.game_service.sessions)
        response = self.activate(game["id"])
        self.assertEqual(response.status_code, 200, response.text)
        runtime = self.app.state.game_service.sessions[game["id"]]
        self.assertEqual(self.activate(game["id"]).json()["id"], game["id"])
        self.assertIs(runtime, self.app.state.game_service.sessions[game["id"]])
        self.assertEqual(self.activate(game["id"], "gu_linchuan").status_code, 409)
        self.assertEqual(len(self.client.get("/api/v1/games", headers=self.headers).json()), 1)

    def test_preparation_exposes_only_the_saved_public_opening_after_activation_and_pause(self) -> None:
        self.item = next(item for item in self.client.get("/api/v1/scripts", headers=self.headers).json()
                         if item["catalog_id"] == "fog_harbor_clocktower")
        game = self.prepare()
        self.assertEqual(self.activate(game["id"]).status_code, 200)
        expected = self.script["opening"]
        for status in ("playing", "paused"):
            with self.subTest(status=status):
                if status == "paused":
                    self.assertEqual(self.client.post(f'/api/v1/games/{game["id"]}/pause', headers=self.headers).status_code, 200)
                response = self.client.get(f'/api/v1/games/{game["id"]}/preparation', headers=self.headers)
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertEqual(payload["game"]["status"], status)
                self.assertEqual(payload["opening"], expected)
                opening_text = json.dumps(payload["opening"], ensure_ascii=False)
                for forbidden in (self.script["story_background"], self.script["truth"]["full_story"],
                                  self.script["stage_flow"]["stage_2"]["public_briefing"]):
                    self.assertNotIn(forbidden, opening_text)
                for role in self.script["roles"]:
                    self.assertNotIn(role["hidden_goal"], opening_text)
                    for knowledge in role["stage_knowledge"].values():
                        for block in knowledge["blocks"]:
                            if block["visibility"] == "self_only":
                                self.assertNotIn(block["content"], opening_text)
                for secret_field in ("truth", "stage_knowledge", "hidden_goal", "hard_constraints"):
                    self.assertNotIn(f'"{secret_field}"', response.text)

    def test_preparation_without_scene_flow_has_no_opening(self) -> None:
        script = json.loads(json.dumps(self.script))
        script.pop("stage_flow")
        script.pop("opening", None)
        script.pop("schema_version", None)
        game = self.app.state.store.prepare_game(1, script, "legacy-script", "v1")
        response = self.client.get(f'/api/v1/games/{game["id"]}/preparation', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["opening"])

    def test_creation_response_and_detail_match_the_opening_state(self) -> None:
        response = self.client.post("/api/v1/games", headers=self.headers, json={
            "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei", "script": self.script,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["current_phase"], "opening")
        detail = self.client.get(f'/api/v1/games/{response.json()["id"]}', headers=self.headers).json()
        self.assertEqual(detail["current_phase"], "opening")
        self.assertTrue(detail["has_opening"])
        self.assertTrue(detail["before_first_stage"])
        self.assertNotIn("script", detail)

    def test_preparing_game_cannot_create_or_load_role_memory(self) -> None:
        game = self.prepare()
        path = f'/api/v1/games/{game["id"]}/notebook'
        self.assertEqual(self.client.get(path, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.put(path + "/manual", headers=self.headers, json={"content": "premature note"}).status_code, 409)
        with self.app.state.store._connect() as connection:
            for table in ("role_notebook_entries", "role_manual_notes", "game_runtime_snapshots"):
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    def test_preparation_and_activation_are_owner_only(self) -> None:
        game = self.prepare()
        self.assertEqual(self.client.get(f'/api/v1/games/{game["id"]}/preparation', headers=self.other).status_code, 404)
        self.assertEqual(self.client.post(f'/api/v1/games/{game["id"]}/activate', headers=self.other, json={"player_role_id": "shen_zhiwei"}).status_code, 404)
        self.assertEqual(self.client.post(f'/api/v1/games/{game["id"]}/pause', headers=self.other).status_code, 404)

    def test_same_script_games_never_share_mutable_runtime(self) -> None:
        first, second = self.prepare(), self.prepare()
        self.activate(first["id"])
        self.activate(second["id"])
        one, two = [self.app.state.game_service.sessions[game["id"]] for game in (first, second)]
        one._require_state().public_history.append({"role": "user", "content": "only game one"})
        self.assertIsNot(one.agent_pool, two.agent_pool)
        self.assertNotIn("only game one", json.dumps(two.export_runtime_snapshot()))

    def test_second_control_window_is_rejected_without_pausing_first(self) -> None:
        from starlette.websockets import WebSocketDisconnect
        game = self.prepare()
        self.activate(game["id"])
        url = f'/game?token={self.headers["Authorization"][7:]}&game_id={game["id"]}'
        with self.client.websocket_connect(url) as first:
            first.receive_json()
            with self.assertRaises(WebSocketDisconnect) as caught:
                with self.client.websocket_connect(url):
                    pass
            self.assertEqual(caught.exception.code, 4409)
            self.assertEqual(self.app.state.store.get_game(1, game["id"])["status"], "playing")

    def test_disconnect_freezes_timer_and_recreates_only_this_games_runtime(self) -> None:
        game = self.prepare()
        self.activate(game["id"])
        with self.client.websocket_connect(f'/game?token={self.headers["Authorization"][7:]}&game_id={game["id"]}') as ws:
            ws.receive_json()
            engine = self.app.state.game_service.sessions[game["id"]]
            engine._require_state().investigation_deadline_at = time.time() + 300
            engine._require_state().autonomy_next_at = time.time() + 60
            self.app.state.game_service.persist_engine_events(game["id"], engine)
            run_id = self.app.state.store.get_game(1, game["id"])["run_id"]
        paused = self.app.state.store.get_game(1, game["id"])
        self.assertEqual(paused["status"], "paused")
        self.assertNotIn(game["id"], self.app.state.game_service.sessions)
        snapshot = self.app.state.store.get_runtime_snapshot(1, game["id"])
        old_deadline = snapshot["state"]["investigation_deadline_at"]
        self.app.state.store.set_game_lifecycle(game["id"], paused_at=paused["paused_at"] - 600)
        with self.client.websocket_connect(f'/game?token={self.headers["Authorization"][7:]}&game_id={game["id"]}') as ws:
            ws.receive_json()
            resumed = self.app.state.game_service.sessions[game["id"]]
            self.assertIsNot(resumed, engine)
            self.assertGreater(resumed._require_state().investigation_deadline_at - old_deadline, 599)
            self.assertNotEqual(self.app.state.store.get_game(1, game["id"])["run_id"], run_id)

    def test_new_wrong_ending_reveals_truth_without_changing_legacy_policy(self) -> None:
        self.script = single_stage_script(self.script)
        self.script["stage_flow"]["stage_1"]["resolution"]["final_decision"]["eligible_role_ids"] = ["shen_zhiwei", "gu_linchuan"]
        published = self.client.post("/api/v1/scripts", headers=self.headers, json={"script": self.script, "title": "错判测试", "tags": []}).json()
        self.item = published
        game = self.prepare()
        self.activate(game["id"])
        dm = self.app.state.game_service.sessions[game["id"]]
        import asyncio
        async def finish():
            await advance_to_investigation(dm)
            dm.end_investigation("player_request")
            with patch.object(dm, "_call_agent", new=AsyncMock(return_value=("shen_zhiwei", False))):
                await dm.cast_stage_vote("shen_zhiwei")
            return (await dm.advance_scene_phase())["replay"]
        replay = asyncio.run(finish())
        self.assertFalse(replay["final_decision"]["correct"])
        self.assertTrue(replay["truth_revealed"])
        self.assertEqual(replay["full_story"], self.script["truth"]["full_story"])

    def test_new_routes_require_auth_and_do_not_cache_shell(self) -> None:
        for path in ("/play", "/scripts/new", "/games/1/prepare", "/games/1"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store, private")
        self.assertEqual(TestClient(self.app).get("/api/v1/scripts").status_code, 401)


class GameSchemaMigrationTest(unittest.TestCase):
    def test_old_game_ids_events_and_deleted_id_sequence_survive_nullable_role_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            with sqlite3.connect(path) as connection:
                connection.executescript("""CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT, created_at TEXT);
                    INSERT INTO users VALUES (1, 'old', 'unused', '2020');
                    CREATE TABLE games(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL,
                      category TEXT NOT NULL, mode TEXT NOT NULL, player_role_id TEXT NOT NULL, ai_agent_count INTEGER NOT NULL,
                      current_stage INTEGER NOT NULL DEFAULT 1, current_phase TEXT NOT NULL DEFAULT 'investigation', total_stages INTEGER NOT NULL,
                      status TEXT NOT NULL DEFAULT 'playing', script_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    INSERT INTO games VALUES (18, 1, 'old', 'mystery', 'deduction', 'role', 1, 1, 'briefing', 2, 'playing', '{}', '2020', '2020');
                    UPDATE sqlite_sequence SET seq = 30 WHERE name = 'games';
                    CREATE TABLE game_events(id INTEGER PRIMARY KEY AUTOINCREMENT, game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,
                      event_type TEXT, payload_json TEXT, created_at TEXT);
                    INSERT INTO game_events VALUES (1, 18, 'old', '{}', '2020');""")
            connection.close()
            store = AppStore(path)
            self.assertEqual(store.get_game(1, 18)["player_role_id"], "role")
            self.assertEqual(len(store.list_events(1, 18)), 1)
            script = json.loads((ROOT / "backend/resources/scripts/fog_harbor_clocktower.json").read_text(encoding="utf-8"))
            new = store.prepare_game(1, script, "builtin", "v1")
            self.assertGreater(new["id"], 30)
            self.assertIsNone(new["player_role_id"])
            store.delete_game(1, 18)
            with store._connect() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM game_events WHERE game_id=18").fetchone()[0], 0)
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
