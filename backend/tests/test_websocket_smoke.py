from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*")
os.environ["LLM_PROVIDER"] = "echo"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "app"))

from fastapi.testclient import TestClient
_IMPORT_DATA_DIRECTORY = tempfile.TemporaryDirectory()
with patch.dict(os.environ, {"AI_MURDER_MYSTERY_DATA_DIR": _IMPORT_DATA_DIRECTORY.name}):
    from main import create_app
from backend.tests.test_engine_flow import actual_input
from backend.tests.script_fixtures import single_stage_script


class WebSocketSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(
            create_app(
                Path(self.temp_dir.name) / "test.db",
                allow_legacy_token_response=True,
            )
        )
        auth = self.client.post("/api/auth/register", json={"username": "socket_user", "password": "secret12"}).json()
        self.token = auth["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.script = json.loads(
            (BACKEND_ROOT / "resources" / "scripts" / "flame_mountain.json").read_text(encoding="utf-8")
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_authenticated_websocket_game_flow(self) -> None:
        health = self.client.get("/health")
        self.assertEqual(health.json(), {"status": "ok"})
        creation = self.client.post(
            "/api/games",
            headers=self.headers,
            json={
                "category": "fantasy",
                "mode": "narrative",
                "player_role_id": "red_boy",
                "script": self.script,
            },
        )
        self.assertEqual(creation.status_code, 200)
        game = creation.json()
        self.assertEqual(game["orchestration"]["ai_agent_count"], 2)

        with self.client.websocket_connect(f"/game?token={self.token}&game_id={game['id']}") as ws:
            init = ws.receive_json()
            self.assertEqual(init["type"], "game_init")
            self.assertTrue(init["orchestration"]["truth_loaded"])
            self.assertEqual(len(init["dispatch"]["deliveries"]), 3)

            ws.send_json({"type": "player_speech", "content": "孙悟空，你为何来我火焰山？"})
            echo = ws.receive_json()
            ai_reply = ws.receive_json()
            self.assertEqual(echo["type"], "human_speech_echo")
            self.assertEqual(ai_reply["type"], "ai_speech")
            self.assertEqual(ai_reply["role_id"], "monkey_king")

            ws.send_json({"type": "search", "target_id": "mountain_pass"})
            search = ws.receive_json()
            self.assertEqual(search["clue"]["id"], "clue_heat_gap")

            ws.send_json(
                {
                    "type": "share_clue",
                    "clue_id": "clue_heat_gap",
                    "mode": "distorted",
                    "content": "旧石碑附近的火势最强，靠近那里十分危险。",
                    "scope": "public",
                }
            )
            disclosure = ws.receive_json()
            self.assertEqual(disclosure["type"], "clue_disclosed")
            self.assertEqual(disclosure["owner_view_mode"], "distorted")

            ws.send_json({"type": "whisper_invite", "target_role_id": "monkey_king"})
            accepted = ws.receive_json()
            self.assertEqual(accepted["type"], "whisper_accepted")

            ws.send_json({"type": "whisper_speech", "content": "这句话只说给你听。"})
            private_player = ws.receive_json()
            private_agent = ws.receive_json()
            self.assertEqual(private_player["type"], "whisper_message")
            self.assertEqual(private_agent["sender_role_id"], "monkey_king")

            ws.send_json({"type": "request_advance"})
            advance = ws.receive_json()
            self.assertEqual(advance["stage"], 2)
            self.assertEqual(advance["dispatch"]["stage"], 2)
            self.assertIsNone(advance["whisper_status"]["active_target_role_id"])

        records = self.client.get("/api/games", headers=self.headers).json()
        self.assertEqual(records[0]["current_stage"], 2)
        notebook = self.client.get(
            f"/api/games/{game['id']}/notebook",
            headers=self.headers,
        ).json()
        self.assertEqual(notebook["clues"][0]["disclosure_mode"], "distorted")
        self.assertIn("火势明显较弱", notebook["clues"][0]["truth_content"])
        self.assertIn("火势最强", notebook["clues"][0]["shared_content"])

    def test_runtime_snapshot_restores_websocket_history_and_active_whisper(self) -> None:
        creation = self.client.post(
            "/api/games",
            headers=self.headers,
            json={
                "category": "fantasy",
                "mode": "narrative",
                "player_role_id": "red_boy",
                "script": self.script,
            },
        ).json()
        game_id = creation["id"]

        with self.client.websocket_connect(
            f"/game?token={self.token}&game_id={game_id}"
        ) as ws:
            initial = ws.receive_json()
            self.assertEqual(initial["sync"]["snapshot_version"], 1)
            ws.send_json(
                {
                    "type": "player_speech",
                    "content": "孙悟空，我们先核对山路上的火势。",
                }
            )
            self.assertEqual(ws.receive_json()["type"], "human_speech_echo")
            self.assertEqual(ws.receive_json()["type"], "ai_speech")
            ws.send_json(
                {
                    "type": "whisper_invite",
                    "target_role_id": "monkey_king",
                }
            )
            self.assertEqual(ws.receive_json()["type"], "whisper_accepted")
            ws.send_json(
                {
                    "type": "whisper_speech",
                    "content": "这段约定只能由我们两人知道。",
                }
            )
            self.assertEqual(ws.receive_json()["sender_type"], "player")
            self.assertEqual(ws.receive_json()["sender_type"], "agent")

        user_id = self.client.app.state.store.user_for_token(self.token)["id"]
        snapshot = self.client.app.state.store.get_runtime_snapshot(
            user_id,
            game_id,
        )
        self.assertIsNotNone(snapshot)
        restarted_client = TestClient(
            create_app(
                Path(self.temp_dir.name) / "test.db",
                allow_legacy_token_response=True,
            )
        )
        try:
            with restarted_client.websocket_connect(
                f"/game?token={self.token}&game_id={game_id}"
            ) as ws:
                restored = ws.receive_json()
                event_types = [
                    event["type"] for event in restored["history_events"]
                ]
                self.assertEqual(
                    restored["sync"]["event_count"],
                    len(restored["history_events"]),
                )
                self.assertIn("human_speech_echo", event_types)
                self.assertEqual(event_types.count("whisper_message"), 2)
                self.assertEqual(
                    restored["whisper_status"]["active_target_role_id"],
                    "monkey_king",
                )
                ws.send_json(
                    {
                        "type": "whisper_speech",
                        "content": "重连之后继续这段私聊。",
                    }
                )
                self.assertEqual(ws.receive_json()["sender_type"], "player")
                self.assertEqual(ws.receive_json()["sender_type"], "agent")

            dm = restarted_client.app.state.game_service.sessions[game_id]
            monkey_prompt = actual_input(dm, "monkey_king")
            guanyin_prompt = actual_input(dm, "guanyin")
            self.assertIn("这段约定只能由我们两人知道", monkey_prompt)
            self.assertNotIn("这段约定只能由我们两人知道", guanyin_prompt)
        finally:
            restarted_client.close()

    def test_scene_flow_streams_briefing_then_opens_investigation(self) -> None:
        script = json.loads(
            (BACKEND_ROOT / "resources" / "scripts" / "fog_harbor_clocktower.json").read_text(
                encoding="utf-8"
            )
        )
        script.pop("opening", None)
        creation = self.client.post(
            "/api/games",
            headers=self.headers,
            json={
                "category": "mystery",
                "mode": "deduction",
                "player_role_id": "shen_zhiwei",
                "script": script,
            },
        )
        self.assertEqual(creation.status_code, 200)
        game = creation.json()
        self.assertEqual(game["current_phase"], "briefing")

        with self.client.websocket_connect(f"/game?token={self.token}&game_id={game['id']}") as ws:
            init = ws.receive_json()
            self.assertEqual(init["phase"]["phase"], "briefing")
            briefing = self._receive_until(ws, "dm_narration_end")
            chunks = [
                item["content"]
                for item in briefing
                if item["type"] == "dm_narration_chunk"
            ]
            self.assertIn("暴雨封锁雾港", "".join(chunks))

            ws.send_json({"type": "advance_phase"})
            private_messages = [ws.receive_json(), ws.receive_json()]
            self.assertEqual(private_messages[0]["phase"]["phase"], "private_reveal")
            self.assertEqual(private_messages[1]["type"], "private_script")
            self.assertEqual(private_messages[1]["assignment"]["role_name"], "沈知微")

            ws.send_json({"type": "advance_phase"})
            investigation_messages = [ws.receive_json(), ws.receive_json()]
            self.assertEqual(investigation_messages[0]["phase"]["phase"], "investigation")
            self.assertEqual(investigation_messages[1]["type"], "investigation_open")
            self.assertIn(
                "public_speech",
                investigation_messages[1]["phase"]["enabled_actions"],
            )

            ws.send_json({"type": "request_phase_end"})
            hosting = self._receive_until(ws, "dm_narration_end")
            self.assertEqual(hosting[0]["type"], "investigation_end_vote")
            self.assertTrue(hosting[0]["vote"]["approved"])
            self.assertEqual(hosting[0]["vote"]["required_votes"], 3)
            self.assertEqual(hosting[1]["phase"]["phase"], "dm_hosting")

        detail = self.client.get(
            f"/api/games/{game['id']}",
            headers=self.headers,
        ).json()
        self.assertEqual(detail["current_phase"], "dm_hosting")

    def test_completed_scene_flow_reopens_at_replay(self) -> None:
        script = json.loads(
            (BACKEND_ROOT / "resources" / "scripts" / "fog_harbor_clocktower.json").read_text(
                encoding="utf-8"
            )
        )
        script = single_stage_script(script)
        creation = self.client.post(
            "/api/games",
            headers=self.headers,
            json={
                "category": "mystery",
                "mode": "deduction",
                "player_role_id": "shen_zhiwei",
                "script": script,
            },
        ).json()

        with self.client.websocket_connect(
            f"/game?token={self.token}&game_id={creation['id']}"
        ) as ws:
            init = ws.receive_json()
            self._open_investigation(ws, init["phase"]["phase"])
            ws.send_json({"type": "request_phase_end"})
            self._receive_until(ws, "dm_narration_end")
            ws.send_json(
                {"type": "stage_vote", "target_role_id": "gu_linchuan"}
            )
            decision = ws.receive_json()
            self.assertEqual(decision["type"], "stage_resolution")
            self.assertFalse(decision["resolution"]["vote"]["pending"])
            ws.send_json({"type": "advance_phase"})
            replay = ws.receive_json()
            self.assertEqual(replay["type"], "replay")
            self.assertTrue(replay["truth_revealed"])

        detail = self.client.get(
            f"/api/games/{creation['id']}",
            headers=self.headers,
        ).json()
        self.assertEqual(detail["status"], "completed")
        self.assertEqual(detail["current_phase"], "replay")

        with self.client.websocket_connect(
            f"/game?token={self.token}&game_id={creation['id']}"
        ) as ws:
            init = ws.receive_json()
            changed = ws.receive_json()
            replay = ws.receive_json()
            self.assertEqual(init["phase"]["phase"], "replay")
            self.assertEqual(changed["phase"]["phase"], "replay")
            self.assertEqual(replay["type"], "replay")

    def test_completed_game_exposes_role_notebooks_and_action_audit(self) -> None:
        script = json.loads(
            (BACKEND_ROOT / "resources" / "scripts" / "fog_harbor_clocktower.json").read_text(
                encoding="utf-8"
            )
        )
        script = single_stage_script(script)
        investigation = script["stage_flow"]["stage_1"]["investigation"]
        investigation["end_conditions"] = {}
        investigation["autonomy"]["max_turns"] = 0
        creation = self.client.post(
            "/api/games",
            headers=self.headers,
            json={
                "category": "mystery",
                "mode": "deduction",
                "player_role_id": "shen_zhiwei",
                "script": script,
            },
        ).json()
        game_id = creation["id"]
        self.client.put(
            f"/api/games/{game_id}/notebook/manual",
            headers=self.headers,
            json={"content": "顾临川的时间线需要与停表时间交叉验证。"},
        )

        with self.client.websocket_connect(
            f"/game?token={self.token}&game_id={game_id}"
        ) as ws:
            init = ws.receive_json()
            self._open_investigation(ws, init["phase"]["phase"])

            ws.send_json(
                {
                    "type": "player_speech",
                    "content": "顾临川，请说明停电时你在哪里。",
                }
            )
            self.assertEqual(ws.receive_json()["type"], "human_speech_echo")
            self.assertEqual(ws.receive_json()["type"], "ai_speech")
            speech_progress = ws.receive_json()
            self.assertEqual(speech_progress["type"], "investigation_progress")
            self.assertFalse(speech_progress["condition"]["met"])

            ws.send_json({"type": "search", "target_id": "archive_desk"})
            self.assertEqual(ws.receive_json()["type"], "search_result")
            search_progress = ws.receive_json()
            self.assertEqual(search_progress["type"], "investigation_progress")
            self.assertFalse(search_progress["condition"]["auto_end"])

            ws.send_json({"type": "request_phase_end"})
            self._receive_until(ws, "dm_narration_end")
            ws.send_json(
                {"type": "stage_vote", "target_role_id": "gu_linchuan"}
            )
            self.assertEqual(ws.receive_json()["type"], "stage_resolution")
            ws.send_json({"type": "advance_phase"})
            self.assertEqual(ws.receive_json()["type"], "replay")

        audit = self.client.get(
            f"/api/games/{game_id}/role-records",
            headers=self.headers,
        )
        self.assertEqual(audit.status_code, 200)
        audit_payload = audit.json()
        self.assertTrue(audit_payload["stage_resolutions"])
        self.assertEqual(audit_payload["final_decision"]["kind"], "final")
        roles = {role["role_id"]: role for role in audit_payload["roles"]}
        self.assertEqual(len(roles), 4)

        human = roles["shen_zhiwei"]
        self.assertTrue(human["stage_results"])
        human_sources = {
            entry["source_type"]
            for entry in human["automatic_notebook"]
        }
        self.assertTrue(
            {
                "opening",
                "public_briefing",
                "public_tasks",
                "public_information",
                "dm_hosting",
            }.issubset(human_sources)
        )
        self.assertIn(
            "search",
            [entry["source_type"] for entry in human["automatic_notebook"]],
        )
        self.assertIn(
            "顾临川的时间线",
            "\n".join(entry["content"] for entry in human["reasoning_notebook"]),
        )
        self.assertTrue(
            {"public_speech", "search"}.issubset(
                {operation["event_type"] for operation in human["operations"]}
            )
        )

        doctor = roles["gu_linchuan"]
        self.assertIn(
            "public_conversation",
            [entry["source_type"] for entry in doctor["automatic_notebook"]],
        )
        self.assertIn(
            "public_response",
            [operation["event_type"] for operation in doctor["operations"]],
        )

    def test_scene_flow_emits_unsolicited_agent_action(self) -> None:
        script = json.loads(
            (BACKEND_ROOT / "resources" / "scripts" / "fog_harbor_clocktower.json").read_text(
                encoding="utf-8"
            )
        )
        autonomy = script["stage_flow"]["stage_1"]["investigation"]["autonomy"]
        autonomy["initial_delay_seconds"] = 0
        autonomy["interval_seconds"] = 999
        autonomy["max_turns"] = 1
        creation = self.client.post(
            "/api/games",
            headers=self.headers,
            json={
                "category": "mystery",
                "mode": "deduction",
                "player_role_id": "shen_zhiwei",
                "script": script,
            },
        ).json()

        with self.client.websocket_connect(
            f"/game?token={self.token}&game_id={creation['id']}"
        ) as ws:
            init = ws.receive_json()
            opened = self._open_investigation(ws, init["phase"]["phase"])
            self.assertTrue(opened["phase"]["autonomy"]["enabled"])

            activity = ws.receive_json()
            proactive = ws.receive_json()
            autonomy_status = ws.receive_json()
            self.assertEqual(activity["type"], "agent_activity_start")
            self.assertEqual(proactive["type"], "ai_proactive_speech")
            self.assertEqual(proactive["target_role_id"], "shen_zhiwei")
            self.assertEqual(autonomy_status["type"], "autonomy_status")
            self.assertFalse(autonomy_status["autonomy"]["enabled"])

        detail = self.client.get(
            f"/api/games/{creation['id']}",
            headers=self.headers,
        ).json()
        self.assertIn(
            "ai_proactive_speech",
            [event["type"] for event in detail["events"]],
        )

    def _open_investigation(self, ws: object, phase: str) -> dict[str, object]:
        for _ in range(4):
            if phase == "investigation":
                return self._receive_until(ws, "investigation_open")[-1]
            if phase in {"opening", "briefing"}:
                self._receive_until(ws, "dm_narration_end")
            elif phase == "private_reveal":
                self._receive_until(ws, "private_script")
            else:
                self.fail(f"Unexpected introductory phase: {phase}")
            ws.send_json({"type": "advance_phase"})
            changed = ws.receive_json()
            self.assertEqual(changed["type"], "phase_changed")
            phase = changed["phase"]["phase"]
        self.fail("Investigation did not open after the introduction")

    @staticmethod
    def _receive_until(ws: object, terminal_type: str) -> list[dict[str, object]]:
        messages: list[dict[str, object]] = []
        while True:
            message = ws.receive_json()
            messages.append(message)
            if message["type"] == terminal_type:
                return messages


if __name__ == "__main__":
    unittest.main()
