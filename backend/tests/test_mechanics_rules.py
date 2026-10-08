from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "app"))

from backend.tests.test_engine_flow import build_engine
from main import create_app


class EndingReviewBoundaryTest(TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.temp.name) / "rules.db"))
        auth = self.client.post("/api/v1/auth/register", json={
            "username": "rules_player", "password": "secret12",
        }).json()
        self.headers = {"X-CSRF-Token": auth["csrf_token"]}
        self.script = json.loads((BACKEND_ROOT / "resources" / "scripts" /
                                  "fog_harbor_clocktower.json").read_text(encoding="utf-8"))
        self.script["script_meta"]["total_stages"] = 1
        self.script["stage_flow"]["stage_1"]["resolution"]["final_decision"][
            "eligible_role_ids"] = ["shen_zhiwei", "gu_linchuan"]
        created = self.client.post("/api/v1/games", headers=self.headers, json={
            "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei",
            "script": self.script,
        })
        self.assertEqual(created.status_code, 200)
        self.game_id = created.json()["id"]

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def complete(self, *, correct: bool) -> dict:
        service = self.client.app.state.game_service
        dm = service.sessions[self.game_id]

        async def finish() -> dict:
            await dm.advance_scene_phase()
            await dm.advance_scene_phase()
            await dm.handle_mechanic_action({"type": "search", "target_id": "archive_desk"})
            dm.end_investigation("timeout")
            if correct:
                resolution = await dm.cast_stage_vote("gu_linchuan")
            else:
                with patch.object(dm, "_call_agent", new=AsyncMock(return_value=("shen_zhiwei", False))):
                    resolution = await dm.cast_stage_vote("shen_zhiwei")
            service.record_responses(self.game_id, dm, [{"type": "stage_resolution", "resolution": resolution}])
            replay = (await dm.advance_scene_phase())["replay"]
            service.record_responses(self.game_id, dm, [{"type": "replay", **replay}])
            return replay

        return asyncio.run(finish())

    def test_wrong_ending_denies_all_role_audit_but_keeps_own_notebook_and_public_vote(self) -> None:
        replay = self.complete(correct=False)
        self.assertFalse(replay["truth_revealed"])
        for prefix in ("/api", "/api/v1"):
            response = self.client.get(f"{prefix}/games/{self.game_id}/role-records")
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("agent_context_audits", response.text)
            self.assertNotIn("truth_content", response.text)
        notebook = self.client.get(f"/api/v1/games/{self.game_id}/notebook")
        self.assertEqual(notebook.status_code, 200)
        self.assertTrue(notebook.json()["clues"])
        self.assertEqual(notebook.json()["role_id"], "shen_zhiwei")
        events = self.client.get(f"/api/v1/games/{self.game_id}").json()
        ending = next(event["payload"] for event in events["events"] if event["type"] == "replay")
        self.assertEqual(ending["final_decision"]["selected_role_id"], "shen_zhiwei")
        self.assertTrue(ending["final_decision"]["ballots"])
        self.assertEqual(ending["timeline"], {})

    def test_wrong_ending_stays_private_after_session_restore(self) -> None:
        self.complete(correct=False)
        service = self.client.app.state.game_service
        service.sessions.clear()
        asyncio.run(service.get_engine(1, self.game_id))
        self.assertEqual(self.client.get(f"/api/v1/games/{self.game_id}/role-records").status_code, 403)
        self.assertEqual(self.client.get(f"/api/v1/games/{self.game_id}/notebook").status_code, 200)

    def test_correct_ending_keeps_full_audit_available(self) -> None:
        self.assertTrue(self.complete(correct=True)["truth_revealed"])
        response = self.client.get(f"/api/v1/games/{self.game_id}/role-records")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["roles"]), 4)
        self.assertTrue(any(role["agent_context_audits"] for role in response.json()["roles"]))

    def test_completed_status_without_revealed_truth_cannot_open_audit(self) -> None:
        self.client.app.state.store.update_game(self.game_id, 1, "completed", "replay")
        self.assertEqual(self.client.get(f"/api/v1/games/{self.game_id}/role-records").status_code, 403)

    def test_wrong_snapshot_cannot_be_overridden_by_an_older_reveal_event(self) -> None:
        self.complete(correct=False)
        self.client.app.state.store.add_event(self.game_id, "replay", {"truth_revealed": True})
        self.assertEqual(self.client.get(f"/api/v1/games/{self.game_id}/role-records").status_code, 403)

    def test_nonfinal_resolution_does_not_authorize_audit(self) -> None:
        script = json.loads((BACKEND_ROOT / "resources" / "scripts" /
                             "fog_harbor_clocktower.json").read_text(encoding="utf-8"))
        game_id = self.client.post("/api/v1/games", headers=self.headers, json={
            "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei",
            "script": script,
        }).json()["id"]
        store = self.client.app.state.store
        snapshot = store.get_runtime_snapshot(1, game_id)
        snapshot["state"]["stage_resolutions"] = {"1": {
            "stage": 1, "resolved": True,
            "vote": {"kind": "final", "pending": False, "truth_revealed": True},
        }}
        store.save_runtime_snapshot(game_id, snapshot)
        store.update_game(game_id, 3, "completed", "replay")
        self.assertEqual(self.client.get(f"/api/v1/games/{game_id}/role-records").status_code, 403)

    def test_legacy_replay_can_authorize_only_an_explicit_true_flag(self) -> None:
        store = self.client.app.state.store
        store.update_game(self.game_id, 1, "completed", "replay")
        with store._connect() as connection:
            connection.execute("DELETE FROM game_runtime_snapshots WHERE game_id = ?", (self.game_id,))
        for value in (False, "true", 1, None):
            with self.subTest(truth_revealed=value):
                store.add_event(self.game_id, "replay", {"truth_revealed": value})
                self.assertEqual(self.client.get(f"/api/v1/games/{self.game_id}/role-records").status_code, 403)
        store.add_event(self.game_id, "replay", {"truth_revealed": True})
        self.assertEqual(self.client.get(f"/api/v1/games/{self.game_id}/role-records").status_code, 200)
        service = self.client.app.state.game_service
        service.sessions.clear()
        asyncio.run(service.get_engine(1, self.game_id))
        self.assertEqual(self.client.get(f"/api/v1/games/{self.game_id}/role-records").status_code, 200)


