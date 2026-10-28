from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from agent.director import DMDirector
from llm.echo import EchoLLM
from llm.tools import parse_native_message
from main import create_app
from runtime.contracts import ExecutionFrame, RuntimeAccessError, execution_frame
from workflow import GameWorkflow
from runtime.models import recorded_model_call
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from tools.gateway import ToolGateway
from workflow_config import WorkflowSettings, load_workflow_settings

ROOT = Path(__file__).resolve().parents[2]


class GameWorkflowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name) / "test.db")
        self.store = self.app.state.store
        self.service = self.app.state.game_service
        self.user_id = self.store.register("workflow_owner", "secret12")["user"]["id"]
        self.script = json.loads((ROOT / "backend/resources/scripts/fog_harbor_clocktower.json").read_text(encoding="utf-8"))
        self.game, self.dm = await self.new_game()
        self.workflow = GameWorkflow(self.service, self.user_id, self.dm)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def new_game(self, settings=None):
        game = self.store.prepare_game(self.user_id, self.script, "builtin:test", "version", workflow_config=(settings or WorkflowSettings()).model_dump())
        await self.service.activate_game(self.user_id, game["id"], "shen_zhiwei")
        return await self.service.get_engine(self.user_id, game["id"])

    async def investigation(self):
        for _ in range(4):
            if self.dm.state.scene_phase.value == "investigation":
                break
            self.assertIn(self.dm.state.scene_phase.value, {"opening", "private_reveal", "briefing"})
            result = await self.workflow.dispatch(str(uuid.uuid4()), {"type": "advance_phase"})
            self.assertEqual(result[-1]["status"], "completed", result)
        self.assertEqual(self.dm.state.scene_phase.value, "investigation")

    async def tool(self, role, name, args, call_id=None):
        frame = ExecutionFrame(game_id=self.game["id"], run_id=self.dm.runtime_scopes["dm"].run_id, request_id=str(uuid.uuid4()))
        token = execution_frame.set(frame)
        try:
            scope = self.dm.runtime_scopes[role]
            call_id = call_id or str(uuid.uuid4())
            self.service.runtime_store.enqueue_tool(scope, call_id, frame.turn_id, frame.request_id, name, args)
            return await ToolGateway(self.service, self.user_id, self.dm).execute(scope, call_id)
        finally:
            execution_frame.reset(token)

    async def test_native_director_and_role_loop_persist_isolated_records(self):
        await self.investigation()
        result = await self.workflow.dispatch("public-turn-0001", {"type": "player_speech", "content": "大家核对一下现在掌握的时间线。"})
        self.assertEqual(result[-1]["status"], "completed", result)
        with self.store._connect() as connection:
            models = [dict(row) for row in connection.execute("SELECT * FROM model_requests")]
            tools = [dict(row) for row in connection.execute("SELECT * FROM tool_calls")]
        self.assertTrue(any(row["actor_kind"] == "dm" for row in models), models)
        self.assertTrue(any(row["tool_name"] == "search_scene" and row["status"] == "succeeded" for row in tools), tools)
        self.assertTrue(any(row["tool_name"] == "select_actor" for row in tools))
        self.assertTrue(all(row["game_id"] == self.game["id"] for row in models))
        self.assertTrue(self.workflow.checkpoint_path.exists())

    async def test_same_request_replays_without_more_model_calls_or_effects(self):
        await self.investigation()
        message = {"type": "player_speech", "content": "先核对时间线。"}
        first = await self.workflow.dispatch("retry-0001", message)
        with self.store._connect() as connection:
            before = connection.execute("SELECT COUNT(*) FROM model_requests").fetchone()[0]
        snapshot = self.dm.export_runtime_snapshot()
        second = await self.workflow.dispatch("retry-0001", message)
        self.assertEqual(first, second)
        after = self.dm.export_runtime_snapshot()
        snapshot.pop("saved_at_epoch", None)
        after.pop("saved_at_epoch", None)
        self.assertEqual(snapshot, after)
        with self.store._connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM model_requests").fetchone()[0], before)
        with self.assertRaises(ValueError):
            await self.workflow.dispatch("retry-0001", {**message, "content": "不同内容"})

    async def test_named_roles_reply_even_when_dm_repeatedly_picks_someone_else(self):
        await self.investigation()
        first, second, third = self.dm.state.ai_role_ids
        client=DMDirector(self.dm).client
        wrong=parse_native_message({'role':'assistant','content':None,'tool_calls':[{'id':'wrong-pick','type':'function',
            'function':{'name':'select_actor','arguments':json.dumps({'role_id':first})}}]})
        content='周既明和许砚舟，请分别说明停电时自己在哪里？'
        with patch.object(client,'chat_tools',new=AsyncMock(return_value=wrong)):
            events=await self.workflow.dispatch('two-named-roles',{'type':'player_speech','content':content})
        speakers={e.get('role_id') for e in events if e['type']=='ai_speech'}
        self.assertTrue({second,third}.issubset(speakers),events)
        self.assertNotIn(first,speakers)
        self.assertEqual(next(e for e in events if e['type']=='human_speech_echo')['request_id'],'two-named-roles')
        for role in self.dm.state.ai_role_ids:
            self.assertIn(content,json.dumps(self.dm.agent_pool.get(role).export_runtime_state(),ensure_ascii=False))
        with self.store._connect() as connection:
            rejected=connection.execute("SELECT result_json FROM tool_calls WHERE request_id=? AND tool_name='select_actor'",('two-named-roles',)).fetchall()
            self.assertTrue(rejected)
            self.assertTrue(all('ACTOR_NOT_SCHEDULED' in row[0] for row in rejected))
            counts=connection.execute("SELECT actor_kind,actor_role_id,COUNT(*) FROM model_requests WHERE game_id=? AND turn_id=(SELECT turn_id FROM workflow_commands WHERE game_id=? AND request_id=?) GROUP BY actor_kind,actor_role_id",(self.game['id'],self.game['id'],'two-named-roles')).fetchall()
            self.assertTrue(all(row[2]<=self.dm.workflow_settings.max_model_requests_per_role_turn for row in counts),counts)

    async def test_failed_named_role_does_not_silence_other_named_role(self):
        await self.investigation()
        failed_role, other=self.dm.state.ai_role_ids[1:]
        original=self.dm._call_agent
        async def fail_one(context,**kwargs):
            if context.role_id==failed_role and context.purpose=='native_tool_turn':
                return None,True
            return await original(context,**kwargs)
        with patch.object(self.dm,'_call_agent',new=fail_one):
            events=await self.workflow.dispatch('one-failure',{'type':'player_speech','content':'周既明、许砚舟，回应一下刚才的问题。'})
        self.assertTrue(any(e['type']=='ai_speech' and e.get('role_id')==other for e in events),events)
        self.assertFalse(any(e['type']=='ai_speech' and e.get('role_id')==failed_role for e in events))
        self.assertTrue(any(e.get('code')=='PUBLIC_RESPONSE_MISSING' for e in events))
        stored=self.store.realtime_events_for_request(self.game['id'],'one-failure')
        self.assertEqual([event['payload'] for event in stored],events)
        before=len(stored)
        replay=await self.workflow.dispatch('one-failure',{'type':'player_speech','content':'周既明、许砚舟，回应一下刚才的问题。'})
        self.assertEqual(replay,events)
        self.assertEqual(len(self.store.realtime_events_for_request(self.game['id'],'one-failure')),before)

    async def test_public_response_limit_and_activity_use_actual_actor(self):
        self.game,self.dm=await self.new_game(WorkflowSettings(max_public_responders=1))
        self.workflow=GameWorkflow(self.service,self.user_id,self.dm)
        await self.investigation()
        activities=[]
        async def collect(event):activities.append(event)
        events=await self.workflow.dispatch('limited-response',{'type':'player_speech','content':'周既明、许砚舟，请回应。'},activity_sink=collect)
        speakers={e.get('role_id') for e in events if e['type']=='ai_speech'}
        self.assertEqual(speakers,{'zhou_jiming'},events)
        self.assertEqual({e['actor_role_id'] for e in activities},{'dm','zhou_jiming'})
        self.assertTrue(any(e['activity']=='searching' for e in activities))
        self.assertTrue(all(set(e)=={'type','actor_role_id','activity'} for e in activities))

    async def test_public_speech_validation_rejection_has_no_public_effect(self):
        await self.investigation()
        role=self.dm.state.ai_role_ids[0]
        before=list(self.dm.state.public_history)
        with patch.object(self.dm,'_validate_agent_speech',new=AsyncMock(return_value=('已拦截',True))):
            result=await self.tool(f'role:{role}','speak_public',{'content':'未通过边界的发言'})
        self.assertEqual(result.code,'CONTENT_REJECTED')
        self.assertFalse(result.gameplay_committed)
        self.assertEqual(before,self.dm.state.public_history)

    async def test_role_can_search_then_publish_true_or_distorted_testimony(self):
        await self.investigation()
        role=self.dm.state.ai_role_ids[1]
        target=self.dm.mechanic_registry.get('search').available_targets(1,role)[0]['id']
        result=await self.tool(f'role:{role}','search_scene',{'target_id':target})
        clue=result.data['clues'][0]
        for mode,text in [('truthful',''),('distorted','我认为这个线索不足以证明任何人的行踪。')]:
            result=await self.tool(f'role:{role}','share_clue',{'clue_id':clue['clue_id'],'mode':mode,'scope':'public','shared_content':text})
            self.assertEqual(result.status,'succeeded',result)
            self.assertEqual(result.data['published']['content'],clue['truth_content'] if mode=='truthful' else text)
        self.assertEqual(next(c for c in self.dm.get_role_clues(role) if c['clue_id']==clue['clue_id'])['truth_content'],clue['truth_content'])
        private_text='我暂时只愿意对你说：这条线索还需要复核。'
        result=await self.tool(f'role:{role}','share_clue',{'clue_id':clue['clue_id'],'mode':'distorted','scope':'private',
            'target_role_id':self.dm.state.human_player_role_id,'shared_content':private_text})
        self.assertEqual(result.status,'succeeded',result)
        events=self.store.list_realtime_events(self.user_id,self.game['id'],0,200)
        private_event=next(e['payload'] for e in events if e['payload'].get('public_status')=='shared_with_player')
        self.assertEqual(private_event['channel'],'private');self.assertEqual(private_event['conversation_role_id'],role)
        self.assertNotIn(private_text,json.dumps(DMDirector(self.dm).messages(role),ensure_ascii=False))
        for other in self.dm.state.ai_role_ids:
            if other!=role:self.assertNotIn(private_text,json.dumps(self.dm.agent_pool.get(other).export_runtime_state(),ensure_ascii=False))

    async def test_dm_never_receives_private_dialogue_by_default(self):
        await self.investigation()
        role = self.dm.state.ai_role_ids[0]
        self.dm.agent_pool.get(role).remember_private_exchange(1, "另一个角色", "received", "PRIVATE_CANARY_8274")
        self.dm.state.audit_log.append({"private": "AUDIT_CANARY_8298"})
        text = json.dumps(DMDirector(self.dm).messages(role), ensure_ascii=False)
        self.assertIn("IMMUTABLE_SCRIPT", text)
        self.assertNotIn("PRIVATE_CANARY", text)
        self.assertNotIn("AUDIT_CANARY", text)

    async def test_search_receipt_replay_does_not_spend_more_ap(self):
        await self.investigation()
        role = self.dm.state.ai_role_ids[0]
        call_id = str(uuid.uuid4())
        target = self.dm.mechanic_registry.get("search").available_targets(1, role)[0]["id"]
        result = await self.tool(f"role:{role}", "search_scene", {"target_id": target}, call_id)
        self.assertEqual(result.status, "succeeded", result)
        self.assertTrue(result.data["clues"])
        before = self.dm.export_runtime_snapshot()
        replay = await ToolGateway(self.service, self.user_id, self.dm).execute(self.dm.runtime_scopes[f"role:{role}"], call_id)
        self.assertEqual(replay, result)
        after = self.dm.export_runtime_snapshot()
        before.pop("saved_at_epoch", None)
        after.pop("saved_at_epoch", None)
        self.assertEqual(after, before)

    async def test_forbidden_tools_and_extra_game_ids_rejected(self):
        await self.investigation()
        role = "role:" + self.dm.state.ai_role_ids[0]
        result = await self.tool(role, "publish_task", {"task_id": "stage:1:task:0"})
        self.assertEqual(result.code, "TOOL_FORBIDDEN")
        result = await self.tool(role, "search_scene", {"target_id": "clocktower", "game_id": 999})
        self.assertEqual(result.code, "INVALID_ARGUMENTS")
        self.assertFalse(result.gameplay_committed)

    async def test_cross_game_tool_identifier_cannot_be_reused(self):
        await self.investigation()
        role = "role:" + self.dm.state.ai_role_ids[0]
        call_id = str(uuid.uuid4())
        await self.tool(role, "record_note", {"content": "测试判断"}, call_id)
        game, other_dm = await self.new_game()
        scope = other_dm.runtime_scopes[role]
        with self.assertRaises(RuntimeAccessError):
            self.service.runtime_store.enqueue_tool(scope, call_id, "turn", "request", "record_note", {"content": "测试判断"})
        with self.assertRaises(RuntimeAccessError):
            self.service.runtime_store.tool_record(scope, call_id)

    async def test_pause_resume_rotates_instances_and_rejects_old_scope(self):
        await self.investigation()
        role = self.dm.state.ai_role_ids[0]
        old = self.dm.runtime_scopes[f"role:{role}"]
        await self.tool(f"role:{role}", "record_note", {"content": "同局恢复应保留的判断"})
        self.service.pause_game(self.user_id, self.game["id"])
        _, new_dm = await self.service.get_engine(self.user_id, self.game["id"])
        new = new_dm.runtime_scopes[f"role:{role}"]
        self.assertEqual(old.context_id, new.context_id)
        self.assertNotEqual(old.agent_instance_id, new.agent_instance_id)
        self.assertNotEqual(old.run_id, new.run_id)
        self.assertIn("同局恢复", json.dumps(new_dm.agent_pool.get(role).export_runtime_state(), ensure_ascii=False))
        with self.assertRaises(RuntimeAccessError):
            self.service.runtime_store.assert_scope(old)

    async def test_yaml_round_and_tool_limits_are_frozen_per_game(self):
        settings = WorkflowSettings(max_model_requests_per_role_turn=1, max_tool_calls_per_role_turn=1, max_rounds_per_role_turn=1)
        self.game, self.dm = await self.new_game(settings)
        self.workflow = GameWorkflow(self.service, self.user_id, self.dm)
        await self.investigation()
        await self.workflow.dispatch("bounded-turn", {"type": "player_speech", "content": "核对线索"})
        with self.store._connect() as connection:
            counts = connection.execute("SELECT actor_kind,actor_role_id,COUNT(*) AS count FROM model_requests WHERE game_id=? GROUP BY actor_kind,actor_role_id", (self.game["id"],)).fetchall()
        self.assertTrue(counts)
        self.assertTrue(all(row["count"] <= 1 for row in counts))
        self.service.workflow_defaults = WorkflowSettings(max_rounds_per_role_turn=10)
        self.service.pause_game(self.user_id, self.game["id"])
        _, new_dm = await self.service.get_engine(self.user_id, self.game["id"])
        self.assertEqual(new_dm.workflow_settings.max_rounds_per_role_turn, 1)

    async def test_private_invitation_decline_has_no_dialogue_effect(self):
        await self.investigation()
        first, second = self.dm.state.ai_role_ids[:2]
        with patch.object(self.dm, "_call_agent", new=AsyncMock(return_value=("REJECT", False))):
            result = await self.tool(f"role:{first}", "private_exchange", {"target_role_id": second, "content": "愿意私下核对吗？"})
        self.assertEqual(result.code, "INVITATION_DECLINED", result)
        self.assertFalse(result.data["accepted"])
        self.assertEqual(self.dm.agent_pool.get(first)._private_memory, [])
        self.assertEqual(self.dm.agent_pool.get(second)._private_memory, [])

    async def test_logs_hide_agents_until_completion_and_check_owner(self):
        await self.investigation()
        await self.workflow.dispatch("logged-turn", {"type": "player_speech", "content": "核对线索"})
        logs = self.service.runtime_store.logs(self.user_id, self.game["id"])
        self.assertEqual(logs["model_requests"], [])
        self.assertTrue(all(row["actor_kind"] == "human" for row in logs["tool_calls"]))
        with self.assertRaises(KeyError):
            self.service.runtime_store.logs(999, self.game["id"])
        self.store.update_game(self.game["id"], 1, "completed", "replay")
        logs = self.service.runtime_store.logs(self.user_id, self.game["id"])
        self.assertTrue(logs["model_requests"])

    async def test_checkpoint_failure_after_tool_commit_preserves_phase_and_receipt(self):
        original = AsyncSqliteSaver.aput
        async def fail_after_commit(saver, *args, **kwargs):
            with self.store._connect() as connection:
                committed = connection.execute("SELECT COUNT(*) FROM tool_calls WHERE status='succeeded'").fetchone()[0]
            if committed:
                raise RuntimeError("injected checkpoint failure")
            return await original(saver, *args, **kwargs)
        message = {"type": "advance_phase"}
        with patch.object(AsyncSqliteSaver, "aput", new=fail_after_commit):
            result = await self.workflow.dispatch("checkpoint-failure", message)
        self.assertEqual(result[-1]["status"], "failed", result)
        self.assertEqual(self.dm.state.scene_phase.value, "private_reveal")
        self.assertEqual(self.store.get_game(self.user_id, self.game["id"])["current_phase"], "private_reveal")
        await self.workflow.dispatch("checkpoint-failure", message)
        self.assertEqual(self.dm.state.scene_phase.value, "private_reveal")
        next_result = await self.workflow.dispatch("next-command", message)
        self.assertEqual(next_result[-1]["status"], "completed")
        self.assertEqual(self.dm.state.scene_phase.value, "briefing")
        final_result = await self.workflow.dispatch("begin-investigation", message)
        self.assertEqual(final_result[-1]["status"], "completed")
        self.assertEqual(self.dm.state.scene_phase.value, "investigation")

    async def test_tool_receipt_write_failure_rolls_back_clue_and_ap(self):
        await self.investigation()
        role = self.dm.state.ai_role_ids[0]
        search = self.dm.mechanic_registry.get("search")
        target = search.available_targets(1, role)[0]["id"]
        ap = search.remaining_ap(1, role)
        original = self.service.runtime_store.finish_tool
        def fail_on_success(call_id, result):
            if result["status"] == "succeeded":
                raise RuntimeError("injected receipt failure")
            return original(call_id, result)
        with patch.object(self.service.runtime_store, "finish_tool", side_effect=fail_on_success):
            result = await self.tool(f"role:{role}", "search_scene", {"target_id": target})
        self.assertEqual(result.status, "failed")
        self.assertFalse(result.gameplay_committed)
        self.assertEqual(self.dm.mechanic_registry.get("search").remaining_ap(1, role), ap)
        self.assertEqual(self.dm.get_role_clues(role), [])
        self.assertEqual(self.store.list_role_clues(self.user_id, self.game["id"]), [])

    async def test_late_model_response_is_rejected_after_pause(self):
        await self.investigation()
        scope = self.dm.runtime_scopes["dm"]
        client = EchoLLM()
        model_id = str(uuid.uuid4())
        async def delayed():
            self.service.pause_game(self.user_id, self.game["id"])
            return "LATE_RESPONSE"
        with self.assertRaises(RuntimeAccessError):
            await recorded_model_call(self.service.runtime_store, self.dm.workflow_settings, scope,
                model_id, client, [{"role": "user", "content": "test"}], "plain_text", delayed, {})
        with self.store._connect() as connection:
            row = connection.execute("SELECT status,output_json FROM model_requests WHERE model_request_id=?", (model_id,)).fetchone()
        self.assertEqual(row["status"], "rejected")
        self.assertIn("LATE_RESPONSE", row["output_json"])

    async def test_interrupted_request_replays_receipts_without_spending_model_calls(self):
        scope = self.dm.runtime_scopes["dm"]
        self.service.runtime_store.start_command(self.game["id"], scope.run_id, "incomplete-1", "turn", {"type": "advance_phase"})
        model_id = str(uuid.uuid4())
        self.service.runtime_store.start_model(scope, model_id, "turn", "native_tools", [], {})
        self.service.pause_game(self.user_id, self.game["id"])
        _, dm = await self.service.get_engine(self.user_id, self.game["id"])
        result = await GameWorkflow(self.service, self.user_id, dm).dispatch("incomplete-1", {"type": "advance_phase"})
        self.assertEqual(result[-1]["status"], "interrupted")
        self.assertEqual(dm.state.scene_phase.value, "opening")
        with self.store._connect() as connection:
            self.assertEqual(connection.execute("SELECT status FROM model_requests WHERE model_request_id=?", (model_id,)).fetchone()[0], "unknown")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM model_requests").fetchone()[0], 1)

    async def test_echo_complete_game_uses_native_votes_and_reveals_wrong_ending(self):
        class WrongVoteEcho(EchoLLM):
            async def chat_tools(self, messages, definitions, *, transport="native_tools"):
                if any(tool["function"]["name"] == "cast_role_vote" for tool in definitions):
                    self.last_provider_invoked = True
                    return parse_native_message({"content": None, "tool_calls": [{"id": "vote_" + uuid.uuid4().hex,
                        "type": "function", "function": {"name": "cast_role_vote", "arguments": '{"target_role_id":"shen_zhiwei"}'}}]})
                return await super().chat_tools(messages, definitions, transport=transport)
        for role in self.dm.state.ai_role_ids:
            self.dm.agent_pool.get(role)._llm = WrongVoteEcho()
        for _ in range(24):
            phase = self.dm.state.scene_phase.value
            if phase == "replay":
                break
            if phase == "investigation":
                message = {"type": "request_phase_end"}
            elif phase == "dm_hosting" and self.dm.stage_resolution_pending():
                vote = self.dm.get_stage_resolution()["vote"]
                candidates = [role["role_id"] for role in vote["eligible_roles"]]
                wrong = next(role for role in candidates if role != self.script["truth"]["culprit_role_id"])
                message = {"type": "stage_vote", "target_role_id": wrong}
            else:
                message = {"type": "advance_phase"}
            result = await self.workflow.dispatch(str(uuid.uuid4()), message)
            self.assertEqual(result[-1]["status"], "completed", result)
            self.assertFalse(any(event["type"] == "error" for event in result), result)
        self.assertEqual(self.dm.state.scene_phase.value, "replay")
        self.assertFalse(self.dm.get_replay()["final_decision"]["correct"])
        self.assertTrue(self.dm.get_replay()["truth_revealed"])
        self.assertTrue(self.dm.get_replay()["full_story"])
        with self.store._connect() as connection:
            names = {row[0] for row in connection.execute("SELECT tool_name FROM tool_calls")}
        self.assertIn("decide_phase_end", names)
        self.assertIn("cast_role_vote", names)

    def test_yaml_rejects_unsupported_parallelism_and_retry(self):
        for values in ({"concurrency": 2}, {"automatic_retries": 1}, {"max_rounds_per_role_turn": 0}, {"extra": 1}):
            with self.assertRaises(ValidationError):
                WorkflowSettings(**values)
        self.assertFalse(load_workflow_settings().dm_reads_private_dialogue)
