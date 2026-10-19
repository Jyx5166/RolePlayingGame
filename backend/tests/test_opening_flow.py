from __future__ import annotations

import asyncio
import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from backend.tests.test_engine_flow import build_engine
from domain.state import ScenePhase
from ws.handlers import build_phase_messages


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class OpeningFlowTest(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.legacy_script = json.loads(
            (BACKEND_ROOT / "resources" / "scripts" / "fog_harbor_clocktower.json").read_text(
                encoding="utf-8"
            )
        )
        self.legacy_script.pop("opening", None)
        self.script = deepcopy(self.legacy_script)
        self.script["opening"] = {
            "title": "夜宴之前",
            "content": "独立开幕：暴雨中的钟楼亮起了最后一盏灯，宾客正等待夜宴开始。",
        }

    async def new_engine(self, script: dict | None = None):
        dm = build_engine()
        await dm.init_game_from_script(
            deepcopy(self.script if script is None else script), "shen_zhiwei", "deduction"
        )
        return dm

    async def test_opening_precedes_private_script_and_first_stage_briefing(self) -> None:
        dm = await self.new_engine()
        self.assertTrue(dm.has_opening())
        for phase, before_first_stage, title, continue_label in (
            (ScenePhase.OPENING, True, self.script["opening"]["title"], "接收角色剧本"),
            (ScenePhase.PRIVATE_REVEAL, True, "角色剧本", "开始第一幕"),
            (ScenePhase.BRIEFING, False, self.script["stage_flow"]["stage_1"]["title"], "开始调查"),
        ):
            with self.subTest(phase=phase.value):
                summary = dm.get_scene_summary()
                self.assertEqual(dm.state.scene_phase, phase)
                self.assertEqual(summary["phase"], phase.value)
                self.assertTrue(summary["has_opening"])
                self.assertEqual(summary["before_first_stage"], before_first_stage)
                self.assertEqual(summary["stage_title"], title)
                self.assertEqual(summary["continue_label"], continue_label)
                if before_first_stage:
                    self.assertEqual(summary["enabled_actions"], [])
                    self.assertEqual(summary["public_tasks"], [])
                    self.assertEqual(summary["duration_seconds"], 0)
                await dm.advance_scene_phase()

        self.assertEqual(dm.state.scene_phase, ScenePhase.INVESTIGATION)
        self.assertEqual(dm.state.current_stage_num, 1)
        self.assertEqual(
            dm.get_briefing_narration(),
            self.script["stage_flow"]["stage_1"]["public_briefing"],
        )

    async def test_opening_messages_use_only_the_static_opening_text(self) -> None:
        dm = await self.new_engine()
        messages = build_phase_messages(dm)
        start = next(item for item in messages if item["type"] == "dm_narration_start")
        chunks = [item for item in messages if item["type"] == "dm_narration_chunk"]
        end = next(item for item in messages if item["type"] == "dm_narration_end")

        self.assertEqual(dm.get_opening_narration(), self.script["opening"]["content"])
        self.assertEqual(start["phase"], "opening")
        self.assertEqual(start["title"], self.script["opening"]["title"])
        self.assertTrue(chunks)
        self.assertTrue(all(item["phase"] == "opening" for item in chunks))
        self.assertEqual("".join(item["content"] for item in chunks), self.script["opening"]["content"])
        self.assertEqual(end["phase"], "opening")
        self.assertTrue(end["can_continue"])
        self.assertEqual(end["continue_label"], dm.get_scene_summary()["continue_label"])
        self.assertFalse(any(item["type"] == "private_script" for item in messages))
        build_phase_messages(dm)
        self.assertEqual(
            sum(self.script["opening"]["content"] in item["content"] for item in dm.state.public_history), 1
        )
        public_history = "\n".join(item["content"] for item in dm.state.public_history)
        self.assertNotIn(self.script["stage_flow"]["stage_1"]["public_briefing"], public_history)
        self.assertNotIn(self.script["story_background"], public_history)

    async def test_timers_and_autonomy_start_only_when_investigation_opens(self) -> None:
        dm = await self.new_engine()
        for phase in (ScenePhase.OPENING, ScenePhase.PRIVATE_REVEAL, ScenePhase.BRIEFING):
            with self.subTest(phase=phase.value):
                self.assertEqual(dm.state.scene_phase, phase)
                self.assertIsNone(dm.state.investigation_deadline_at)
                self.assertIsNone(dm.state.autonomy_next_at)
                self.assertIsNone(dm.investigation_seconds_remaining())
                self.assertFalse(dm.get_autonomy_status()["enabled"])
                self.assertIsNone(dm.preview_autonomous_turn())
                with patch("domain.scenes.time.time", return_value=1234.0):
                    await dm.advance_scene_phase()

        investigation = self.script["stage_flow"]["stage_1"]["investigation"]
        self.assertEqual(dm.state.scene_phase, ScenePhase.INVESTIGATION)
        self.assertEqual(dm.state.investigation_deadline_at, 1234.0 + investigation["duration_seconds"])
        self.assertEqual(
            dm.state.autonomy_next_at,
            1234.0 + investigation["autonomy"]["initial_delay_seconds"],
        )
        self.assertTrue(dm.get_autonomy_status()["enabled"])

    async def test_initial_phases_round_trip_without_replaying_or_skipping(self) -> None:
        phases = (
            ScenePhase.OPENING,
            ScenePhase.PRIVATE_REVEAL,
            ScenePhase.BRIEFING,
            ScenePhase.INVESTIGATION,
        )
        for transitions, expected_phase in enumerate(phases[:-1]):
            with self.subTest(phase=expected_phase.value):
                dm = await self.new_engine()
                for _ in range(transitions):
                    await dm.advance_scene_phase()
                snapshot = json.loads(json.dumps(dm.export_runtime_snapshot()))
                restored = await self.new_engine()
                restored.restore_runtime_snapshot(snapshot)

                self.assertEqual(snapshot["state"]["scene_phase"], expected_phase.value)
                self.assertEqual(restored.state.scene_phase, expected_phase)
                self.assertEqual(restored.get_scene_summary(), dm.get_scene_summary())
                self.assertIsNone(restored.state.investigation_deadline_at)
                self.assertIsNone(restored.state.autonomy_next_at)
                await restored.advance_scene_phase()
                self.assertEqual(restored.state.scene_phase, phases[transitions + 1])

        dm = await self.new_engine()
        for _ in range(3):
            await dm.advance_scene_phase()
        deadline = dm.state.investigation_deadline_at
        autonomy_next_at = dm.state.autonomy_next_at
        snapshot = json.loads(json.dumps(dm.export_runtime_snapshot()))
        restored = await self.new_engine()
        restored.restore_runtime_snapshot(snapshot)
        self.assertEqual(restored.state.scene_phase, ScenePhase.INVESTIGATION)
        self.assertIsNotNone(deadline)
        self.assertIsNotNone(autonomy_next_at)
        self.assertEqual(restored.state.investigation_deadline_at, deadline)
        self.assertEqual(restored.state.autonomy_next_at, autonomy_next_at)

    async def test_scripts_without_opening_keep_the_original_first_stage_flow(self) -> None:
        dm = await self.new_engine(self.legacy_script)
        self.assertFalse(dm.has_opening())
        self.assertEqual(
            dm.get_briefing_narration(),
            "\n\n".join(
                (
                    self.legacy_script["story_background"].strip(),
                    self.legacy_script["stage_flow"]["stage_1"]["public_briefing"].strip(),
                )
            ),
        )
        for phase in (ScenePhase.BRIEFING, ScenePhase.PRIVATE_REVEAL):
            self.assertEqual(dm.state.scene_phase, phase)
            self.assertFalse(dm.get_scene_summary()["has_opening"])
            self.assertFalse(dm.get_scene_summary()["before_first_stage"])
            await dm.advance_scene_phase()
        self.assertEqual(dm.state.scene_phase, ScenePhase.INVESTIGATION)

    async def test_legacy_announcement_backfill_respects_the_first_stage_opening_boundary(self) -> None:
        first_stage = self.script["stage_flow"]["stage_1"]
        for transitions, phase in enumerate((ScenePhase.OPENING, ScenePhase.PRIVATE_REVEAL, ScenePhase.BRIEFING)):
            with self.subTest(phase=phase.value):
                dm = await self.new_engine()
                build_phase_messages(dm)
                for _ in range(transitions):
                    await dm.advance_scene_phase()
                snapshot = json.loads(json.dumps(dm.export_runtime_snapshot()))
                for payload in snapshot["agents"].values():
                    payload.pop("public_announcements")
                restored = await self.new_engine()
                restored.restore_runtime_snapshot(snapshot)

                self.assertEqual(restored.state.scene_phase, phase)
                expected_keys = {"dm-opening:1"}
                if phase == ScenePhase.BRIEFING:
                    expected_keys.update({"dm-public-briefing:1", "dm-public-tasks:1"})
                public_history = restored.state.public_history
                self.assertEqual({item["source_key"] for item in public_history}, expected_keys)
                self.assertEqual(sum(item["source_key"] == "dm-opening:1" for item in public_history), 1)
                public_memories = ["\n".join(item["content"] for item in public_history)]
                for payload in restored.agent_pool.export_runtime_state().values():
                    announcements = payload["public_announcements"]
                    self.assertEqual(set(announcements), expected_keys)
                    public_memories.append("\n".join(announcements.values()))
                for content in public_memories:
                    self.assertIn(self.script["opening"]["content"], content)
                    self.assertNotIn(self.script["story_background"], content)
                    for text in (first_stage["public_briefing"], *first_stage["public_tasks"]):
                        if phase == ScenePhase.BRIEFING:
                            self.assertIn(text, content)
                        else:
                            self.assertNotIn(text, content)

    async def test_later_stages_keep_briefing_private_script_investigation_order(self) -> None:
        script = deepcopy(self.script)
        # This test exercises stage transitions independently of the voting mechanic.
        script["stage_flow"]["stage_1"]["resolution"].pop("vote", None)
        dm = await self.new_engine(script)
        for _ in range(3):
            await dm.advance_scene_phase()
        dm.end_investigation("test")
        transition = await dm.advance_scene_phase()

        self.assertTrue(transition["stage_advanced"])
        self.assertEqual(dm.state.current_stage_num, 2)
        self.assertEqual(dm.get_briefing_narration(), script["stage_flow"]["stage_2"]["public_briefing"])
        for phase in (ScenePhase.BRIEFING, ScenePhase.PRIVATE_REVEAL):
            summary = dm.get_scene_summary()
            self.assertEqual(dm.state.scene_phase, phase)
            self.assertTrue(summary["has_opening"])
            self.assertFalse(summary["before_first_stage"])
            self.assertEqual(summary["stage_title"], script["stage_flow"]["stage_2"]["title"])
            await dm.advance_scene_phase()
        self.assertEqual(dm.state.scene_phase, ScenePhase.INVESTIGATION)
        self.assertIsNotNone(dm.state.investigation_deadline_at)


class OpeningNotebookAPITest(TestCase):
    def test_notebook_response_reveals_opening_role_script_then_first_stage_briefing(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"AI_MURDER_MYSTERY_DATA_DIR": directory, "LLM_PROVIDER": "echo"}
        ):
            from fastapi.testclient import TestClient
            from main import create_app

            paid_request = AsyncMock(side_effect=AssertionError("Paid model requests are forbidden in this test"))
            with patch("llm.openai_compatible.OpenAICompatibleLLM._request", new=paid_request):
                with TestClient(create_app(Path(directory) / "test.db", allow_legacy_token_response=True)) as client:
                    auth = client.post(
                        "/api/auth/register", json={"username": "opening_notebook", "password": "secret12"}
                    ).json()
                    headers = {"Authorization": f"Bearer {auth['token']}"}
                    script = build_engine().script_loader.load("fog_harbor_clocktower")
                    creation = client.post("/api/games", headers=headers, json={
                        "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei", "script": script,
                    })
                    self.assertEqual(creation.status_code, 200, creation.text)
                    game_id = creation.json()["id"]
                    service = client.app.state.game_service
                    dm = service.sessions[game_id]

                    for phase, expected_sources in (
                        (ScenePhase.OPENING, {"opening"}),
                        (ScenePhase.PRIVATE_REVEAL, {"opening", "role_script", "personal_task"}),
                        (ScenePhase.BRIEFING, {"opening", "role_script", "personal_task", "public_briefing", "public_tasks"}),
                    ):
                        with self.subTest(phase=phase.value):
                            self.assertEqual(dm.state.scene_phase, phase)
                            build_phase_messages(dm)
                            service.persist_engine_events(game_id, dm)
                            response = client.get(f"/api/games/{game_id}/notebook", headers=headers)
                            self.assertEqual(response.status_code, 200, response.text)
                            automatic = response.json()["automatic"]
                            sources = {entry["source_type"] for entry in automatic}
                            if phase == ScenePhase.BRIEFING:
                                self.assertTrue(expected_sources.issubset(sources))
                                self.assertTrue(any(entry["content"] == script["stage_flow"]["stage_1"]["public_briefing"] for entry in automatic))
                            else:
                                self.assertEqual(sources, expected_sources)
                                self.assertNotIn(script["stage_flow"]["stage_1"]["public_briefing"], response.text)
                                self.assertNotIn("public_tasks", sources)
                            self.assertNotIn("story_background", sources)
                            self.assertEqual(sum(entry["source_type"] == "opening" for entry in automatic), 1)
                            if phase != ScenePhase.BRIEFING:
                                asyncio.run(dm.advance_scene_phase())
            paid_request.assert_not_awaited()
