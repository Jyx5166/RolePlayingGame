"""Game-command dispatch and the outer DM/role orchestration graph."""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from domain.state import ScenePhase
from runtime.contracts import ExecutionFrame, RuntimeAccessError, execution_frame
from tools.gateway import ToolGateway

from .actor_graph import ActorWorkflow
from .state import ActorState, DirectorState


class GameWorkflow:
    """Serial, bounded, per-game workflows with independently committed tool receipts.

    Checkpoints are diagnostic/resume references, never the authority for gameplay.
    Interrupted paid calls are not automatically re-executed. A new input starts a new
    turn, loading the canonical game snapshot and actor-specific memories.
    """
    def __init__(self, service: Any, user_id: int, dm: Any) -> None:
        self.service, self.user_id, self.dm = service, user_id, dm
        self.store = service.runtime_store
        self.gateway = ToolGateway(service, user_id, dm)
        self.checkpoint_path = service.store.database_path.with_name(service.store.database_path.stem + ".workflow.db")
        self.actor_workflow = ActorWorkflow(dm, self.store, self.gateway, self.publish_status, self.activity)

    def _scope(self, kind: str, role_id: str = "dm"):
        return self.dm.runtime_scopes["dm" if kind == "dm" else f"role:{role_id}"]

    def publish_status(self, event: dict[str, Any]) -> None:
        # Statuses may occur between committed actions of different roles. Persist
        # them at that position instead of slicing a mixed event list at the end.
        frame=execution_frame.get()
        with self.service.store.transaction():
            self.store.assert_scope(self._scope('dm'))
            self.store.append_events(frame.game_id,frame.request_id,[event])
        frame.public_events.append(event)

    def _history(self, scope: Any, state: ActorState) -> list[dict[str, Any]]:
        return self.actor_workflow._history(scope, state)

    def role_context(self, role_id: str):
        return self.actor_workflow.role_context(role_id)

    def _actor_graph(self, saver: Any, kind: str, recommended: str = ""):
        return self.actor_workflow.build(saver, kind, recommended)

    def _director_graph(self, saver: Any):
        async def accept(state: DirectorState):
            request = interrupt({"kind": "await_game_command", "game_id": state["game_id"], "run_id": state["run_id"]})
            if request != {"request_id": state["request_id"]}:
                raise RuntimeAccessError("输入与本次游戏请求编号不匹配")
            return {}

        async def execute(state: DirectorState):
            frame = execution_frame.get()
            command = self.store.command(state["game_id"], state["request_id"])
            message = command["payload"]
            internal = message["type"] in {"phase_timeout", "autonomy_tick",'hosting_tick'}
            scope = self._scope("dm") if internal else self._scope("human", self.dm._require_state().human_player_role_id)
            name = "internal_reserve_autonomy" if message["type"] == "autonomy_tick" else (
                'internal_hosting_tick' if message['type']=='hosting_tick' else "internal_phase_timeout" if internal else "command_" + message["type"])
            arguments = {} if internal else {key: value for key, value in message.items() if key != "type"}
            call_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{state['game_id']}:{state['request_id']}:command"))
            self.store.enqueue_tool(scope, call_id, frame.turn_id, frame.request_id, name, arguments)
            result = await self.gateway.execute(scope, call_id)
            if result.status != "succeeded":
                if not any(event["type"] == "error" for event in frame.public_events):
                    self.publish_status({"type": "error", "code": result.code, "message": result.message or "操作未执行"})
                return {"scheduled": False}
            scheduled = message["type"] in {"autonomy_tick", "player_speech"} and self.dm._require_state().scene_phase == ScenePhase.INVESTIGATION
            recommended = result.data.get("plan", {}).get("actor_role_id") or result.data.get("recommended_role_id")
            ai_roles = self.dm._require_state().ai_role_ids
            candidates = [recommended] if recommended in ai_roles else []
            if message['type']=='player_speech' and scheduled:
                content = message['content']
                candidates = self.dm._require_turn_manager().mentioned_speakers(content, ai_roles)
                if not candidates and any(word in content for word in ('你们','大家','各位','所有人')):
                    candidates = list(ai_roles)
                if not candidates and ai_roles:
                    # Rotate ordinary public prompts instead of repeatedly picking the first role.
                    count = sum(entry.get('role')=='user' for entry in self.dm.state.public_history)
                    candidates = [recommended] if recommended in ai_roles else [ai_roles[(count-1)%len(ai_roles)]]
                frame.public_trigger = content
                candidates = candidates[:self.dm.workflow_settings.max_public_responders]
                frame.response_role_ids = set(candidates)
                self.dm.state.pending_human_question_from = None
            frame.candidate_role_ids = candidates
            recommended = candidates[0] if candidates else ''
            hosting = self.dm.workflow_settings.model_hosting and self.dm.state.scene_phase in {ScenePhase.BRIEFING,ScenePhase.DM_HOSTING} and (
                message['type']=='hosting_tick' or any(event['type']=='phase_changed' for event in result.data.get('events',[]) or frame.public_events))
            if hosting:
                hosting=self.store.reserve_hosting(self._scope('dm'),self.dm.state.current_stage_num,self.dm.state.scene_phase.value,frame.request_id)
            return {"scheduled": scheduled and bool(recommended), 'hosting':hosting, "recommended_role_id": recommended or ""}

        async def director(state: DirectorState):
            graph = self._actor_graph(saver, "dm", state["recommended_role_id"])
            frame = execution_frame.get()
            try:
                result = await graph.ainvoke({"role_id": "dm", "rounds": 0, "model_ids": [], "tool_ids": []},
                    {"configurable": {"thread_id": f"game:{frame.game_id}:run:{frame.run_id}:dm:{frame.turn_id}"},
                     "recursion_limit": self.dm.workflow_settings.max_graph_steps})
            except Exception:
                if not frame.response_role_ids:
                    raise
                result = {}
                self.publish_status({'type':'actor_turn_stopped','actor_role_id':'dm','code':'DM_SCHEDULING_FAILED',
                    'message':'DM 调度未完成，按公开点名队列继续；没有自动重试模型。'})
            # An invalid scheduling proposal cannot suppress explicitly requested replies.
            selected = result.get('selected_role_id','')
            if not selected and frame.response_role_ids:
                selected = frame.candidate_role_ids[0]
            return {"selected_role_id": selected}

        async def role(state: DirectorState):
            frame = execution_frame.get()
            first = state['selected_role_id']
            queue = [first, *[role for role in frame.candidate_role_ids if role!=first and role in frame.response_role_ids]]
            for role_id in queue:
                if self.dm.state.scene_phase!=ScenePhase.INVESTIGATION or self.dm.investigation_seconds_remaining()==0:
                    break
                scope = self._scope('role',role_id)
                graph = self._actor_graph(saver,'role')
                try:
                    await graph.ainvoke({'role_id':role_id,'rounds':0,'model_ids':[],'tool_ids':[]},
                        {'configurable':{'thread_id':f'game:{scope.game_id}:run:{scope.run_id}:role:{scope.context_id}:{frame.turn_id}'},
                         'recursion_limit':self.dm.workflow_settings.max_graph_steps})
                except Exception:
                    self.publish_status({'type':'actor_turn_stopped','actor_role_id':role_id,
                        'code':'ROLE_TURN_FAILED','message':'角色本回合未能完成，已提交行动保留；其他角色继续回应。'})
                if role_id in frame.response_role_ids and role_id not in frame.responded_role_ids:
                    self.publish_status({'type':'actor_turn_stopped','actor_role_id':role_id,
                        'code':'PUBLIC_RESPONSE_MISSING','message':'该角色本回合未提交有效公开答复，普通正文没有发布；本回合已停止，未自动重试 HTTP 请求。'})
            return {}

        graph = StateGraph(DirectorState)
        graph.add_node("await_input", accept)
        graph.add_node("execute", execute)
        graph.add_node("director", director)
        graph.add_node("role", role)
        graph.add_edge(START, "await_input")
        graph.add_edge("await_input", "execute")
        graph.add_conditional_edges("execute", lambda state: "director" if state.get("scheduled") or state.get('hosting') else END)
        graph.add_conditional_edges("director", lambda state: "role" if state.get("selected_role_id") else END)
        graph.add_edge("role", END)
        return graph.compile(checkpointer=saver)

    async def activity(self, role_id: str, activity: str):
        frame = execution_frame.get()
        if frame and frame.activity_sink:
            await frame.activity_sink({'type':'agent_activity','actor_role_id':role_id,'activity':activity})

    async def dispatch(self, request_id: str, message: dict[str, Any], *, activity_sink=None) -> list[dict[str, Any]]:
        scope = self._scope("dm")
        self.store.assert_scope(scope)
        existing = self.store.command(scope.game_id, request_id)
        frame = ExecutionFrame(game_id=scope.game_id, run_id=scope.run_id, request_id=request_id, activity_sink=activity_sink)
        self.store.start_command(scope.game_id, scope.run_id, request_id, frame.turn_id, message)
        if existing is not None:
            # Complete receipts may be replayed. An interrupted request never re-spends a paid model call.
            events = self.service.store.realtime_events_for_request(scope.game_id, request_id)
            if not any(event["type"] == "game_command_complete" for event in events):
                with self.service.store.transaction():
                    self.store.append_events(scope.game_id, request_id, [
                        {"type": "error", "code": "PREVIOUS_TURN_INTERRUPTED", "message": "上次执行已中断，已提交的行动保留；本请求不自动重试模型。"},
                        {"type": "game_command_complete", "request_id": request_id, "status": "interrupted"}])
                    self.store.finish_command(scope.game_id, request_id, "interrupted")
                events = self.service.store.realtime_events_for_request(scope.game_id, request_id)
            return [event["payload"] if "payload" in event else {key: value for key, value in event.items() if key not in {"event_id", "request_id", "created_at"}} for event in events]
        token = execution_frame.set(frame)
        status = "completed"
        try:
            async with AsyncSqliteSaver.from_conn_string(str(self.checkpoint_path)) as saver:
                graph = self._director_graph(saver)
                config = {"configurable": {"thread_id": f"game:{scope.game_id}:run:{scope.run_id}:director:{frame.turn_id}"},
                          "recursion_limit": self.dm.workflow_settings.max_graph_steps}
                await graph.ainvoke({"game_id": scope.game_id, "run_id": scope.run_id, "request_id": request_id, "turn_id": frame.turn_id}, config)
                await graph.ainvoke(Command(resume={"request_id": request_id}), config)
        except BaseException as exc:
            import asyncio
            status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            # Tools already committed remain valid. Only recover from canonical gameplay state.
            snapshot = self.service.store.get_runtime_snapshot(self.user_id, scope.game_id)
            if snapshot is not None:
                self.dm.restore_runtime_snapshot(snapshot)
            if isinstance(exc, Exception):
                self.publish_status({"type": "error", "code": "WORKFLOW_INTERRUPTED", "message": "本次 Agent 调度未完整执行；已提交的行动已保留，可继续游戏。"})
            else:
                raise
        finally:
            try:
                completion = {"type": "game_command_complete", "request_id": request_id, "status": status}
                # Every action and status already has its own committed receipt.
                with self.service.store.transaction():
                    self.store.assert_scope(scope)
                    self.service.persist_engine_events(scope.game_id, self.dm)
                    self.store.append_events(scope.game_id, request_id, [completion])
                    self.store.finish_command(scope.game_id, request_id, status)
                frame.public_events.append(completion)
            finally:
                execution_frame.reset(token)
        return frame.public_events
