from __future__ import annotations
import json
import time
from typing import Any
from agent.action import AgentAction, AgentActionError
from mechanics.search import SearchMechanic


class AutonomousRoles:
    async def run_autonomous_turn(self) -> list[dict[str, Any]]:
        state = self._require_state()
        plan = self.preview_autonomous_turn()
        if plan is None:
            return []

        state.autonomy_turn_count += 1
        state.autonomy_next_at = (
            time.time() + float(self._autonomy_config()["interval_seconds"])
        )
        plan, actor_speech, actor_fallback = await self._choose_autonomous_action(plan)
        if plan is None or self.investigation_seconds_remaining() == 0:
            return []
        if plan.get("action") == "search":
            return [await self._run_autonomous_search(plan)]
        if plan["channel"] == "private":
            exchange = await self._run_autonomous_private_exchange(plan, actor_speech, actor_fallback)
            return [exchange] if exchange else []
        return await self._run_autonomous_public_exchange(
            plan,
            actor_speech,
            actor_fallback,
        )

    async def _run_autonomous_search(
        self,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_investigation_action("search")
        state = self._require_state()
        permission = self._require_permission()
        actor_role_id = str(plan["actor_role_id"])
        actor_name = permission.role_name(actor_role_id)
        target_id = str(plan["search_target_id"])
        mechanic = self.mechanic_registry.get("search")
        if not isinstance(mechanic, SearchMechanic):
            raise ValueError("当前剧本未启用搜证")
        target = mechanic.targets.get(target_id, {})
        target_name = str(target.get("name", target_id or "未知地点"))
        result = await mechanic.on_role_action(
            state,
            actor_role_id,
            {"type": "search", "target_id": target_id},
        )
        clue = result.get("clue")
        search_event = self._build_observed_event(
            actor_role_id=actor_role_id,
            event_type="search",
            channel="public_action",
            content=f"前往{target_name}进行搜证。搜证结果仅由行动者和 DM 掌握。",
        )
        self._broadcast_observed_event(search_event, exclude=[actor_role_id])
        self._queue_activity(
            actor_role_id=actor_role_id,
            target_role_id=None,
            event_type="search",
            channel="action",
            summary=(
                f"{actor_name}搜查了{target_name}"
                + (f"，获得线索“{clue['content']}”" if clue else "，未获得新线索")
            ),
            details={
                "target_id": target_id,
                "target_name": target_name,
                "clue": clue,
                "message": result.get("message"),
                "autonomy_turn": plan["turn_number"],
            },
        )
        response: dict[str, Any] = {
            "type": "agent_search_result",
            "actor_role_id": actor_role_id,
            "actor_role_name": actor_name,
            "target_id": target_id,
            "target_name": target_name,
            "autonomy_turn": plan["turn_number"],
            "public_status": "private",
            "content": "",
            "summary": f"{actor_name}搜查了{target_name}，没有公开搜证结果。",
        }
        if not clue:
            response["summary"] = (
                f"{actor_name}搜查了{target_name}，"
                f"{result.get('message') or '没有取得新线索'}"
            )
            return response

        self.record_investigation_event("searches", actor_type="agent")
        self._register_acquired_clue(
            role_id=actor_role_id,
            clue=clue,
            target_id=target_id,
            target_name=target_name,
        )
        self._queue_notebook(
            role_id=actor_role_id,
            section="automatic",
            source_type="search",
            source_key=f"search:{clue['id']}",
            title=f"搜证 · {target_name}",
            content=str(clue["content"]),
        )

        disclosure = str(plan.get("disclosure") or "keep")
        shared_content = str(plan.get("shared_content") or "").strip()
        if disclosure == "distorted":
            if not shared_content:
                disclosure = "keep"
            else:
                disclosure_context = self._build_agent_context(
                    role_id=actor_role_id,
                    channel=str(plan.get("channel") or "public"),
                    purpose="clue_disclosure_validation",
                    instruction=(
                        "[CLUE_DISCLOSURE]\n"
                        "检查这条准备对外发布的线索说法是否符合当前幕信息边界。"
                        "只应使用你亲自取得的线索和当前已知信息。"
                    ),
                    instruction_source="dm_clue_disclosure",
                )
                validated, fallback = await self._validate_agent_speech(
                    disclosure_context,
                    channel="clue_disclosure",
                    response=shared_content,
                )
                if fallback:
                    disclosure = "keep"
                else:
                    shared_content = validated

        if disclosure in {"truthful", "distorted"}:
            scope = str(plan.get("channel") or "public")
            target_role_id = (
                str(plan["target_role_id"])
                if scope == "private"
                else None
            )
            published = self._disclose_clue(
                role_id=actor_role_id,
                clue_id=str(clue["id"]),
                mode=disclosure,
                shared_content=shared_content,
                scope=scope,
                target_role_id=target_role_id,
            )
            visible_to_human = (
                scope == "public"
                or target_role_id == state.human_player_role_id
            )
            response.update(
                {
                    "public_status": (
                        "shared"
                        if scope == "public"
                        else (
                            "shared_with_player"
                            if visible_to_human
                            else "private_exchange"
                        )
                    ),
                    "content": published["content"] if visible_to_human else "",
                    "target_role_id": target_role_id,
                    "target_role_name": (
                        permission.role_name(target_role_id)
                        if target_role_id
                        else None
                    ),
                    "summary": (
                        f"{actor_name}公开了一条搜证说法：{published['content']}"
                        if scope == "public"
                        else (
                            f"{actor_name}私下向你分享了一条搜证说法："
                            f"{published['content']}"
                            if visible_to_human
                            else f"{actor_name}搜证后与其他角色进行了私下交流。"
                        )
                    ),
                }
            )
        return response

    async def _run_autonomous_public_exchange(
        self,
        plan: dict[str, Any],
        actor_speech: str,
        actor_fallback: bool,
    ) -> list[dict[str, Any]]:
        self._require_investigation_action("public_speech")
        state = self._require_state()
        permission = self._require_permission()
        actor_role_id = str(plan["actor_role_id"])
        target_role_id = str(plan["target_role_id"])
        actor_name = permission.role_name(actor_role_id)
        target_name = permission.role_name(target_role_id)
        state.public_history.append(
            {"role": "assistant", "content": f"{actor_name}: {actor_speech}"}
        )
        actor_event = self._build_observed_event(
            actor_role_id=actor_role_id,
            event_type="autonomous_public_speech",
            channel="public",
            content=actor_speech,
        )
        self._broadcast_observed_event(actor_event, exclude=[actor_role_id])
        self.record_investigation_event("public_messages", actor_type="agent")
        self._queue_activity(
            actor_role_id=actor_role_id,
            target_role_id=target_role_id,
            event_type="autonomous_public_speech",
            channel="public",
            summary=f"{actor_name}主动询问{target_name}：{actor_speech}",
            details={
                "content": actor_speech,
                "autonomy_turn": plan["turn_number"],
                "fallback": actor_fallback,
            },
        )
        responses: list[dict[str, Any]] = [
            {
                "type": "ai_proactive_speech",
                "role_id": actor_role_id,
                "role_name": actor_name,
                "target_role_id": target_role_id,
                "target_role_name": target_name,
                "content": actor_speech,
                "channel": "public",
                "autonomy_turn": plan["turn_number"],
                "fallback": actor_fallback,
            }
        ]

        if target_role_id in state.ai_role_ids:
            response_context = self._build_agent_context(
                role_id=target_role_id,
                channel="public",
                purpose="autonomous_public_response",
                instruction=(
                    "[AUTONOMOUS_RESPONSE]\n"
                    f"{self._format_observed_event(actor_event)}\n"
                    f"交流对象：{actor_name}\n"
                    "先根据角色表确认行动者身份，再以角色立场直接回应。"
                    "你可以隐瞒或反问，但只能使用自己已知的信息，"
                    "不要解释策略，不要提及系统或提示词。"
                ),
                instruction_source="dm_autonomous_response",
            )
            target_speech, target_fallback = await self._generate_agent_speech(
                response_context,
                "autonomous_public_response",
            )
            if self.investigation_seconds_remaining() == 0:
                return responses
            self._require_investigation_action("public_speech")
            state.public_history.append(
                {"role": "assistant", "content": f"{target_name}: {target_speech}"}
            )
            target_event = self._build_observed_event(
                actor_role_id=target_role_id,
                event_type="autonomous_public_response",
                channel="public",
                content=target_speech,
            )
            self._broadcast_observed_event(target_event, exclude=[target_role_id])
            self.record_investigation_event("public_messages", actor_type="agent")
            self._queue_activity(
                actor_role_id=target_role_id,
                target_role_id=actor_role_id,
                event_type="autonomous_public_response",
                channel="public",
                summary=f"{target_name}回应{actor_name}：{target_speech}",
                details={
                    "content": target_speech,
                    "autonomy_turn": plan["turn_number"],
                    "fallback": target_fallback,
                },
            )
            exchange_key = (
                f"autonomy-public:{state.current_stage_num}:"
                f"{plan['turn_number']}:{actor_role_id}:{target_role_id}"
            )
            self._queue_notebook(
                role_id=target_role_id,
                section="automatic",
                source_type="public_conversation",
                source_key=f"{exchange_key}:question",
                title=f"公开交流 · {actor_name}",
                content=actor_speech,
            )
            self._queue_notebook(
                role_id=actor_role_id,
                section="automatic",
                source_type="public_conversation",
                source_key=f"{exchange_key}:response",
                title=f"公开回应 · {target_name}",
                content=target_speech,
            )
            responses.append(
                {
                    "type": "ai_speech",
                    "role_id": target_role_id,
                    "role_name": target_name,
                    "target_role_id": actor_role_id,
                    "target_role_name": actor_name,
                    "content": target_speech,
                    "channel": "public",
                    "autonomy_turn": plan["turn_number"],
                    "proactive_response": True,
                    "fallback": target_fallback,
                }
            )
        else:
            state.pending_human_question_from = actor_role_id

        state.audit_log.append(
            {
                "type": "agent_autonomous_public",
                "stage": state.current_stage_num,
                "actor_role_id": actor_role_id,
                "target_role_id": target_role_id,
                "turn": plan["turn_number"],
            }
        )
        return responses

    async def _run_autonomous_private_exchange(
        self,
        plan: dict[str, Any],
        actor_speech: str,
        actor_fallback: bool,
    ) -> dict[str, Any] | None:
        self._require_investigation_action("whisper")
        state = self._require_state()
        permission = self._require_permission()
        actor_role_id = str(plan["actor_role_id"])
        target_role_id = str(plan["target_role_id"])
        actor_name = permission.role_name(actor_role_id)
        target_name = permission.role_name(target_role_id)
        actor = self.agent_pool.get(actor_role_id)
        target = self.agent_pool.get(target_role_id)
        actor_event = self._build_observed_event(
            actor_role_id=actor_role_id,
            event_type="autonomous_private_speech",
            channel="private",
            content=actor_speech,
        )
        self._broadcast_observed_event(actor_event, recipients=[target_role_id])
        target_context = self._build_agent_context(
            role_id=target_role_id,
            channel="private",
            purpose="autonomous_private_response",
            public_limit=8,
            private_history=[
                {
                    "role": "user",
                    "content": self._format_observed_event(actor_event),
                }
            ],
            private_participants=[actor_role_id, target_role_id],
            instruction=(
                "[AUTONOMOUS_RESPONSE]\n"
                f"交流对象：{actor_name}\n"
                "先根据角色表确认行动者身份，再直接回应。"
                "你可以保留、误导或反问，但不能使用未知信息。"
            ),
            instruction_source="dm_autonomous_private_response",
        )
        target_speech, target_fallback = await self._generate_agent_speech(
            target_context,
            "autonomous_private_response",
        )
        if self.investigation_seconds_remaining() == 0:
            return None

        exchange_key = (
            f"autonomy-private:{state.current_stage_num}:"
            f"{plan['turn_number']}:{actor_role_id}:{target_role_id}"
        )
        actor.remember_private_exchange(
            state.current_stage_num,
            target_name,
            "sent",
            actor_speech,
            source_key=f"{exchange_key}:question", counterpart_role_id=target_role_id,
            phase=state.scene_phase.value,
        )
        target.remember_private_exchange(
            state.current_stage_num,
            actor_name,
            "received",
            actor_speech,
            source_key=f"{exchange_key}:question", counterpart_role_id=actor_role_id,
            phase=state.scene_phase.value,
        )
        target.remember_private_exchange(
            state.current_stage_num,
            actor_name,
            "sent",
            target_speech,
            source_key=f"{exchange_key}:response", counterpart_role_id=actor_role_id,
            phase=state.scene_phase.value,
        )
        actor.remember_private_exchange(
            state.current_stage_num,
            target_name,
            "received",
            target_speech,
            source_key=f"{exchange_key}:response", counterpart_role_id=target_role_id,
            phase=state.scene_phase.value,
        )
        target_event = self._build_observed_event(
            actor_role_id=target_role_id,
            event_type="autonomous_private_response",
            channel="private",
            content=target_speech,
        )
        self._broadcast_observed_event(target_event, recipients=[actor_role_id])
        self.record_investigation_event("whispers", actor_type="agent")
        self._queue_activity(
            actor_role_id=actor_role_id,
            target_role_id=target_role_id,
            event_type="autonomous_private_speech",
            channel="private",
            summary=f"{actor_name}私下询问{target_name}：{actor_speech}",
            details={
                "content": actor_speech,
                "autonomy_turn": plan["turn_number"],
                "fallback": actor_fallback,
            },
        )
        self._queue_activity(
            actor_role_id=target_role_id,
            target_role_id=actor_role_id,
            event_type="autonomous_private_response",
            channel="private",
            summary=f"{target_name}私下回应{actor_name}：{target_speech}",
            details={
                "content": target_speech,
                "autonomy_turn": plan["turn_number"],
                "fallback": target_fallback,
            },
        )
        exchange_key = (
            f"autonomy-private:{state.current_stage_num}:"
            f"{plan['turn_number']}:{actor_role_id}:{target_role_id}"
        )
        self._queue_notebook(
            role_id=target_role_id,
            section="automatic",
            source_type="private_conversation",
            source_key=f"{exchange_key}:question",
            title=f"私聊获得 · {actor_name}",
            content=actor_speech,
        )
        self._queue_notebook(
            role_id=actor_role_id,
            section="automatic",
            source_type="private_conversation",
            source_key=f"{exchange_key}:response",
            title=f"私聊获得 · {target_name}",
            content=target_speech,
        )
        state.audit_log.append(
            {
                "type": "agent_autonomous_private",
                "stage": state.current_stage_num,
                "actor_role_id": actor_role_id,
                "target_role_id": target_role_id,
                "actor_content": actor_speech,
                "target_content": target_speech,
                "turn": plan["turn_number"],
            }
        )
        return {
            "type": "agent_private_exchange",
            "actor_role_id": actor_role_id,
            "actor_role_name": actor_name,
            "target_role_id": target_role_id,
            "target_role_name": target_name,
            "channel": "private",
            "autonomy_turn": plan["turn_number"],
            "fallback": actor_fallback or target_fallback,
            "summary": (
                f"{actor_name}主动邀请{target_name}进行了私下交流。"
                "谈话内容仅对双方与 DM 可见。"
            ),
        }

    async def _choose_autonomous_action(
        self,
        fallback_plan: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str, bool]:
        state = self._require_state()
        permission = self._require_permission()
        actor_role_id = str(fallback_plan["actor_role_id"])
        actor = self.agent_pool.get(actor_role_id)
        candidate_ids = [
            role_id
            for role_id in [state.human_player_role_id, *state.ai_role_ids]
            if role_id != actor_role_id
        ]
        candidate_text = "\n".join(
            (
                f"- role_id={role_id}；角色={permission.role_name(role_id)}；"
                f"公开身份={permission.role_by_id(role_id)['public_identity']}；"
                f"操控者={'真人玩家' if role_id == state.human_player_role_id else '角色 Agent'}"
            )
            for role_id in candidate_ids
        )
        private_allowed = bool(self._autonomy_config()["allow_private"]) and (
            "whisper"
            in self._stage_flow_config()
            .get("investigation", {})
            .get("enabled_actions", self._default_enabled_actions())
        )
        enabled_actions = set(
            self._stage_flow_config()
            .get("investigation", {})
            .get("enabled_actions", self._default_enabled_actions())
        )
        allowed_channels = set()
        if "public_speech" in enabled_actions:
            allowed_channels.add("public")
        if private_allowed:
            allowed_channels.add("private")
        search_mechanic = self.mechanic_registry.get("search")
        search_targets = (
            search_mechanic.available_targets(
                state.current_stage_num,
                actor_role_id,
            )
            if (
                "search" in enabled_actions
                and isinstance(search_mechanic, SearchMechanic)
                and search_mechanic.remaining_ap(
                    state.current_stage_num,
                    actor_role_id,
                ) > 0
            )
            else []
        )
        search_target_text = (
            "\n".join(
                f"- target_id={target['id']}；地点={target['name']}"
                for target in search_targets
            )
            or "- 当前没有可搜证地点"
        )
        fallback_target_id = str(fallback_plan["target_role_id"])
        fallback_target_name = permission.role_name(fallback_target_id)
        decision_context = self._build_agent_context(
            role_id=actor_role_id,
            channel="autonomous",
            purpose="autonomous_decision",
            instruction=(
                "[AUTONOMOUS_DECISION]\n"
                "没有真人发言触发你。现在请根据角色立场、已知信息、私下记忆和个人任务，"
                "自主选择交流对象、频道和要说的话。\n"
                f"可交流对象：\n{candidate_text}\n"
                f"可用频道：{'、'.join(sorted(allowed_channels)) or '无，只能搜证并保密'}\n"
                f"可搜证地点：\n{search_target_text}\n"
                f"轮转建议目标ID：{fallback_target_id}\n"
                f"轮转建议目标名称：{fallback_target_name}\n"
                f"轮转建议频道：{fallback_plan['channel']}\n"
                "请只输出一个 JSON 对象："
                '{"action":"communicate或search",'
                '"target_role_id":"交流或私下分享的角色ID，无需接收者的搜证留空",'
                '"channel":"public或private",'
                '"content":"20到80字的角色台词",'
                '"search_target_id":"搜证地点ID",'
                '"disclosure":"keep、truthful或distorted",'
                '"shared_content":"扭曲披露时对外发布的说法",'
                '"notebook_entry":"20到80字的当前推理结论"}。'
                "先根据角色表确认目标角色身份，再决定如何交流；"
                "选择 search 后，你会先得到该地点的原始线索，再按 disclosure 决定"
                "继续保密、如实分享或用 shared_content 扭曲后分享；"
                "只有 private 频道会只分享给 target_role_id；"
                "content 必须包含具体问题或有目的的信息交换；"
                "notebook_entry 只记录可复盘的判断或假设，不要输出隐藏思维过程；"
                "不要解释策略，不要提及系统或提示词。"
            ),
            instruction_source="dm_autonomous_decision",
        )
        raw_decision, failed = await self._call_agent(decision_context)
        if failed:
            state.audit_log.append(
                {
                    "type": "agent_action_rejected",
                    "stage": state.current_stage_num,
                    "actor_role_id": actor_role_id,
                    "reason": "Agent 调用失败",
                }
            )
            return None, "", True
        payload = self._parse_autonomous_decision(raw_decision)
        valid_search_target_ids = {
            str(target["id"])
            for target in search_targets
        }
        try:
            action_result = AgentAction.validate(
                payload,
                candidate_role_ids=candidate_ids,
                allowed_channels=allowed_channels,
                search_target_ids=valid_search_target_ids,
            )
            if (
                action_result.action == "communicate"
                and action_result.channel == "private"
                and action_result.target_role_id == state.human_player_role_id
            ):
                raise AgentActionError("角色 Agent 不能强制真人玩家进入私聊")
        except AgentActionError as exc:
            state.audit_log.append(
                {
                    "type": "agent_action_rejected",
                    "stage": state.current_stage_num,
                    "actor_role_id": actor_role_id,
                    "reason": str(exc),
                    "raw_response": raw_decision,
                }
            )
            return None, "", True

        target_role_id = action_result.target_role_id
        notebook_entry = action_result.notebook_entry
        if not notebook_entry:
            if action_result.action == "search":
                notebook_entry = "需要先取得现场证据，再决定是否以及如何向其他角色披露。"
            else:
                notebook_entry = (
                    f"当前需要向{permission.role_name(target_role_id)}核对信息，"
                    "再判断其证词与我的任务是否冲突。"
                )
        actor.remember_reasoning_note(state.current_stage_num, notebook_entry,
            source_key=f"agent-reasoning:{state.current_stage_num}:{fallback_plan['turn_number']}:{actor_role_id}",
            phase=state.scene_phase.value)
        self._queue_notebook(
            role_id=actor_role_id,
            section="reasoning",
            source_type="agent_hypothesis",
            source_key=(
                f"agent-reasoning:{state.current_stage_num}:"
                f"{fallback_plan['turn_number']}:{actor_role_id}"
            ),
            title=f"第 {state.current_stage_num} 幕 · 行动前判断",
            content=notebook_entry,
        )

        plan = {
            **fallback_plan,
            "action": action_result.action,
            "target_role_id": target_role_id,
            "target_role_name": permission.role_name(target_role_id) if target_role_id else "",
            "channel": action_result.channel,
            "search_target_id": action_result.search_target_id,
            "disclosure": action_result.disclosure,
            "shared_content": action_result.shared_content,
            "notebook_entry": notebook_entry,
        }
        if action_result.action == "search":
            return plan, "", False

        validated, fallback = await self._validate_agent_speech(
            decision_context,
            channel=f"autonomous_{action_result.channel}",
            response=action_result.content,
        )
        return plan, validated, fallback

    @staticmethod
    def _parse_autonomous_decision(raw: str) -> dict[str, Any]:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