class InvestigationVoteParsingTest(IsolatedAsyncioTestCase):
    async def test_only_exact_approval_tokens_count_toward_majority(self) -> None:
        dm = build_engine()
        await dm.init_game("fog_harbor_clocktower", "shen_zhiwei", "deduction")
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        for raw in ("APPROVE_NOT", "APPROVE or REJECT", "APPROVE\nREJECT", "同意不了", "同意，但我拒绝"):
            with self.subTest(raw=raw):
                with patch.object(dm, "_call_agent", new=AsyncMock(return_value=(raw, False))):
                    vote = await dm.request_investigation_end_vote()
                self.assertFalse(vote["approved"])
                self.assertEqual(vote["approved_votes"], 1)
        for raw in ("APPROVE", " approve ", "同意"):
            with self.subTest(raw=raw):
                with patch.object(dm, "_call_agent", new=AsyncMock(return_value=(raw, False))):
                    vote = await dm.request_investigation_end_vote()
                self.assertTrue(vote["approved"])
                self.assertEqual(vote["approved_votes"], 4)

    async def test_provider_failure_does_not_become_an_approval(self) -> None:
        dm = build_engine()
        await dm.init_game("fog_harbor_clocktower", "shen_zhiwei", "deduction")
        await dm.advance_scene_phase()
        await dm.advance_scene_phase()
        with patch.object(dm, "_call_agent", new=AsyncMock(return_value=("APPROVE", True))):
            vote = await dm.request_investigation_end_vote()
        self.assertFalse(vote["approved"])
        self.assertEqual(vote["approved_votes"], 1)
