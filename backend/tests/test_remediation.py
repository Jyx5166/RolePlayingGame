from __future__ import annotations

import sys
import os
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ["LLM_PROVIDER"] = "echo"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "app"))

from agent.context import AgentContextBroker
from backend.tests.test_engine_flow import build_engine, FailingFactory
from fastapi.testclient import TestClient
from main import create_app
from backend.tests.script_fixtures import single_stage_script, advance_to_investigation
from loader.script_loader import ScriptValidationError


def secret_block(marker: str, *, stage: int = 1, owner: str = "gu_linchuan", scope: str = "self_only") -> dict:
    return {
        "block_id": marker,
        "type": "private",
        "content": marker,
        "visibility": scope,
        "unlock_stage": stage,
        "owner_role": owner,
    }


class KnowledgeRemediationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.dm = build_engine()
        self.script = deepcopy(self.dm.script_loader.load("fog_harbor_clocktower"))

    def prompt(self) -> str:
        state = self.dm.state
        context = AgentContextBroker(state.ai_role_ids).build(
            role_id="gu_linchuan", stage=state.current_stage_num,
            channel="public", purpose="boundary_test", instruction="Respond in character.",
        )
        return str(self.dm.agent_pool.get("gu_linchuan")._build_messages(context))

    async def test_future_block_is_absent_until_actual_unlock_and_survives_restore(self) -> None:
        role = next(role for role in self.script["roles"] if role["role_id"] == "gu_linchuan")
        role["stage_knowledge"]["stage_1"]["blocks"].append(secret_block("FUTURE_SECRET", stage=3))
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        self.assertNotIn("FUTURE_SECRET", self.prompt())
        await self.dm.advance_stage()
        self.assertNotIn("FUTURE_SECRET", self.prompt())
        snapshot = self.dm.export_runtime_snapshot()
        restored = build_engine()
        await restored.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        restored.restore_runtime_snapshot(snapshot)
        self.dm = restored
        self.assertNotIn("FUTURE_SECRET", self.prompt())
        await self.dm.advance_stage()
        self.assertIn("FUTURE_SECRET", self.prompt())

    async def test_dm_and_other_role_blocks_never_enter_role_prompt(self) -> None:
        role = next(role for role in self.script["roles"] if role["role_id"] == "gu_linchuan")
        role["stage_knowledge"]["stage_1"]["blocks"].extend([
            secret_block("DM_SECRET", owner="dm", scope="dm_only"),
            secret_block("OTHER_ROLE_SECRET", owner="xu_yanzhou"),
        ])
        with self.assertRaises(ScriptValidationError):
            await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        # Historical payloads can predate import validation; the runtime must still filter.
        with patch.object(self.dm.script_loader, "validate", return_value=None):
            await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        self.assertNotIn("DM_SECRET", self.prompt())
        self.assertNotIn("OTHER_ROLE_SECRET", self.prompt())

    async def test_direct_injection_and_legacy_snapshot_cannot_bypass_authorization(self) -> None:
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        agent = self.dm.agent_pool.get("gu_linchuan")
        invalid = [secret_block("FUTURE_SECRET", stage=3), secret_block("DM_SECRET", owner="dm", scope="dm_only")]
        agent.inject_info(invalid, 1)
        self.assertNotIn("FUTURE_SECRET", self.prompt())
        self.assertNotIn("DM_SECRET", self.prompt())
        payload = agent.export_runtime_state()
        payload["stage_infos"] = {1: invalid}
        payload["background_summary"] = "FUTURE_SECRET DM_SECRET"
        agent.restore_runtime_state(payload)
        self.assertNotIn("FUTURE_SECRET", self.prompt())
        self.assertNotIn("DM_SECRET", self.prompt())


    async def test_pending_final_resolution_does_not_publish_ending_templates(self) -> None:
        for branch in ("correct_verdict", "incorrect_verdict"):
            self.script["stage_flow"]["stage_3"]["resolution"]["final_decision"][branch] = "SECRET_ENDING_" + branch
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        await self.dm.advance_stage()
        await self.dm.advance_stage()
        await advance_to_investigation(self.dm)
        self.dm.end_investigation("timeout")
        from ws.handlers import build_phase_messages
        payload = str(build_phase_messages(self.dm))
        self.assertNotIn("SECRET_ENDING", payload)
        self.assertNotIn("correct_verdict", payload)
        self.assertNotIn("incorrect_verdict", str(self.dm.get_scene_summary()))

    async def test_dm_background_and_hosting_are_available_to_actual_agent_context(self) -> None:
        import json
        def input_memories(context):
            return [record["content"]
                    for message in self.dm.agent_pool.get("gu_linchuan")._build_messages(context)
                    if message["content"].startswith("[ROLE_MEMORY_DATA]\n")
                    for record in json.loads(message["content"].split("\n", 1)[1])]
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        from ws.handlers import build_phase_messages
        build_phase_messages(self.dm)
        build_phase_messages(self.dm)
        context = self.dm._build_agent_context(
            role_id="gu_linchuan", channel="public", purpose="dm_public_test", instruction="Respond.", instruction_source="dm_test",
        )
        actual = input_memories(context)
        self.assertIn(self.script["opening"]["content"], actual)
        self.assertNotIn(self.script["stage_flow"]["stage_1"]["public_briefing"], actual)
        self.assertEqual(sum(self.script["opening"]["content"] in item["content"] for item in self.dm.state.public_history), 1)
        self.dm.restore_runtime_snapshot(self.dm.export_runtime_snapshot())
        build_phase_messages(self.dm)
        self.assertEqual(sum(self.script["opening"]["content"] in item["content"] for item in self.dm.state.public_history), 1)
        self.dm.state.public_history.extend({"role": "user", "content": "Recent public claim"} for _ in range(20))
        await self.dm.advance_scene_phase()
        await self.dm.advance_scene_phase()
        build_phase_messages(self.dm)
        await self.dm.advance_scene_phase()
        self.dm.end_investigation("timeout")
        build_phase_messages(self.dm)
        context = self.dm._build_agent_context(
            role_id="gu_linchuan", channel="public", purpose="dm_host_test", instruction="Respond.", instruction_source="dm_test",
        )
        actual = input_memories(context)
        self.assertIn(self.dm.get_hosting_narration(), actual)
        self.assertIn(self.script["opening"]["content"], actual)

    async def test_agents_cannot_use_public_channel_in_search_only_phase(self) -> None:
        import time
        self.script["stage_flow"]["stage_1"]["investigation"]["enabled_actions"] = ["search"]
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        await advance_to_investigation(self.dm)
        with self.assertRaises(ValueError):
            await self.dm.handle_human_speech("Disallowed")
        initial = len(self.dm.state.public_history)
        self.dm.state.autonomy_next_at = time.time() - 1
        messages = await self.dm.run_autonomous_turn()
        self.assertFalse(any(msg.get("type") == "ai_proactive_speech" for msg in messages))
        self.assertEqual(len(self.dm.state.public_history), initial)
        with self.assertRaises(ValueError):
            await self.dm._run_autonomous_public_exchange(
                {"actor_role_id": "gu_linchuan", "target_role_id": "shen_zhiwei"}, "Disallowed", False,
            )

    async def test_expired_stage_blocks_human_and_agent_search_without_clue(self) -> None:
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        await advance_to_investigation(self.dm)
        self.dm.state.investigation_deadline_at = time.time() - 1
        with self.assertRaisesRegex(ValueError, "结束"):
            await self.dm.handle_mechanic_action({"type": "search", "target_id": "archive_desk"})
        with self.assertRaisesRegex(ValueError, "结束"):
            await self.dm._run_autonomous_search({"actor_role_id": "gu_linchuan", "search_target_id": "archive_desk"})
        self.assertFalse(self.dm.get_human_clues())
        self.assertFalse(self.dm.get_role_clues("gu_linchuan"))

    async def test_script_action_counts_cannot_end_phase_early(self) -> None:
        self.script["stage_flow"]["stage_1"]["investigation"]["end_conditions"]["auto_end"] = True
        from loader.script_loader import ScriptValidationError
        with self.assertRaisesRegex(ScriptValidationError, "auto_end"):
            self.dm.script_loader.validate(self.script)

    async def test_failed_agent_vote_leaves_decision_pending_without_synthetic_ballots(self) -> None:
        self.dm.llm_factory = FailingFactory()
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        await advance_to_investigation(self.dm)
        self.dm.end_investigation("timeout")
        with self.assertRaisesRegex(ValueError, "投票"):
            await self.dm.cast_stage_vote("gu_linchuan")
        resolution = self.dm.get_stage_resolution()
        self.assertTrue(resolution["vote"]["pending"])
        self.assertEqual(resolution["vote"]["ballots"], [])
        self.assertFalse(resolution["resolved"])
        self.assertEqual(self.dm.state.penalties, [])

    async def test_negated_candidate_id_is_not_a_valid_ballot(self) -> None:
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        await advance_to_investigation(self.dm)
        self.dm.end_investigation("timeout")
        from unittest.mock import AsyncMock
        with patch.object(self.dm, "_call_agent", new=AsyncMock(return_value=("Do not select gu_linchuan; choose no one.", False))):
            with self.assertRaisesRegex(ValueError, "投票"):
                await self.dm.cast_stage_vote("gu_linchuan")
        self.assertTrue(self.dm.stage_resolution_pending())

    async def test_tie_rule_is_published_and_does_not_favor_human_ballot(self) -> None:
        self.script = single_stage_script(self.script)
        self.script["stage_flow"]["stage_1"]["resolution"]["final_decision"]["eligible_role_ids"] = ["shen_zhiwei", "gu_linchuan"]
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        await advance_to_investigation(self.dm)
        self.dm.end_investigation("timeout")
        self.assertEqual(self.dm.get_stage_resolution()["vote"]["tie_breaker"], "role_id_order")
        from unittest.mock import AsyncMock
        with patch.object(self.dm, "_call_agent", new=AsyncMock(side_effect=[
            ("shen_zhiwei", False), ("gu_linchuan", False), ("gu_linchuan", False),
        ])):
            result = await self.dm.cast_stage_vote("shen_zhiwei")
        self.assertEqual([item["votes"] for item in result["vote"]["tally"]], [2, 2])
        self.assertEqual(result["vote"]["selected_role_id"], "gu_linchuan")
        self.assertIn("平票", result["vote"]["outcome_text"])

    async def test_invalid_ending_template_is_rejected_at_import(self) -> None:
        from loader.script_loader import ScriptValidationError
        for template in ("结果 {unknown}", "结果 {selected_role_name.secret}", "结果 {", "结果 {selected_role_name:invalid}"):
            with self.subTest(template=template):
                self.script["stage_flow"]["stage_3"]["resolution"]["final_decision"]["correct_verdict"] = template
                with self.assertRaises(ScriptValidationError):
                    self.dm.script_loader.validate(self.script)

    async def test_failed_ending_does_not_commit_vote_or_allow_replay(self) -> None:
        self.script = single_stage_script(self.script)
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        await advance_to_investigation(self.dm)
        self.dm.end_investigation("timeout")
        final = self.dm.script["stage_flow"]["stage_1"]["resolution"]["final_decision"]
        final["correct_verdict"] = final["incorrect_verdict"] = "结果 {unknown}"
        with self.assertRaises((KeyError, ValueError)):
            await self.dm.cast_stage_vote("gu_linchuan")
        self.assertTrue(self.dm.stage_resolution_pending())
        self.assertEqual(self.dm.get_stage_resolution()["vote"]["ballots"], [])
        with self.assertRaises(ValueError):
            await self.dm.advance_scene_phase()

    async def test_task_checks_settle_and_narrative_tasks_require_review(self) -> None:
        self.script["stage_flow"]["stage_1"]["personal_task_checks"] = {
            "shen_zhiwei": [{"label": "搜证一次", "type": "activity_count", "event_types": ["search"], "minimum": 1}],
            "gu_linchuan": [{"label": "搜证一次", "type": "activity_count", "event_types": ["search"], "minimum": 1}],
        }
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        await advance_to_investigation(self.dm)
        await self.dm.handle_mechanic_action({"type": "search", "target_id": "unknown"})
        self.assertEqual(self.dm._role_task_results("shen_zhiwei", 1)[1]["status"], "failed")
        await self.dm.handle_mechanic_action({"type": "search", "target_id": "archive_desk"})
        self.dm.end_investigation("timeout")
        own = self.dm.get_stage_resolution()["role_results"][0]
        self.assertEqual([task["status"] for task in own["task_results"]], ["manual_review", "completed"])
        internal = next(result for result in self.dm.state.stage_resolutions[1]["role_results"] if result["role_id"] == "gu_linchuan")
        self.assertEqual(internal["task_results"][1]["status"], "failed")
        self.assertNotIn("task_results", next(result for result in self.dm.get_stage_resolution()["role_results"] if result["role_id"] == "gu_linchuan"))
        restored = build_engine()
        await restored.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        restored.restore_runtime_snapshot(self.dm.export_runtime_snapshot())
        self.assertEqual(restored.get_stage_resolution()["role_results"][0]["task_results"], own["task_results"])

    async def test_penalty_disclosure_check_requires_true_new_public_clue(self) -> None:
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        await self.dm.advance_stage()
        await self.dm.advance_stage()
        await advance_to_investigation(self.dm)
        self.dm.state.penalties.append({
            "source_stage": 2, "target_stage": 3, "target_role_id": "shen_zhiwei", "extra_task": "公开新的真实线索", "label": "强制披露",
            "completion_checks": [{"type": "clue_disclosure", "label": "新的公开线索", "channel": "public", "disclosure_mode": "truthful", "new_public": True}],
        })
        self.assertEqual(self.dm._role_task_results("shen_zhiwei", 3)[-1]["status"], "failed")
        await self.dm.handle_mechanic_action({"type": "search", "target_id": "clocktower_log"})
        clue_id = self.dm.get_human_clues()[0]["clue_id"]
        self.dm._disclose_clue(role_id="shen_zhiwei", clue_id=clue_id, mode="distorted", scope="public", target_role_id=None, shared_content="虚构线索")
        self.assertEqual(self.dm._role_task_results("shen_zhiwei", 3)[-1]["status"], "failed")
        self.dm._disclose_clue(role_id="shen_zhiwei", clue_id=clue_id, mode="truthful", scope="private", target_role_id="gu_linchuan", shared_content="")
        self.assertEqual(self.dm._role_task_results("shen_zhiwei", 3)[-1]["status"], "failed")
        self.dm._disclose_clue(role_id="shen_zhiwei", clue_id=clue_id, mode="truthful", scope="public", target_role_id=None, shared_content="")
        self.assertEqual(self.dm._role_task_results("shen_zhiwei", 3)[-1]["status"], "completed")

    async def test_slow_private_reply_cannot_publish_after_deadline(self) -> None:
        import asyncio
        from unittest.mock import AsyncMock
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        await advance_to_investigation(self.dm)
        await self.dm.handle_whisper_action({"type": "whisper_invite", "target_role_id": "gu_linchuan"})
        async def slow_reply(*args):
            await asyncio.sleep(1)
            return "LATE_REPLY"
        self.dm.state.investigation_deadline_at = time.time() + 0.04
        started = time.monotonic()
        with patch.object(self.dm.agent_pool.get("gu_linchuan")._llm, "chat", new=AsyncMock(side_effect=slow_reply)):
            replies = await self.dm.handle_whisper_speech("及时送达的私聊")
        self.assertLess(time.monotonic() - started, 0.3)
        self.assertFalse(any(reply.get("sender_type") == "agent" for reply in replies))
        self.assertTrue(any(reply.get("sender_type") == "player" for reply in replies))

    async def test_slow_autonomous_private_reply_is_not_recorded(self) -> None:
        import asyncio
        from unittest.mock import AsyncMock
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        await advance_to_investigation(self.dm)
        async def slow_reply(*args):
            await asyncio.sleep(1)
            return "LATE_REPLY"
        self.dm.state.investigation_deadline_at = time.time() + 0.04
        with patch.object(self.dm.agent_pool.get("zhou_jiming")._llm, "chat", new=AsyncMock(side_effect=slow_reply)):
            result = await self.dm._run_autonomous_private_exchange({
                "actor_role_id": "gu_linchuan", "target_role_id": "zhou_jiming", "turn_number": 1,
            }, "PRIVATE_QUESTION", False)
        self.assertIsNone(result)
        self.assertFalse(any(event.get("event_type") == "autonomous_private_response" for event in self.dm.state.persistence_events))

    async def test_legacy_restore_backfills_only_already_published_dm_information(self) -> None:
        self.script.pop("opening", None)
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        await advance_to_investigation(self.dm)
        snapshot = self.dm.export_runtime_snapshot()
        for payload in snapshot["agents"].values():
            payload.pop("public_announcements")
        self.dm.restore_runtime_snapshot(snapshot)
        actual = self.prompt()
        self.assertIn(self.script["story_background"], actual)
        self.assertIn(self.script["stage_flow"]["stage_1"]["public_briefing"], actual)
        self.assertNotIn(self.script["stage_flow"]["stage_1"]["dm_hosting"], actual)
        self.assertNotIn(self.script["stage_flow"]["stage_2"]["public_briefing"], actual)

    async def test_direct_replay_is_blocked_before_final_result(self) -> None:
        await self.dm.init_game_from_script(self.script, "shen_zhiwei", "deduction")
        with self.assertRaises(ValueError):
            await self.dm.run_replay()
        self.assertNotEqual(self.dm.state.phase.value, "replay")


class APIRemediationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.temp.name) / "audit.db"), raise_server_exceptions=False)
        auth = self.client.post("/api/v1/auth/register", json={"username": "remediation", "password": "secret12"})
        self.assertEqual(auth.status_code, 200)
        self.headers = {"X-CSRF-Token": auth.json()["csrf_token"]}

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_builtin_preview_and_creation_never_return_author_script(self) -> None:
        preview = self.client.get("/api/v1/scripts/example")
        self.assertEqual(preview.status_code, 200)
        self.assertNotIn("truth", preview.json())
        self.assertNotIn("roles", preview.json())
        self.assertNotIn("stage_knowledge", preview.text)
        self.assertEqual(preview.json()["role_count"], 4)
        inspected = self.client.post("/api/v1/scripts/inspect", headers=self.headers,
            json={"mode": "deduction", "script_id": preview.json()["script_id"]})
        self.assertEqual(inspected.status_code, 200)
        created = self.client.post("/api/v1/games", headers=self.headers, json={
            "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei",
            "script_id": preview.json()["script_id"],
        })
        self.assertEqual(created.status_code, 200)
        self.assertNotIn("stage_knowledge", created.text)
        self.assertNotIn("culprit_role_id", created.text)

    def test_builtin_reference_cannot_select_arbitrary_path_or_two_sources(self) -> None:
        for source in ({"script_id": "../config"}, {"script_id": "fog_harbor_clocktower", "script": {}}):
            response = self.client.post("/api/v1/scripts/inspect", headers=self.headers,
                json={"mode": "deduction", **source})
            self.assertEqual(response.status_code, 400)

    def test_legacy_event_history_cannot_republish_hidden_ending_templates(self) -> None:
        game_id = self.client.post("/api/v1/games", headers=self.headers, json={
            "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei", "script_id": "fog_harbor_clocktower",
        }).json()["id"]
        store = self.client.app.state.store
        legacy = {"type": "stage_resolution", "resolution": {"vote": {"pending": True,
            "correct_verdict": "LEGACY_SECRET_CORRECT", "incorrect_verdict": "LEGACY_SECRET_WRONG"}}}
        store.add_event(game_id, "stage_resolution", legacy)
        store.record_realtime_events(game_id, "legacy-secret", [legacy])
        for path in (f"/api/v1/games/{game_id}", f"/api/v1/games/{game_id}/events"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("LEGACY_SECRET", response.text)
        self.assertNotIn("LEGACY_SECRET", str(store.realtime_events_for_request(game_id, "legacy-secret")))

    def test_malformed_scripts_are_client_errors_not_server_errors(self) -> None:
        mutations = [
            (("script_meta",), None), (("script_meta", "total_stages"), True),
            (("script_meta", "total_stages"), "three"), (("script_meta", "total_stages"), 0),
            (("script_meta", "supported_skills"), "deduction"), (("roles", 0), None),
            (("roles", 0, "role_id"), []), (("roles", 0, "human_playable"), "yes"),
            (("roles", 0, "stage_knowledge", "stage_1"), []),
            (("roles", 0, "stage_knowledge", "stage_1", "blocks", 0), None),
            (("roles", 0, "stage_knowledge", "stage_1", "blocks", 0, "visibility"), "unknown"),
            (("truth",), []), (("truth", "full_story"), None),
            (("stage_flow", "stage_1", "personal_tasks", "gu_linchuan"), []),
            (("stage_flow", "stage_1", "investigation", "enabled_actions"), [{}]),
            (("stage_flow", "stage_1", "investigation", "duration_seconds"), True),
            (("stage_flow", "stage_1", "resolution", "vote", "eligible_role_ids"), [{}, "gu_linchuan"]),
            (("mechanics_config", "search", "ap_per_stage"), []),
            (("mechanics_config", "search", "ap_per_stage"), ["bad"]),
            (("mechanics_config", "search", "search_targets", 0, "id"), []),
            (("mechanics_config", "whisper", "max_sessions_per_stage"), "bad"),
        ]
        base = build_engine().script_loader.load("fog_harbor_clocktower")
        for path, value in mutations:
            script = deepcopy(base)
            node = script
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
            with self.subTest(path=path):
                response = self.client.post("/api/v1/scripts/inspect", headers=self.headers,
                    json={"mode": "deduction", "script": script})
                self.assertEqual(response.status_code, 400, response.text)

    def test_phase_without_timeout_or_manual_vote_is_rejected(self) -> None:
        script = build_engine().script_loader.load("fog_harbor_clocktower")
        config = script["stage_flow"]["stage_1"]["investigation"]
        config.update(duration_seconds=0, allow_manual_end=False)
        response = self.client.post("/api/v1/scripts/inspect", headers=self.headers,
            json={"mode": "deduction", "script": script})
        self.assertEqual(response.status_code, 400)

    def test_stored_session_digest_is_not_a_login_credential(self) -> None:
        store = self.client.app.state.store
        token = self.client.cookies.get(self.client.app.state.cookie_name)
        self.assertIsNotNone(token)
        original = store.user_for_token(token)
        self.assertIsNotNone(original)
        self.assertIsNone(store.user_for_token(original["session_key"]))
        store.logout(original["session_key"])
        self.assertIsNotNone(store.user_for_token(token))
        self.client.cookies.set(self.client.app.state.cookie_name, original["session_key"])
        self.assertEqual(self.client.get("/api/v1/me").status_code, 401)

    def test_legacy_plain_session_is_migrated_without_digest_login_bypass(self) -> None:
        from storage import AppStore
        store = self.client.app.state.store
        token = self.client.cookies.get(self.client.app.state.cookie_name)
        original = store.user_for_token(token)
        with store._connect() as connection:
            connection.execute("UPDATE sessions SET token = ? WHERE token = ?", (token, original["session_key"]))
        migrated = AppStore(Path(self.temp.name) / "audit.db")
        self.assertIsNotNone(migrated.user_for_token(token))
        self.assertIsNone(migrated.user_for_token(original["session_key"]))

    def test_creation_failure_does_not_leave_game_or_cached_engine(self) -> None:
        service = self.client.app.state.game_service
        for target, method in ((service.dm_factory().__class__, "init_game_from_script"),
                               (self.client.app.state.store, "save_runtime_snapshot")):
            with self.subTest(method=method), patch.object(target, method, side_effect=RuntimeError("Injected creation failure")):
                response = self.client.post("/api/v1/games", headers=self.headers, json={
                    "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei",
                    "script_id": "fog_harbor_clocktower",
                })
                self.assertEqual(response.status_code, 500)
            self.assertEqual(self.client.get("/api/v1/games").json(), [])
            self.assertEqual(service.sessions, {})

    def test_search_write_failures_roll_back_clues_notebook_and_snapshot(self) -> None:
        import asyncio
        store = self.client.app.state.store
        for method in ("add_notebook_entry", "save_runtime_snapshot"):
            with self.subTest(method=method):
                game_id = self.client.post("/api/v1/games", headers=self.headers, json={
                    "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei", "script_id": "fog_harbor_clocktower",
                }).json()["id"]
                dm = self.client.app.state.game_service.sessions[game_id]
                asyncio.run(advance_to_investigation(dm))
                ticket = self.client.post(f"/api/v1/games/{game_id}/ws-ticket", headers=self.headers).json()["ticket"]
                with self.client.websocket_connect(f"/ws/v1/games/{game_id}?ticket={ticket}") as ws:
                    ws.receive_json()
                    original = getattr(store, method)
                    failed = False
                    def fail_once(*args, **kwargs):
                        nonlocal failed
                        if not failed:
                            failed = True
                            raise RuntimeError("Injected intermediate write failure")
                        return original(*args, **kwargs)
                    command = {"protocol_version": "1.0", "kind": "command", "type": "search",
                        "request_id": f"fault-{method}", "game_id": game_id, "payload": {"target_id": "archive_desk"}}
                    with patch.object(store, method, side_effect=fail_once):
                        ws.send_json(command)
                        error = ws.receive_json()
                    self.assertEqual(error["kind"], "error")
                    self.assertFalse(dm.get_human_clues())
                    self.assertFalse(store.list_role_clues(1, game_id))
                    self.assertFalse(any(entry["source_type"] == "search" for entry in store.list_notebook_entries(1, game_id)))
                    self.assertEqual(dm.mechanic_registry.get("search").remaining_ap(1, "shen_zhiwei"), 2)
                    ws.send_json(command)
                    self.assertEqual(ws.receive_json()["event_id"], error["event_id"])
                    ws.send_json({**command, "request_id": f"retry-{method}"})
                    self.assertEqual(ws.receive_json()["type"], "search_result")
                    self.assertEqual(len(dm.get_human_clues()), 1)
                    self.assertEqual(dm.mechanic_registry.get("search").remaining_ap(1, "shen_zhiwei"), 1)

    def test_completed_role_records_include_private_agent_task_results(self) -> None:
        import asyncio
        service = self.client.app.state.game_service
        game_id = self.client.post("/api/v1/games", headers=self.headers, json={
            "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei", "script_id": "fog_harbor_clocktower",
        }).json()["id"]
        self.assertEqual(self.client.get(f"/api/v1/games/{game_id}/role-records").status_code, 409)
        dm = service.sessions[game_id]
        async def complete():
            for stage in range(1, 4):
                await advance_to_investigation(dm)
                dm.end_investigation("timeout")
                result = await dm.cast_stage_vote("gu_linchuan")
                service.record_responses(game_id, dm, [{"type": "stage_resolution", "resolution": result}])
                transition = await dm.advance_scene_phase()
            service.record_responses(game_id, dm, [{"type": "replay", **transition["replay"]}])
        asyncio.run(complete())
        response = self.client.get(f"/api/v1/games/{game_id}/role-records")
        self.assertEqual(response.status_code, 200)
        records = response.json()
        self.assertEqual(len(records["roles"]), 4)
        for role in records["roles"]:
            self.assertEqual(len(role["stage_results"]), 3)
            self.assertEqual(role["stage_results"][0]["result"]["task_results"][0]["status"], "manual_review")

    def test_websocket_rejects_expired_search_and_publishes_phase_end(self) -> None:
        created = self.client.post("/api/v1/games", headers=self.headers, json={
            "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei",
            "script_id": "fog_harbor_clocktower",
        }).json()
        game_id = created["id"]
        dm = self.client.app.state.game_service.sessions[game_id]
        import asyncio
        asyncio.run(advance_to_investigation(dm))
        ticket = self.client.post(f"/api/v1/games/{game_id}/ws-ticket", headers=self.headers).json()["ticket"]
        with self.client.websocket_connect(f"/ws/v1/games/{game_id}?ticket={ticket}") as ws:
            ws.receive_json()
            dm.state.investigation_deadline_at = time.time() - 1
            ws.send_json({"protocol_version": "1.0", "kind": "command", "type": "search",
                "request_id": "expired-search", "game_id": game_id, "payload": {"target_id": "archive_desk"}})
            first = ws.receive_json()
            self.assertNotEqual(first.get("type"), "search_result")
            self.assertEqual(dm.state.scene_phase.value, "dm_hosting")
            self.assertFalse(dm.get_human_clues())

    def test_websocket_resume_drains_more_than_one_page_before_live_event(self) -> None:
        created = self.client.post("/api/v1/games", headers=self.headers, json={
            "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei",
            "script_id": "fog_harbor_clocktower",
        }).json()
        game_id = created["id"]
        store = self.client.app.state.store
        stored = store.record_realtime_events(game_id, "backlog", [
            {"type": "audit_event", "index": index} for index in range(1001)
        ])
        ticket = self.client.post(f"/api/v1/games/{game_id}/ws-ticket", headers=self.headers).json()["ticket"]
        with self.client.websocket_connect(f"/ws/v1/games/{game_id}?ticket={ticket}&after_event_id={stored[0]['event_id']}") as ws:
            ws.send_json({"protocol_version": "1.0", "kind": "command", "type": "ask_hint",
                "request_id": "live-after-backlog", "game_id": game_id, "payload": {}})
            received = []
            for _ in range(8):
                message = ws.receive_json()
                if message["kind"] != "resume":
                    break
                received.extend(item["event_id"] for item in message["payload"]["events"])
            self.assertEqual(received, [item["event_id"] for item in stored[1:]])
            self.assertEqual(message["kind"], "snapshot")
            message = ws.receive_json()
            self.assertGreater(message["event_id"], stored[-1]["event_id"])

    def test_reconnect_restores_current_phase_even_without_new_events(self) -> None:
        import asyncio
        created = self.client.post("/api/v1/games", headers=self.headers, json={
            "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei",
            "script_id": "fog_harbor_clocktower",
        }).json()
        game_id = created["id"]
        dm = self.client.app.state.game_service.sessions[game_id]
        asyncio.run(advance_to_investigation(dm))
        stored = self.client.app.state.store.record_realtime_events(game_id, "seed-cursor", [{"type": "hint", "content": "seed"}])
        ticket = self.client.post(f"/api/v1/games/{game_id}/ws-ticket", headers=self.headers).json()["ticket"]
        with self.client.websocket_connect(f"/ws/v1/games/{game_id}?ticket={ticket}&after_event_id={stored[0]['event_id']}") as ws:
            self.assertEqual(ws.receive_json()["kind"], "resume")
            ws.send_json({"protocol_version": "1.0", "kind": "command", "type": "ask_hint",
                "request_id": "after-reconnect", "game_id": game_id, "payload": {}})
            sync = ws.receive_json()
            self.assertEqual(sync["kind"], "snapshot")
            opened = next(message for message in sync["payload"]["phase_messages"] if message["type"] == "investigation_open")
            self.assertGreater(opened["phase"]["remaining_seconds"], 0)

    def test_slow_command_sends_heartbeat_before_result(self) -> None:
        import asyncio
        import main
        created = self.client.post("/api/v1/games", headers=self.headers, json={
            "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei",
            "script_id": "fog_harbor_clocktower",
        }).json()
        game_id = created["id"]
        original = main.handle_client_message

        async def delayed(*args, **kwargs):
            await asyncio.sleep(0.12)
            return await original(*args, **kwargs)

        ticket = self.client.post(f"/api/v1/games/{game_id}/ws-ticket", headers=self.headers).json()["ticket"]
        with patch("main.handle_client_message", side_effect=delayed), patch("ws.lifecycle.HEARTBEAT_INTERVAL_SECONDS", 0.01):
            with self.client.websocket_connect(f"/ws/v1/games/{game_id}?ticket={ticket}") as ws:
                ws.receive_json()
                ws.send_json({"protocol_version": "1.0", "kind": "command", "type": "ask_hint",
                    "request_id": "slow-command", "game_id": game_id, "payload": {}})
                self.assertEqual(ws.receive_json()["type"], "heartbeat")

    def test_idle_connection_receives_peer_committed_result(self) -> None:
        created = self.client.post("/api/v1/games", headers=self.headers, json={
            "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei",
            "script_id": "fog_harbor_clocktower",
        }).json()
        game_id = created["id"]
        first = self.client.post(f"/api/v1/games/{game_id}/ws-ticket", headers=self.headers).json()["ticket"]
        second = self.client.post(f"/api/v1/games/{game_id}/ws-ticket", headers=self.headers).json()["ticket"]
        with self.client.websocket_connect(f"/ws/v1/games/{game_id}?ticket={first}") as left:
            left.receive_json()
            with self.client.websocket_connect(f"/ws/v1/games/{game_id}?ticket={second}") as right:
                right.receive_json()
                left.send_json({"protocol_version": "1.0", "kind": "command", "type": "ask_hint",
                    "request_id": "peer-result", "game_id": game_id, "payload": {}})
                expected = left.receive_json()
                received = right.receive_json()
                if received["type"] == "heartbeat":
                    received = right.receive_json()
                self.assertEqual(received["event_id"], expected["event_id"])
                self.assertEqual(received["request_id"], "peer-result")

    def test_failed_result_commit_rolls_back_game_and_memory_before_retry(self) -> None:
        created = self.client.post("/api/v1/games", headers=self.headers, json={
            "category": "mystery", "mode": "deduction", "player_role_id": "shen_zhiwei",
            "script_id": "fog_harbor_clocktower",
        }).json()
        game_id = created["id"]
        store = self.client.app.state.store
        dm = self.client.app.state.game_service.sessions[game_id]
        original = store.record_realtime_events
        failed = False

        def fail_once(*args, **kwargs):
            nonlocal failed
            if not failed:
                failed = True
                raise RuntimeError("Injected result write failure")
            return original(*args, **kwargs)

        ticket = self.client.post(f"/api/v1/games/{game_id}/ws-ticket", headers=self.headers).json()["ticket"]
        command = {"protocol_version": "1.0", "kind": "command", "type": "advance_phase",
            "request_id": "atomic-phase-fault", "game_id": game_id, "payload": {}}
        with self.client.websocket_connect(f"/ws/v1/games/{game_id}?ticket={ticket}") as ws:
            ws.receive_json()
            with patch.object(store, "record_realtime_events", side_effect=fail_once):
                ws.send_json(command)
                result = ws.receive_json()
            self.assertEqual(result["kind"], "error")
            self.assertEqual(dm.state.scene_phase.value, "opening")
            persisted = self.client.get(f"/api/v1/games/{game_id}").json()
            self.assertEqual(persisted["current_phase"], "opening")
            self.assertFalse(any(item["type"] == "phase_changed" for item in persisted["events"]))
            ws.send_json(command)
            self.assertEqual(ws.receive_json()["event_id"], result["event_id"])
            self.assertEqual(dm.state.scene_phase.value, "opening")
            ws.send_json({**command, "request_id": "atomic-phase-retry"})
            self.assertEqual(ws.receive_json()["type"], "phase_changed")
            self.assertEqual(dm.state.scene_phase.value, "private_reveal")


if __name__ == "__main__":
    unittest.main()
