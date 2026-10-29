from __future__ import annotations

from backend.tests.account_fixtures import new_test_account

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from llm.echo import EchoLLM
from llm.tools import parse_native_message
from main import create_app
from workflow import GameWorkflow
from workflow_config import WorkflowSettings, load_workflow_settings


ROOT = Path(__file__).resolve().parents[2]


class ScriptedPublicLLM(EchoLLM):
    """Offline native replies, including the live run's unexecuted prose case."""

    def __init__(self, replies):
        super().__init__()
        self.replies = list(replies)
        self.inputs = []

    async def chat_tools(self, messages, definitions, *, transport="native_tools"):
        self.last_provider_invoked = True
        self.inputs.append((messages, definitions))
        reply = self.replies.pop(0) if self.replies else {"content": "本回合结束。", "tool_calls": []}
        return parse_native_message({"role": "assistant", **reply})


def proposal(name, arguments):
    return {"content": None, "tool_calls": [{"id": "offline_" + uuid.uuid4().hex, "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]}


class PublicResponseExecutionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name) / "public-response.db")
        self.store = self.app.state.store
        self.service = self.app.state.game_service
        self.user_id = self.store.register(**new_test_account('public_response_owner'))["user"]["id"]
        self.script = json.loads((ROOT / "backend/resources/scripts/fog_harbor_clocktower.json").read_text(encoding="utf-8"))
        await self.start_game()

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def start_game(self, settings=None):
        self.game = self.store.prepare_game(self.user_id, self.script, "builtin:test", "version",
            workflow_config=(settings or WorkflowSettings()).model_dump())
        await self.service.activate_game(self.user_id, self.game["id"], "shen_zhiwei")
        _, self.dm = await self.service.get_engine(self.user_id, self.game["id"])
        self.workflow = GameWorkflow(self.service, self.user_id, self.dm)
        for _ in range(4):
            if self.dm.state.scene_phase.value == "investigation":
                break
            self.assertIn(self.dm.state.scene_phase.value, {"opening", "private_reveal", "briefing"})
            result = await self.workflow.dispatch(str(uuid.uuid4()), {"type": "advance_phase"})
            self.assertEqual(result[-1]["status"], "completed", result)
        self.assertEqual(self.dm.state.scene_phase.value, "investigation")
        self.role_id = self.dm.state.ai_role_ids[0]
        self.role_name = self.dm.permission.role_name(self.role_id)

    async def respond(self, replies, request_id="public-response", *, named=True):
        client = ScriptedPublicLLM(replies)
        self.dm.agent_pool.get(self.role_id)._llm = client
        content = f"{self.role_name}，请说明你亲自确认的情况。" if named else "请回应当前已知信息。"
        events = await self.workflow.dispatch(request_id, {"type": "player_speech", "content": content})
        return events, client, content

    def records(self, request_id="public-response"):
        with self.store._connect() as connection:
            models = [dict(row) for row in connection.execute(
                "SELECT * FROM model_requests WHERE actor_kind='role' AND turn_id="
                "(SELECT turn_id FROM workflow_commands WHERE game_id=? AND request_id=?) ORDER BY started_at",
                (self.game["id"], request_id))]
            tools = [dict(row) for row in connection.execute(
                "SELECT * FROM tool_calls WHERE request_id=? AND actor_kind='role' ORDER BY started_at", (request_id,))]
        return models, tools

    def assert_caps(self, models, tools):
        settings = self.dm.workflow_settings
        self.assertLessEqual(len(models), settings.max_model_requests_per_role_turn)
        self.assertLessEqual(len(models), settings.max_rounds_per_role_turn)
        self.assertLessEqual(len(tools), settings.max_tool_calls_per_role_turn)

    async def test_required_reply_only_offers_speak_then_restores_exploration(self):
        expected = "我现在无法确认，请先核对各自亲眼见到的情况。"
        events, client, _ = await self.respond([proposal("speak_public", {"content": expected}),
            proposal("read_memory", {"query": "时间线"})])
        self.assertEqual([tool["function"]["name"] for tool in client.inputs[0][1]], ["speak_public"])
        self.assertEqual(client.inputs[0][1][0]["function"]["parameters"]["properties"]["content"]["maxLength"], 500)
        self.assertIn("read_memory", {tool["function"]["name"] for tool in client.inputs[1][1]})
        self.assertEqual([e["content"] for e in events if e["type"] == "ai_speech"], [expected])
        models, tools = self.records()
        self.assertEqual(tools[0]["tool_name"], "speak_public")
        self.assertTrue(json.loads(tools[0]["result_json"])["gameplay_committed"])
        self.assertEqual(tools[1]["tool_name"], "read_memory")
        self.assertEqual(tools[1]["status"], "succeeded")
        self.assert_caps(models, tools)

    async def test_unexecuted_prose_is_preserved_and_corrected_within_same_turn(self):
        unexecuted = "我已经在公开频道回应，现在可以继续研读卷宗。"
        expected = "我只能确认自己已经看到的部分，其他细节还需核对。"
        events, client, _ = await self.respond([
            {"content": unexecuted, "tool_calls": []}, proposal("speak_public", {"content": expected})])
        self.assertEqual([e["content"] for e in events if e["type"] == "ai_speech"], [expected])
        self.assertFalse(any(e.get("code") == "PUBLIC_RESPONSE_MISSING" for e in events))
        second_messages = client.inputs[1][0]
        self.assertTrue(any(m.get("role") == "assistant" and m.get("content") == unexecuted for m in second_messages))
        self.assertTrue(any("[PUBLIC_RESPONSE_REQUIRED]" in (m.get("content") or "") for m in second_messages))
        models, tools = self.records()
        self.assertEqual(json.loads(models[0]["output_json"])["content"], unexecuted)
        self.assertEqual([tool["tool_name"] for tool in tools], ["speak_public"])
        self.assertEqual(len(models), 3)
        self.assert_caps(models, tools)

    async def test_oversized_proposal_is_rejected_without_truncation_then_corrected(self):
        oversized = "长" * 501
        expected = "我暂时无法确认对方的行踪，需要进一步核对。"
        events, client, _ = await self.respond([
            proposal("speak_public", {"content": oversized}), proposal("speak_public", {"content": expected})])
        self.assertEqual([e["content"] for e in events if e["type"] == "ai_speech"], [expected])
        models, tools = self.records()
        self.assertEqual(json.loads(tools[0]["arguments_json"])["content"], oversized)
        self.assertEqual(json.loads(tools[0]["result_json"])["code"], "INVALID_ARGUMENTS")
        self.assertFalse(json.loads(tools[0]["result_json"])["gameplay_committed"])
        second_history = client.inputs[1][0]
        self.assertTrue(any(m.get("role") == "tool" and "INVALID_ARGUMENTS" in m["content"] for m in second_history))
        self.assertEqual(tools[1]["status"], "succeeded")
        self.assert_caps(models, tools)

    async def test_read_memory_cannot_replace_required_public_reply(self):
        expected = "我先回应你的问题：我没有足够依据确认这一点。"
        events, _, _ = await self.respond([
            proposal("read_memory", {"query": "时间线"}), proposal("speak_public", {"content": expected})])
        models, tools = self.records()
        self.assertEqual(json.loads(tools[0]["result_json"])["code"], "PUBLIC_RESPONSE_REQUIRED")
        self.assertFalse(json.loads(tools[0]["result_json"])["gameplay_committed"])
        self.assertEqual([e["content"] for e in events if e["type"] == "ai_speech"], [expected])
        self.assert_caps(models, tools)

    async def test_plain_text_exhausts_existing_rounds_and_never_becomes_public(self):
        prose = {"content": "我已经回答了，行动结束。", "tool_calls": []}
        events, client, content = await self.respond([prose, prose, prose])
        self.assertFalse(any(e["type"] == "ai_speech" for e in events))
        self.assertTrue(any(e.get("code") == "PUBLIC_RESPONSE_MISSING" for e in events))
        models, tools = self.records()
        self.assertEqual(len(models), self.dm.workflow_settings.max_rounds_per_role_turn)
        self.assertEqual(tools, [])
        before = len(client.inputs)
        replay = await self.workflow.dispatch("public-response", {"type": "player_speech", "content": content})
        self.assertEqual(replay, events)
        self.assertEqual(len(client.inputs), before)
        self.assert_caps(models, tools)

    async def test_model_and_tool_caps_stop_correction(self):
        for limiting in ("model", "tool"):
            with self.subTest(limiting=limiting):
                settings = WorkflowSettings(**({"max_model_requests_per_role_turn": 1} if limiting == "model"
                    else {"max_tool_calls_per_role_turn": 1}))
                await self.start_game(settings)
                first = {"content": "尚未执行的普通正文。", "tool_calls": []} if limiting == "model" else proposal("speak_public", {"content": "长" * 501})
                events, client, _ = await self.respond([first, proposal("speak_public", {"content": "不会执行的第二次提案。"})], request_id="limit-" + limiting)
                models, tools = self.records("limit-" + limiting)
                self.assertEqual(len(client.inputs), 1)
                self.assertFalse(any(e["type"] == "ai_speech" for e in events))
                self.assertTrue(any(e.get("code") == "PUBLIC_RESPONSE_MISSING" for e in events))
                self.assert_caps(models, tools)

    async def test_ordinary_public_prompt_also_requires_selected_role_reply(self):
        expected = "我听到了，会先说明自己亲自确认的部分。"
        clients = {role_id: ScriptedPublicLLM([proposal("speak_public", {"content": expected})])
                   for role_id in self.dm.state.ai_role_ids}
        for role_id, client in clients.items():
            self.dm.agent_pool.get(role_id)._llm = client
        events = await self.workflow.dispatch("public-response", {"type": "player_speech", "content": "请回应当前已知信息。"})
        selected = [(role_id, client) for role_id, client in clients.items() if client.inputs]
        self.assertEqual(len(selected), 1, events)
        role_id, client = selected[0]
        self.assertEqual([tool["function"]["name"] for tool in client.inputs[0][1]], ["speak_public"])
        self.assertEqual([e["content"] for e in events if e["type"] == "ai_speech"], [expected])
        self.assertEqual([e["role_id"] for e in events if e["type"] == "ai_speech"], [role_id])

    async def test_shipped_archive_workflow_can_reply_in_first_proposal(self):
        await self.start_game(load_workflow_settings())
        expected = "我先说明自己能够确认的部分，其他人的情况需要分别核对。"
        events, client, _ = await self.respond([proposal("speak_public", {"content": expected})])
        self.assertEqual([e["content"] for e in events if e["type"] == "ai_speech"], [expected])
        self.assertIn("archive-index", json.dumps(client.inputs[0][0], ensure_ascii=False))
        models, tools = self.records()
        self.assertEqual(tools[0]["tool_name"], "speak_public")
        self.assertEqual(tools[0]["model_request_id"], models[0]["model_request_id"])
        self.assertEqual(tools[0]["status"], "succeeded")
        self.assertEqual(self.dm.workflow_settings.max_rounds_per_role_turn, 3)
        self.assertEqual(self.dm.workflow_settings.max_model_requests_per_role_turn, 4)
        self.assertEqual(self.dm.workflow_settings.max_tool_calls_per_role_turn, 3)
        self.assert_caps(models, tools)
