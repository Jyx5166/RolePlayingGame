from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dm.engine import DMEngine, ScenePhase
from runtime.contracts import RuntimeScope, execution_frame
from tools.contracts import ToolArguments


class DomainActionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ActionOutcome:
    data: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    code: str = "OK"
    rejected: bool = False


class GameActions:
    """Actor-specific adapters into the existing deterministic game rules."""
    def __init__(self, dm: DMEngine) -> None:
        self.dm = dm

    async def human_command(self, message: dict[str, Any]) -> ActionOutcome:
        from ws.handlers import handle_client_message
        if message["type"] == "player_speech" and self.dm.workflow_enabled:
            # The director graph will schedule a role workflow after this public event commits.
            if self.dm.investigation_seconds_remaining() != 0:
                result = await self.dm.handle_human_speech(message["content"])
                events = [{"type": "human_speech_echo", **result}]
                if result.get("warning"):
                    events.append({"type": "speech_warning", "message": result["warning"]})
                return ActionOutcome(data={"recommended_role_id": self.dm._require_state().pending_human_question_from or ""}, events=events)
        events = await handle_client_message(self.dm, message)
        if self.dm.workflow_enabled and any(event.get("fallback") for event in events):
            raise DomainActionError("MODEL_RESPONSE_FAILED", "角色回复未通过校验，本次交流未提交")
        errors = [event for event in events if event["type"] == "error"]
        return ActionOutcome(events=events, code=errors[0].get("code", "COMMAND_REJECTED") if errors else "OK", rejected=bool(errors))

    async def internal_command(self, name: str) -> ActionOutcome:
        from ws.handlers import handle_message
        if name == "phase_timeout":
            return ActionOutcome(events=await handle_message(self.dm, {"type": name}))
        if name == 'hosting_tick':
            return ActionOutcome()
        if name == "reserve_autonomy":
            plan = self.dm.preview_autonomous_turn()
            if plan is None:
                raise DomainActionError("AUTONOMY_NOT_READY", "当前不满足自主行动条件")
            import time
            state = self.dm._require_state()
            state.autonomy_turn_count += 1
            state.autonomy_next_at = time.time() + float(self.dm._autonomy_config()["interval_seconds"])
            return ActionOutcome(data={"plan": plan})
        raise DomainActionError("COMMAND_FORBIDDEN", "未注册的内部操作")

    async def role_tool(self, scope: RuntimeScope, name: str, args: ToolArguments) -> ActionOutcome:
        dm = self.dm
        state = dm._require_state()
        role_id = scope.actor_role_id
        if role_id not in state.ai_role_ids:
            raise DomainActionError("ACTOR_FORBIDDEN", "当前角色不由 Agent 控制")
        permission = dm._require_permission()
        values = args.model_dump()
        frame = execution_frame.get()
        sequence = state.record_sequence + 1
        if name == "speak_public":
            dm._require_investigation_action("public_speech")
            attribution = dm._require_validator().validate_role_attribution(
                role_id, state.current_stage_num, values["content"], dm.agent_pool.get(role_id)._memory_records())
            if not attribution.passed:
                raise DomainActionError("CONTENT_REJECTED", attribution.message or "发言角色或来源归属不匹配")
            content = await self._validate_content(role_id, values["content"], "public")
            role_name = permission.role_name(role_id)
            state.public_history.append({"role": "assistant", "content": f"{role_name}: {content}"})
            event = dm._build_observed_event(actor_role_id=role_id, event_type="public_speech", channel="public", content=content)
            dm._broadcast_observed_event(event)
            dm.record_investigation_event("public_messages", actor_type="agent")
            dm._queue_activity(actor_role_id=role_id, target_role_id=None, event_type="public_speech", channel="public",
                summary=f"{role_name}公开回应：{content}", details={"content": content})
            return ActionOutcome(data={"published": True}, events=[{"type": "ai_speech", "role_id": role_id,
                "role_name": role_name, "content": content, "channel": "public"}])
        if name == "record_note":
            dm._require_investigation_action("public_speech")
            source_key = f"tool-note:{frame.turn_id if frame else sequence}:{sequence}"
            dm.agent_pool.get(role_id).remember_reasoning_note(state.current_stage_num, values["content"], source_key=source_key, phase=state.scene_phase.value)
            dm._queue_notebook(role_id=role_id, section="reasoning", source_type="agent_hypothesis", source_key=source_key,
                               title="角色判断摘要", content=values["content"])
            return ActionOutcome(data={"saved": True})
        if name == "search_scene":
            dm._require_investigation_action("search")
            mechanic = dm.mechanic_registry.get("search")
            if values["target_id"] not in {target["id"] for target in mechanic.available_targets(state.current_stage_num, role_id)}:
                raise DomainActionError("TARGET_UNAVAILABLE", "搜证目标不存在、未解锁或没有可用线索")
            if mechanic.remaining_ap(state.current_stage_num, role_id) <= 0:
                raise DomainActionError("SEARCH_BUDGET_EXCEEDED", "本幕搜证次数已用完")
            before_ids = {clue["clue_id"] for clue in dm.get_role_clues(role_id)}
            event = await dm._run_autonomous_search({"actor_role_id": role_id, "search_target_id": values["target_id"],
                "turn_number": sequence, "disclosure": "keep", "channel": "public", "target_role_id": ""})
            clues = [clue for clue in dm.get_role_clues(role_id) if clue["clue_id"] not in before_ids]
            return ActionOutcome(data={"clues": clues}, events=[event], code="OK" if clues else "NO_NEW_CLUE")
        if name == "share_clue":
            action = "public_speech" if values["scope"] == "public" else "whisper"
            dm._require_investigation_action(action)
            if values["scope"] == "private":
                self._require_other_role(role_id, values["target_role_id"])
            if values["mode"] == "distorted":
                validated = await self._validate_content(role_id, values["shared_content"], values["scope"])
                values["shared_content"] = validated
            shared = dm._disclose_clue(role_id=role_id, clue_id=values["clue_id"], mode=values["mode"],
                shared_content=values["shared_content"], scope=values["scope"], target_role_id=values["target_role_id"])
            visible = values["scope"] == "public" or values["target_role_id"] == state.human_player_role_id
            event = {"type": "agent_search_result", "actor_role_id": role_id, "actor_role_name": permission.role_name(role_id),
                "public_status": "shared" if values["scope"] == "public" else "shared_with_player" if visible else "private_exchange",
                "content": shared["content"] if visible else "", "summary": "角色分享了一条线索说法。" if visible else "角色进行了私下信息交换。",
                "channel":"private" if values['scope']=='private' and visible else 'public',
                "conversation_role_id":role_id if values['scope']=='private' and visible else None}
            return ActionOutcome(data={"published": shared}, events=[event])
        if name in {"public_exchange", "private_exchange"}:
            target = values["target_role_id"]
            self._require_other_role(role_id, target)
            channel = "public" if name == "public_exchange" else "private"
            content = await self._validate_content(role_id, values["content"], channel)
            plan = {"actor_role_id": role_id, "target_role_id": target, "channel": channel,
                    "turn_number": sequence, "actor_role_name": permission.role_name(role_id), "target_role_name": permission.role_name(target)}
            if channel == "public":
                dm._require_investigation_action("public_speech")
                events = await dm._run_autonomous_public_exchange(plan, content, False)
                if any(event.get("fallback") for event in events):
                    raise DomainActionError("MODEL_RESPONSE_FAILED", "角色回复未通过校验，本次交流未提交")
                return ActionOutcome(data={"channel": channel, "responses": events}, events=events)
            dm._require_investigation_action("whisper")
            if target == state.human_player_role_id:
                raise DomainActionError("HUMAN_CONSENT_REQUIRED", "角色 Agent 不能强制真人进入私聊")
            invitation = dm._build_agent_context(role_id=target, channel="private", purpose="whisper_invitation",
                instruction=f"[WHISPER_INVITATION]\n{permission.role_name(role_id)}邀请你私聊。你可自行拒绝。只回答 ACCEPT 或 REJECT。",
                instruction_source="private_invitation")
            answer, failed = await dm._call_agent(invitation)
            if failed:
                raise DomainActionError("INVITATION_MODEL_FAILED", "对方未能有效回复邀请")
            if answer.strip().upper() != "ACCEPT":
                return ActionOutcome(data={"accepted": False}, code="INVITATION_DECLINED")
            event = await dm._run_autonomous_private_exchange(plan, content, False)
            if event is None or event.get("fallback"):
                raise DomainActionError("MODEL_RESPONSE_FAILED", "私聊回复无效或阶段已经结束")
            event["summary"] = f"{permission.role_name(role_id)}与{permission.role_name(target)}进行了私下交流，正文仅对双方可见。"
            private = dm.agent_pool.get(role_id)._private_memory[-2:]
            return ActionOutcome(data={"accepted": True, "messages": [{"direction": entry["direction"], "content": entry["content"]} for entry in private]}, events=[event])
        raise DomainActionError("TOOL_FORBIDDEN", "未注册的角色工具")

    async def _validate_content(self, role_id: str, content: str, channel: str) -> str:
        context = self.dm._build_agent_context(role_id=role_id, channel=channel, purpose="tool_speech_validation",
            instruction="核对本次发言是否符合角色已知事实和阶段边界。", instruction_source="tool_speech_validation")
        validated, fallback = await self.dm._validate_agent_speech(context, channel=channel, response=content)
        if fallback:
            raise DomainActionError("CONTENT_REJECTED", "发言没有通过游戏信息边界校验")
        return validated

    def _require_other_role(self, actor: str, target: str | None) -> None:
        if target == actor or not target or not self.dm._require_permission().role_exists(target):
            raise DomainActionError("TARGET_FORBIDDEN", "目标不属于本场游戏的其他角色")

    async def dm_tool(self, name: str, args: ToolArguments) -> ActionOutcome:
        dm = self.dm
        state = dm._require_state()
        if name == 'present_script_section':
            section = args.model_dump()['section_id']
            allowed = {'briefing':'public_briefing','dm_hosting':'dm_hosting'}.get(state.scene_phase.value)
            if section!=allowed:
                raise DomainActionError('SECTION_FORBIDDEN','只可主持当前阶段的公开剧本段落')
            content = str(dm._stage_flow_config().get(section,'')).strip()
            if not content: raise DomainActionError('SECTION_EMPTY','当前幕未提供此公开段落')
            source = f'script:stage_{state.current_stage_num}:{section}'
            return ActionOutcome(data={'source_key':source,'content':content},events=[{'type':'dm_host_action','source_key':source,'content':content}])
        if name == "select_actor":
            role_id = args.model_dump()["role_id"]
            if state.scene_phase != ScenePhase.INVESTIGATION or role_id not in state.ai_role_ids:
                raise DomainActionError("ACTOR_FORBIDDEN", "只能选择调查阶段的角色 Agent")
            frame = execution_frame.get()
            if frame and frame.candidate_role_ids and role_id not in frame.candidate_role_ids:
                raise DomainActionError("ACTOR_NOT_SCHEDULED", "本次必须优先调度被点名或轮转到的候选角色")
            return ActionOutcome(data={"role_id": role_id})
        if name == "publish_task":
            task_id = args.model_dump()["task_id"]
            tasks = dm._stage_flow_config().get("public_tasks", [])
            task_ids = {f"stage:{state.current_stage_num}:task:{index}": text for index, text in enumerate(tasks)}
            if task_id not in task_ids or state.scene_phase not in {ScenePhase.BRIEFING, ScenePhase.INVESTIGATION}:
                raise DomainActionError("TASK_FORBIDDEN", "任务不属于当前幕的可发布内容")
            text = task_ids[task_id]
            # DM is a privileged publisher, not a fictional participant in the role roster.
            state.public_history.append({"role": "user", "content": "DM：" + text})
            for role_id in state.ai_role_ids:
                dm.agent_pool.get(role_id).remember_public_announcement(task_id, text)
            return ActionOutcome(data={"task_id": task_id}, events=[{"type": "dm_task_published", "content": text}])
        if name == "dispatch_stage_information":
            for role_id in state.ai_role_ids:
                dm.agent_pool.inject_info(role_id, dm._require_permission().current_stage_blocks(role_id, state.current_stage_num), state.current_stage_num)
            dm._record_intelligence_dispatch(state.current_stage_num)
            return ActionOutcome(data={"stage": state.current_stage_num}, events=[{"type": "dm_information_available", "stage": state.current_stage_num}])
        raise DomainActionError("TOOL_FORBIDDEN", "未注册的 DM 工具")
