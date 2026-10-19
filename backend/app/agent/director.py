from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import replace
from typing import Any

from llm.tools import ToolModelReply, json_transport_messages
from runtime.models import recorded_model_call
from llm.budget import estimate_tokens, ContextBudgetError


class DMDirector:
    """Omniscient script access, restricted live observations, no shared role memory."""
    def __init__(self, dm: Any) -> None:
        self.dm = dm
        if dm.dm_llm is None:
            dm.dm_llm = dm.llm_factory.create()
        self.client = dm.dm_llm
        if dm.workflow_settings.reasoning_effort and hasattr(self.client,'reasoning_effort'):
            self.client.reasoning_effort=dm.workflow_settings.reasoning_effort

    def messages(self, recommended_role_id: str, reserved_tokens: int = 0) -> list[dict[str, Any]]:
        state = self.dm._require_state()
        config = self.dm._stage_flow_config()
        data: dict[str, Any] = {
            "stage": state.current_stage_num, "phase": state.scene_phase.value,
            "candidate_role_ids": list(state.ai_role_ids), "recommended_role_id": recommended_role_id,
            'hosting_section': {'briefing':'public_briefing','dm_hosting':'dm_hosting'}.get(state.scene_phase.value,''),
            "public_events": state.public_history,
            "tasks": [{"task_id": f"stage:{state.current_stage_num}:task:{index}", "content": text}
                      for index, text in enumerate(config.get("public_tasks", []))],
        }
        from runtime.contracts import execution_frame
        frame=execution_frame.get()
        if frame and frame.candidate_role_ids:
            data['candidate_role_ids'] = frame.candidate_role_ids
        data['remaining_tool_calls']=self.dm.workflow_settings.max_tool_calls_per_role_turn-(frame.tool_counts.get('dm:dm',0) if frame else 0)
        # A deliberate opt-in for future rules; the shipped YAML and user decision are false.
        if self.dm.workflow_settings.dm_reads_private_dialogue:
            data["authorized_private_dialogue"] = {
                role: self.dm.agent_pool.get(role)._private_memory for role in state.ai_role_ids}
        script_data = self.dm._require_script()
        if self.dm.workflow_settings.context_strategy == 'archive_retrieval':
            data['public_events'] = state.public_history[-6:]
            data['archive_index'] = self.dm.memory_archive.index(self.dm.runtime_scopes['dm'], state.current_stage_num,
                ' '.join(str(event.get('content','')) for event in state.public_history[-2:]), self.dm.workflow_settings.memory_index_items)
            script_data = {'script_meta':script_data['script_meta'], 'current_stage':{'title':config.get('title'),'public_tasks':config.get('public_tasks',[])},
                           'roles':[{'role_id':r['role_id'],'role_name':r['role_name'],'public_identity':r['public_identity']} for r in script_data['roles']]}
        messages = [
            {"role": "system", "content": "你是本场剧本杀的 DM 调控 Agent。静态剧本包含全知信息，但只能通过已注册工具主持。"
                "不要将真相或角色秘密发布给无权读取的玩家。默认不得读取私聊正文。"
                "在调查阶段选择一个角色执行本次行动，优先回应最新的公开发言。"
                "调查调度入口必须调用 select_actor，返回一个 candidate_role_ids 内的角色；本入口不执行档案研读。"
                "在开场或主持阶段，优先调用 present_script_section 选择 hosting_section 所指定的当前公开段落；正文由规则层读取剧本。"
                "任务只能从当前幕已有任务选择；不替真人确认阅读、投票或推进阶段。"
                "工具结果是执行事实；被拒绝的调用不代表行动完成。文本摘要不会自动成为游戏事件。"},
            {"role": "user", "content": "[IMMUTABLE_SCRIPT]\n" + json.dumps(script_data, ensure_ascii=False, separators=(",", ":"))},
            {"role": "user", "content": "[DM_DIRECTOR_DATA]\n" + json.dumps(data, ensure_ascii=False)},
        ]
        if self.dm.workflow_settings.context_strategy == 'archive_retrieval':
            available=self.client.budget.input_limit-reserved_tokens
            while estimate_tokens(messages)>available and (data['public_events'] or data['archive_index']):
                if data['public_events']:data['public_events']=data['public_events'][1:]
                else:data['archive_index']=data['archive_index'][:-1]
                messages[-1]['content']='[DM_DIRECTOR_DATA]\n'+json.dumps(data,ensure_ascii=False)
            if estimate_tokens(messages)>available:
                raise ContextBudgetError('DM 本回合续接已占满输入预算，原始档案和已提交行动保留')
        return messages

    def prepared_messages(self,recommended,tools,history):
        reserve=estimate_tokens(history)+len(json.dumps(tools,ensure_ascii=False).encode('utf-8'))+32
        return [*self.messages(recommended,reserve),*history]

    async def call(self, recommended: str, tools: list[dict[str, Any]], history: list[dict[str, Any]]) -> ToolModelReply:
        scope = self.dm.runtime_scopes["dm"]
        messages = self.prepared_messages(recommended,tools,history)
        transport = self.dm.workflow_settings.transport
        actual = json_transport_messages(messages, tools) if transport == "validated_action_json" else messages
        model_id = str(uuid.uuid4())
        self.client.reset_call_metadata()
        async def operation():
            deadline = self.dm._require_state().investigation_deadline_at
            if deadline is not None and deadline <= time.time():
                raise ValueError("调查时间已经结束，不能开始新的 DM 模型请求")
            response = self.client.chat_tools(messages, tools, transport=transport)
            if deadline is not None:
                return await asyncio.wait_for(response, timeout=max(0.001, deadline-time.time()))
            return await response
        reply = await recorded_model_call(self.dm.runtime_store, self.dm.workflow_settings, scope,
            model_id, self.client, actual, transport, operation,
            {"purpose": "dm_director", "stage": self.dm._require_state().current_stage_num,
             "tools": tools, "dm_reads_private_dialogue": self.dm.workflow_settings.dm_reads_private_dialogue})
        return replace(reply, model_request_id=model_id)
