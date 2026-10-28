"""Bounded model/tool loops for DM and role actors."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from agent.director import DMDirector
from domain.state import ScenePhase
from mechanics.search import SearchMechanic
from runtime.contracts import RuntimeAccessError, execution_frame
from runtime.store import RuntimeStore
from tools.contracts import tool_definitions
from tools.gateway import ToolGateway

from .state import ActorState


class ActorWorkflow:
    """Execute actor turns using explicit runtime and event dependencies."""

    def __init__(
        self,
        dm: Any,
        store: RuntimeStore,
        gateway: ToolGateway,
        publish_status: Callable[[dict[str, Any]], None],
        activity: Callable[[str, str], Awaitable[None]],
    ) -> None:
        self.dm = dm
        self.store = store
        self.gateway = gateway
        self.publish_status = publish_status
        self.activity = activity

    def _scope(self, kind: str, role_id: str = "dm"):
        return self.dm.runtime_scopes["dm" if kind == "dm" else f"role:{role_id}"]

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

    def build(self, saver: Any, kind: str, recommended: str = ""):
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
