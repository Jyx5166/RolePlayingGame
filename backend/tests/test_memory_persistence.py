from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.tests.test_engine_flow import build_engine, actual_input
from backend.tests.script_fixtures import advance_to_investigation
from game_service import GameService
from llm.base import BaseLLM
from llm.budget import ContextBudget
from storage import AppStore


class WaitingLLM(BaseLLM):
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def chat(self, messages):
        self.started.set()
        await asyncio.Event().wait()


class FailedLLM(BaseLLM):
    api_key = "TEST_SECRET_KEY"

    async def chat(self, messages):
        raise RuntimeError(f"Provider failure {self.api_key}")


class MemoryPersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "app.db"
        self.store = AppStore(self.path)
        self.user = self.store.register("memory_tests", "secret123")["user"]
        self.service = GameService(self.store, build_engine)
        script = build_engine().script_loader.load("fog_harbor_clocktower")
        self.game = await self.service.create_game(self.user["id"], script, "mystery", "deduction", "shen_zhiwei")
        _, self.dm = await self.service.get_engine(self.user["id"], self.game["id"])
        await advance_to_investigation(self.dm)
        self.service.persist_engine_events(self.game["id"], self.dm)

    async def asyncTearDown(self):
        self.directory.cleanup()

    def context(self):
        return self.dm._build_agent_context(role_id="gu_linchuan", channel="public", purpose="persistence_test",
                                            instruction="核对已知信息", instruction_source="test")

    def attempts(self):
        return self.store.list_agent_attempts(self.user["id"], self.game["id"])

    async def test_started_and_canceled_attempt_survive_runtime_rollback(self):
        snapshot = self.dm.export_runtime_snapshot()
        waiting = WaitingLLM()
        self.dm.agent_pool.get("gu_linchuan")._llm = waiting
        task = asyncio.create_task(self.dm._call_agent(self.context()))
        await waiting.started.wait()
        self.assertEqual(self.attempts()[0]["status"], "running")
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.dm.restore_runtime_snapshot(snapshot)
        self.assertEqual(self.attempts()[0]["status"], "canceled")
        self.assertFalse(self.store.list_agent_context_audits(self.user["id"], self.game["id"]))

    async def test_failed_attempt_survives_database_rollback_and_redacts_key(self):
        snapshot = self.dm.export_runtime_snapshot()
        self.dm.agent_pool.get("gu_linchuan")._llm = FailedLLM()
        _, failed = await self.dm._call_agent(self.context())
        self.assertTrue(failed)
        with patch.object(self.store, "save_runtime_snapshot", side_effect=RuntimeError("disk fault")):
            with self.assertRaises(RuntimeError):
                self.service.persist_engine_events(self.game["id"], self.dm)
        self.dm.restore_runtime_snapshot(snapshot)
        self.assertEqual(self.attempts()[0]["status"], "failed")
        self.assertNotIn(FailedLLM.api_key, json.dumps(self.attempts()))
        self.assertIn("[REDACTED]", self.attempts()[0]["error"])
        self.assertFalse(self.store.list_agent_context_audits(self.user["id"], self.game["id"]))

    async def test_completed_audit_is_actual_input_and_merged_once(self):
        _, failed = await self.dm._call_agent(self.context())
        self.assertFalse(failed)
        payload = self.attempts()[0]["context"]
        self.assertEqual(payload["prompt_version"], "role-context-v3")
        self.assertEqual(payload["provider"], "echo")
        self.assertIn("ROLE_MEMORY_DATA", json.dumps(payload["messages"]))
        self.assertEqual(payload["messages"][0]["content"], self.dm.agent_pool.get("gu_linchuan").last_prepared.messages()[1]["content"])
        self.assertIsNone(payload["input_tokens"])
        self.assertGreaterEqual(payload["latency_ms"], 0)
        self.service.persist_engine_events(self.game["id"], self.dm)
        self.store.update_game(self.game["id"], 3, "completed", "replay")
        role = next(role for role in self.service.get_role_records(self.user["id"], self.game["id"])["roles"] if role["role_id"] == "gu_linchuan")
        self.assertEqual(len(role["agent_context_audits"]), 1)
        self.assertTrue(role["agent_context_audits"][0]["gameplay_committed"])

    async def test_missing_audit_storage_prevents_provider_call(self):
        waiting = WaitingLLM()
        self.dm.agent_pool.get("gu_linchuan")._llm = waiting
        with patch.object(self.store, "record_agent_attempt", side_effect=sqlite3.OperationalError("disk full")):
            with self.assertRaises(sqlite3.OperationalError):
                await self.dm._call_agent(self.context())
        self.assertFalse(waiting.started.is_set())

    async def test_terminal_audit_write_failure_does_not_fake_a_completed_record(self):
        original = self.store.record_agent_attempt
        def fail_terminal(game_id, attempt):
            if attempt["status"] != "running":
                raise sqlite3.OperationalError("terminal disk fault")
            original(game_id, attempt)
        with patch.object(self.store, "record_agent_attempt", side_effect=fail_terminal):
            with self.assertRaises(sqlite3.OperationalError):
                await self.dm._call_agent(self.context())
        self.assertEqual(self.attempts()[0]["status"], "running")
        self.assertFalse(self.store.list_agent_context_audits(self.user["id"], self.game["id"]))

    async def test_attempts_cannot_write_inside_game_transaction(self):
        with self.store.transaction():
            with self.assertRaisesRegex(RuntimeError, "写事务"):
                self.store.record_agent_attempt(self.game["id"], {})

    async def test_failed_preparation_is_audited_without_claiming_provider_invocation(self):
        agent = self.dm.agent_pool.get("gu_linchuan")
        waiting = WaitingLLM()
        agent._llm = waiting
        agent.budget = ContextBudget(8192, 4000, 2048, 512)
        agent.inject_info([{"unlock_stage": 1, "visibility": "self_only", "owner_role": "gu_linchuan",
                            "content": "x" * 10000}], 1)
        _, failed = await self.dm._call_agent(self.context())
        self.assertTrue(failed)
        attempt = self.attempts()[0]
        self.assertEqual(attempt["status"], "failed")
        self.assertEqual(attempt["context"]["prompt_version"], "role-context-v3")
        self.assertFalse(attempt["context"]["input_prepared"])
        self.assertFalse(attempt["context"]["provider_invoked"])
        self.assertFalse(waiting.started.is_set())

    async def test_manual_versions_keep_stage_phase_and_postgame_revision(self):
        for stage, status, phase, content in [(1, "playing", "investigation", "v1"),
                                              (2, "playing", "dm_hosting", "v2"),
                                              (3, "completed", "replay", "v3")]:
            self.store.update_game(self.game["id"], stage, status, phase)
            self.service.save_player_manual_notes(self.user["id"], self.game["id"], content)
        self.service.save_player_manual_notes(self.user["id"], self.game["id"], "v3")
        revisions = self.store.list_manual_note_revisions(self.user["id"], self.game["id"])
        self.assertEqual([row["stage"] for row in revisions], [1, 2, 3])
        self.assertEqual([row["phase"] for row in revisions], ["investigation", "dm_hosting", "replay"])
        self.assertEqual([row["content"] for row in revisions], ["v1", "v2", "v3"])
        role = self.service.get_role_records(self.user["id"], self.game["id"])["roles"][0]
        manual = [entry for entry in role["reasoning_notebook"] if entry["source_type"] == "manual"]
        self.assertEqual([entry["stage"] for entry in manual], [1, 2, 3])

    async def test_manual_is_owner_role_only_and_delete_cascades_observations(self):
        with self.assertRaises(ValueError):
            self.store.save_manual_notes(self.user["id"], self.game["id"], "gu_linchuan", "illegal")
        await self.dm._call_agent(self.context())
        self.service.save_player_manual_notes(self.user["id"], self.game["id"], "v1")
        other = self.store.register("other_user", "secret123")["user"]
        with self.assertRaises(KeyError):
            self.store.list_agent_attempts(other["id"], self.game["id"])
        self.service.delete_game(self.user["id"], self.game["id"])
        with self.store._connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM agent_call_attempts").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM role_manual_note_revisions").fetchone()[0], 0)

    async def test_legacy_trimmed_snapshot_recovers_only_authorized_history(self):
        snapshot = self.dm.export_runtime_snapshot()
        for agent in snapshot["agents"].values():
            agent.pop("memory_version")
            agent["private_memory"] = []
        snapshot["mechanics"]["whisper"]["history"] = {
            "gu_linchuan": [{"sender_role_id": "shen_zhiwei", "message_role": "user", "content": "EARLY_PRIVATE_ARCHIVE"}],
            "zhou_jiming": [{"sender_role_id": "shen_zhiwei", "message_role": "user", "content": "THIRD_PARTY_PRIVATE"}],
        }
        self.dm.restore_runtime_snapshot(snapshot)
        gu_input = actual_input(self.dm, "gu_linchuan")
        self.assertIn("EARLY_PRIVATE_ARCHIVE", gu_input)
        self.assertNotIn("THIRD_PARTY_PRIVATE", gu_input)
        self.assertNotIn("EARLY_PRIVATE_ARCHIVE", actual_input(self.dm, "zhou_jiming"))
        self.assertIn("legacy_stage_unknown", gu_input)

    async def test_legacy_npc_private_archive_recovers_only_participants_and_unlocked_stages(self):
        snapshot = self.dm.export_runtime_snapshot()
        for agent in snapshot["agents"].values():
            agent.pop("memory_version")
            agent["private_memory"] = []
        for stage, actor, target, content in [(1, "gu_linchuan", "zhou_jiming", "EARLY_NPC_PRIVATE"),
                                               (1, "shen_zhiwei", "xu_yanzhou", "FOREIGN_PRIVATE"),
                                               (2, "gu_linchuan", "zhou_jiming", "FUTURE_PRIVATE")]:
            self.store.add_role_activity(self.game["id"], actor, target, "autonomous_private_speech",
                stage, "investigation", "private", "Private exchange", {"content": content})
        self.store.save_runtime_snapshot(self.game["id"], snapshot)
        self.service.sessions.clear()
        _, restored = await self.service.get_engine(self.user["id"], self.game["id"])
        for role in ("gu_linchuan", "zhou_jiming"):
            actual = actual_input(restored, role)
            self.assertIn("EARLY_NPC_PRIVATE", actual)
            self.assertNotIn("FOREIGN_PRIVATE", actual)
            self.assertNotIn("FUTURE_PRIVATE", actual)
        self.assertNotIn("EARLY_NPC_PRIVATE", actual_input(restored, "xu_yanzhou"))


class LegacyNoteMigrationTest(unittest.TestCase):
    def test_migration_is_idempotent_and_does_not_invent_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            store = AppStore(path)
            user = store.register("legacy_user", "secret123")["user"]
            script = build_engine().script_loader.load("fog_harbor_clocktower")
            game = store.create_game(user["id"], script, "mystery", "deduction", "shen_zhiwei")
            with store._connect() as connection:
                connection.execute("DROP TABLE role_manual_notes")
                connection.execute("CREATE TABLE role_manual_notes(game_id INTEGER, role_id TEXT, content TEXT, updated_at TEXT, PRIMARY KEY(game_id,role_id))")
                connection.execute("INSERT INTO role_manual_notes VALUES (?, ?, 'old note', '2026-01-01')", (game["id"], "shen_zhiwei"))
            AppStore(path)
            migrated = AppStore(path)
            revisions = migrated.list_manual_note_revisions(user["id"], game["id"])
            self.assertEqual(len(revisions), 1)
            self.assertIsNone(revisions[0]["stage"])
            self.assertEqual(revisions[0]["phase"], "legacy_unknown")
