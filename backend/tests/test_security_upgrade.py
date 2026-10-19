from __future__ import annotations

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
from starlette.websockets import WebSocketDisconnect


class SecurityUpgradeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.temp_dir.name) / "test.db"))
        self.script = json.loads(
            (BACKEND_ROOT / "resources" / "scripts" / "flame_mountain.json").read_text(
                encoding="utf-8"
            )
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def register(self, username: str = "secure_user") -> dict[str, object]:
        response = self.client.post(
            "/api/auth/register",
            json={"username": username, "password": "secret12"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_cookie_auth_does_not_expose_session_token(self) -> None:
        payload = self.register()

        self.assertNotIn("token", payload)
        self.assertIn("csrf_token", payload)
        session_cookie = self.client.cookies.get("ai_mm_session")
        self.assertTrue(session_cookie)
        self.assertIn("HttpOnly", self.client.post(
            "/api/auth/login",
            json={"username": "secure_user", "password": "secret12"},
        ).headers["set-cookie"])

        me = self.client.get("/api/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["username"], "secure_user")
        self.assertEqual(me.headers["cache-control"], "no-store, private")

    def test_cookie_write_requires_csrf_and_logout_revokes_session(self) -> None:
        payload = self.register()
        denied = self.client.post(
            "/api/games",
            json={
                "category": "fantasy",
                "mode": "narrative",
                "player_role_id": "red_boy",
                "script": self.script,
            },
        )
        self.assertEqual(denied.status_code, 403)

        logout = self.client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": str(payload["csrf_token"])},
        )
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_websocket_ticket_is_one_time_and_internal_events_are_forbidden(self) -> None:
        payload = self.register()
        csrf_headers = {"X-CSRF-Token": str(payload["csrf_token"])}
        creation = self.client.post(
            "/api/games",
            headers=csrf_headers,
            json={
                "category": "fantasy",
                "mode": "narrative",
                "player_role_id": "red_boy",
                "script": self.script,
            },
        )
        self.assertEqual(creation.status_code, 200)
        game_id = creation.json()["id"]
        ticket_response = self.client.post(
            f"/api/games/{game_id}/ws-ticket",
            headers=csrf_headers,
        )
        self.assertEqual(ticket_response.status_code, 200)
        ticket = ticket_response.json()["ticket"]
        ws_path = f"/ws/v1/games/{game_id}?ticket={ticket}"

        with self.client.websocket_connect(ws_path) as ws:
            snapshot = ws.receive_json()
            self.assertEqual(snapshot["kind"], "snapshot")
            self.assertEqual(snapshot["payload"]["game"]["type"], "game_init")
            ws.send_json(
                {
                    "protocol_version": "1.0",
                    "kind": "command",
                    "type": "phase_timeout",
                    "request_id": "forbidden-command-1",
                    "game_id": game_id,
                    "payload": {},
                }
            )
            forbidden = ws.receive_json()
            self.assertEqual(forbidden["kind"], "error")
            self.assertEqual(
                forbidden["payload"]["code"],
                "WS_COMMAND_FORBIDDEN",
            )

        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(ws_path) as ws:
                ws.receive_json()

    def test_v1_command_idempotency_and_incremental_events(self) -> None:
        payload = self.register()
        csrf_headers = {"X-CSRF-Token": str(payload["csrf_token"])}
        game_id = self.client.post(
            "/api/v1/games",
            headers=csrf_headers,
            json={
                "category": "fantasy",
                "mode": "narrative",
                "player_role_id": "red_boy",
                "script": self.script,
            },
        ).json()["id"]
        ticket = self.client.post(
            f"/api/v1/games/{game_id}/ws-ticket",
            headers=csrf_headers,
        ).json()["ticket"]
        command = {
            "protocol_version": "1.0",
            "kind": "command",
            "type": "player_speech",
            "request_id": "idempotent-command-1",
            "game_id": game_id,
            "payload": {"content": "孙悟空，请说明你来火焰山的目的。"},
        }

        with self.client.websocket_connect(
            f"/ws/v1/games/{game_id}?ticket={ticket}"
        ) as ws:
            self.assertEqual(ws.receive_json()["kind"], "snapshot")
            ws.send_json(
                {
                    **command,
                    "request_id": "invalid-command-1",
                    "payload": {
                        "content": "有效内容",
                        "unexpected": "不允许的字段",
                    },
                }
            )
            invalid = ws.receive_json()
            self.assertEqual(invalid["kind"], "error")
            self.assertEqual(
                invalid["payload"]["code"],
                "WS_COMMAND_INVALID",
            )
            ws.send_json(command)
            first_events = [ws.receive_json(), ws.receive_json()]
            self.assertEqual(
                [event["type"] for event in first_events],
                ["human_speech_echo", "ai_speech"],
            )
            ws.send_json(command)
            replayed_events = [ws.receive_json(), ws.receive_json()]
            self.assertEqual(
                [event["event_id"] for event in replayed_events],
                [event["event_id"] for event in first_events],
            )

        event_page = self.client.get(
            f"/api/v1/games/{game_id}/events",
        )
        self.assertEqual(event_page.status_code, 200)
        items = event_page.json()["items"]
        self.assertEqual(len(items), 2)
        self.assertTrue(
            all(item["request_id"] == "idempotent-command-1" for item in items)
        )
        delta = self.client.get(
            f"/api/v1/games/{game_id}/events",
            params={"after_event_id": items[0]["event_id"]},
        ).json()
        self.assertEqual(len(delta["items"]), 1)
        self.assertEqual(delta["items"][0]["event_id"], items[1]["event_id"])

    def test_v1_errors_are_structured(self) -> None:
        response = self.client.get("/api/v1/games")
        self.assertEqual(response.status_code, 401)
        body = response.json()
        self.assertEqual(body["code"], "AUTH_REQUIRED")
        self.assertTrue(body["request_id"])
        self.assertEqual(response.headers["X-Request-ID"], body["request_id"])

        schema = self.client.get("/openapi.json").json()
        self.assertIn("/api/v1/games/{game_id}/events", schema["paths"])
        game_list_schema = schema["paths"]["/api/v1/games"]["get"][
            "responses"
        ]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(game_list_schema["type"], "array")

    def test_case_routes_serve_spa_shell_without_cache(self) -> None:
        for path in ("/login", "/register", "/cases/new", "/cases", "/cases/123", "/personal-center"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("剧镜", response.text)
                self.assertEqual(response.headers["cache-control"], "no-store, private")

    def test_login_rate_limit_and_script_complexity_limit(self) -> None:
        payload = self.register()
        self.client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": str(payload["csrf_token"])},
        )
        for _ in range(5):
            failed = self.client.post(
                "/api/auth/login",
                json={"username": "secure_user", "password": "wrong-password"},
            )
            self.assertEqual(failed.status_code, 401)
        limited = self.client.post(
            "/api/auth/login",
            json={"username": "secure_user", "password": "wrong-password"},
        )
        self.assertEqual(limited.status_code, 429)
        self.assertIn("Retry-After", limited.headers)

        second_client = TestClient(create_app(Path(self.temp_dir.name) / "second.db"))
        try:
            second_auth = second_client.post(
                "/api/auth/register",
                json={"username": "script_user", "password": "secret12"},
            ).json()
            oversized_roles = {
                "roles": [{"role_id": f"role_{index}"} for index in range(51)]
            }
            rejected = second_client.post(
                "/api/scripts/inspect",
                headers={"X-CSRF-Token": second_auth["csrf_token"]},
                json={"mode": "narrative", "script": oversized_roles},
            )
            self.assertEqual(rejected.status_code, 400)
            self.assertIn("角色不能超过", rejected.json()["detail"])
        finally:
            second_client.close()


if __name__ == "__main__":
    unittest.main()
