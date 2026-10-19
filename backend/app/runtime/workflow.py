from __future__ import annotations

import json
import uuid
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agent.director import DMDirector
from dm.engine import ScenePhase
from mechanics.search import SearchMechanic
from runtime.contracts import ExecutionFrame, RuntimeAccessError, execution_frame
from tools.contracts import tool_definitions
from tools.gateway import ToolGateway


class ActorState(TypedDict, total=False):
    # Checkpoints hold references; confidential messages stay in their scoped store.
    role_id: str
    rounds: int
    model_ids: list[str]
    tool_ids: list[str]
    pending_tool_ids: list[str]
    selected_role_id: str
    stopped: bool


class DirectorState(TypedDict, total=False):
    game_id: int
    run_id: str
    request_id: str
    turn_id: str
    scheduled: bool
    hosting: bool
    recommended_role_id: str
    selected_role_id: str


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
        messages: list[dict[str, Any]] = []
        for model_id in state.get("model_ids", []):
            record = self.store.model_record(scope, model_id)
            wire = record["output"]
            if not wire or record["status"] != "completed":
                raise RuntimeAccessError("未完成的模型调用不能用于后续推理")
            messages.append(wire)
            for tool_id in state.get("tool_ids", []):
                tool = self.store.tool_record(scope, tool_id)
                if tool["model_request_id"] == model_id:
                    result = tool["result"] or {"status": "unknown", "code": "UNCOMMITTED"}
                    messages.append({"role": "tool", "tool_call_id": tool["provider_tool_call_id"] or tool_id,
                                     "content": json.dumps(result, ensure_ascii=False)})
        return messages

    def role_context(self, role_id: str):
        state = self.dm._require_state()
        enabled = set(self.dm.get_scene_summary()["enabled_actions"])
        search = self.dm.mechanic_registry.get("search")
        targets = search.available_targets(state.current_stage_num, role_id) if (
            "search" in enabled and isinstance(search, SearchMechanic) and search.remaining_ap(state.current_stage_num, role_id) > 0) else []
        data = {"search_targets": targets, "public_allowed": "public_speech" in enabled,
                "candidate_role_ids": [role for role in [state.human_player_role_id, *state.ai_role_ids] if role != role_id],
                "private_candidates": [role for role in state.ai_role_ids if role != role_id] if "whisper" in enabled else []}
        frame=execution_frame.get()
        key='role:'+role_id
        data['remaining_tool_calls']=self.dm.workflow_settings.max_tool_calls_per_role_turn-(frame.tool_counts.get(key,0) if frame else 0)
        data['remaining_model_requests']=self.dm.workflow_settings.max_model_requests_per_role_turn-(frame.model_counts.get(key,0) if frame else 0)
        data['response_required'] = bool(frame and role_id in frame.response_role_ids and role_id not in frame.responded_role_ids)
        data['public_response_max_chars'] = 500
        data['public_trigger'] = frame.public_trigger if frame else ''
        return self.dm._build_agent_context(role_id=role_id, channel="autonomous", purpose="native_tool_turn",
            instruction="[ROLE_TOOL_TURN]\n" + json.dumps(data, ensure_ascii=False)
                + "\n根据自己的任务、角色已知信息和最新事件决定行动。使用工具执行搜证、交流、分享和记笔记。"
                "搜证后先阅读工具返回的原始线索，再决定保密或分享；工具被拒绝时行动没有完成。"
                "response_required 为 true 时，本次只调用 speak_public 直接回应 public_trigger，成功后再考虑其他工具。"
                "content 必须为 1 至 500 个字符（含标点），建议 120 至 250 字；不必一次讲完全部卷宗。"
                "不能以研读档案、搜证、记笔记或私聊代替答复。普通正文即使声称已发言，也没有公开且不算完成。"
                "可以承认不知情、澄清、隐瞒或反问，但不得借用其他角色秘密或未来信息。回应后再考虑搜证。"
                "搜证所得可通过 share_clue 原文公开或改写说法以服务自己的任务；改写仍是证词，不能成为已证实事实。"
                "本次提案的工具总数必须不超过 remaining_tool_calls。不要重复已经提交的行动。"
                "私聊正文只对参与双方可见。结束时给出简短摘要，文本不会自动公开或执行。",
            instruction_source="role_tool_workflow")

    def _actor_graph(self, saver: Any, kind: str, recommended: str = ""):
        async def model(state: ActorState):
            scope = self._scope(kind, state.get("role_id", "dm"))
            self.store.assert_scope(scope)
            tools = tool_definitions(kind)
            frame = execution_frame.get()
            if kind == 'role' and scope.actor_role_id in frame.response_role_ids and scope.actor_role_id not in frame.responded_role_ids:
                tools = [tool for tool in tools if tool['function']['name'] == 'speak_public']
            if kind=='dm' and self.dm.state.scene_phase==ScenePhase.INVESTIGATION:
                # The scheduling node must dispatch an actor. Hosting/retrieval
                # tools run in their own scene workflow, not instead of dispatch.
                tools=[tool for tool in tools if tool['function']['name']=='select_actor']
            if kind=='dm' and self.dm.state.scene_phase!=ScenePhase.INVESTIGATION:
                tools = [tool for tool in tools if tool['function']['name'] in {'present_script_section','publish_task','dispatch_stage_information','read_memory'}]
            history = self._history(scope, state)
            response_required = kind == 'role' and scope.actor_role_id in frame.response_role_ids and scope.actor_role_id not in frame.responded_role_ids
            if response_required and state.get('rounds', 0):
                # This is a new bounded tool proposal, never a fabricated tool
                # receipt or a conversion of the previous assistant's prose.
                history.append({'role':'user','content':'[PUBLIC_RESPONSE_REQUIRED]\n'
                    '本回合尚无成功的 speak_public 收据，公开答复仍未执行。'
                    '请根据已有授权信息，仅调用 speak_public，content 为 1 至 500 个字符（含标点）。'
                    '请自行精简内容；普通正文、已拒绝的调用和其他工具都不能代替公开发言。'})
            from llm.budget import ContextBudgetError, estimate_tokens
            try:
                if kind=='dm': DMDirector(self.dm).prepared_messages(recommended,tools,history)
                else:
                    agent=self.dm.agent_pool.get(scope.actor_role_id)
                    if agent.archive is not None:
                        agent.prepare(self.role_context(scope.actor_role_id),reserved_tokens=estimate_tokens(history)+len(json.dumps(tools,ensure_ascii=False).encode('utf-8'))+512)
            except ContextBudgetError:
                self.publish_status({'type':'actor_turn_stopped','actor_role_id':scope.actor_role_id,
                    'code':'CONTEXT_BUDGET_EXHAUSTED','message':'本回合输入预算已用完，已提交行动保留；下个回合可按编号取回档案。'})
                return {'stopped':True}
            await self.activity(scope.actor_role_id, 'thinking')
            try:
                if kind == "dm":
                    reply = await DMDirector(self.dm).call(recommended, tools, history)
                else:
                    reply, failed = await self.dm._call_agent(self.role_context(scope.actor_role_id), tools=tools, wire_history=history)
                    if failed or reply is None or not hasattr(reply, "tool_calls"):
                        raise RuntimeError("角色工具推理未返回有效结果")
            finally:
                await self.activity(scope.actor_role_id, 'idle')
            model_id = reply.model_request_id
            frame = execution_frame.get()
            pending = []
            for index, call in enumerate(reply.tool_calls):
                call_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{scope.game_id}:{model_id}:{index}"))
                self.store.enqueue_tool(scope, call_id, frame.turn_id, frame.request_id, call.name,
                                        call.arguments, model_id, call.provider_call_id)
                pending.append(call_id)
            return {"rounds": state.get("rounds", 0)+1, "model_ids": [*state.get("model_ids", []), model_id],
                    "pending_tool_ids": pending, "stopped": not bool(pending) and not response_required}

        async def tools(state: ActorState):
            scope = self._scope(kind, state.get("role_id", "dm"))
            selected = state.get("selected_role_id", "")
            ids = state.get("pending_tool_ids", [])
            for call_id in ids:
                tool = self.store.tool_record(scope, call_id)
                await self.activity(scope.actor_role_id, 'searching' if tool['tool_name']=='search_scene' else 'thinking')
                try:
                    result = await self.gateway.execute(scope, call_id)
                finally:
                    await self.activity(scope.actor_role_id, 'idle')
                if result.status=='succeeded' and result.gameplay_committed and tool['tool_name'] in {'speak_public','public_exchange'}:
                    execution_frame.get().responded_role_ids.add(scope.actor_role_id)
                if kind == "dm" and tool["tool_name"] == "select_actor" and result.status == "succeeded":
                    selected = result.data["role_id"]
            return {"tool_ids": [*state.get("tool_ids", []), *ids], "pending_tool_ids": [], "selected_role_id": selected}

        def route(state: ActorState):
            if state.get("stopped") or self.dm._require_state().scene_phase != ScenePhase.INVESTIGATION or self.dm.investigation_seconds_remaining() == 0:
                return END
            if kind == "dm" and state.get("selected_role_id"):
                return END
            scope = self._scope(kind, state.get("role_id", "dm"))
            frame = execution_frame.get()
            key = f"{scope.actor_kind}:{scope.actor_role_id}"
            settings = self.dm.workflow_settings
            if state.get("rounds", 0) >= settings.max_rounds_per_role_turn or (
                frame.model_counts.get(key, 0) >= settings.max_model_requests_per_role_turn
                or frame.tool_counts.get(key, 0) >= settings.max_tool_calls_per_role_turn):
                return END
            return "model"

        graph = StateGraph(ActorState)
        graph.add_node("model", model)
        graph.add_node("tools", tools)
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", lambda state: END if state.get("stopped") else "tools")
        graph.add_conditional_edges("tools", route)
        return graph.compile(checkpointer=saver)

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
