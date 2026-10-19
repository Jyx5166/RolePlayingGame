from __future__ import annotations
from typing import Any
from domain.state import GamePhase, ScenePhase


class PlayerActions:
    async def handle_human_speech(self, content: str) -> dict[str, Any]:
        state = self._require_state()
        self._require_investigation_action("public_speech")
        permission = self._require_permission()
        validator = self._require_validator()
        result = validator.validate_human_speech(state.human_player_role_id, state.current_stage_num, content)
        role_name = permission.role_name(state.human_player_role_id)
        state.public_history.append({"role": "user", "content": f"{role_name}: {content}"})
        event = self._build_observed_event(
            actor_role_id=state.human_player_role_id,
            event_type="public_speech",
            channel="public",
            content=content,
        )
        self._broadcast_observed_event(event)
        self._queue_activity(
            actor_role_id=state.human_player_role_id,
            target_role_id=None,
            event_type="public_speech",
            channel="public",
            summary=f"{role_name}公开发言：{content}",
            details={"content": content},
        )
        response = {
            "role_id": state.human_player_role_id,
            "role_name": role_name,
            "public_identity": permission.role_by_id(
                state.human_player_role_id
            )["public_identity"],
            "event_type": "public_speech",
            "channel": "public",
            "stage": state.current_stage_num,
            "content": content,
        }
        if result.message:
            response["warning"] = result.message
        self.record_investigation_event("public_messages")
        return response

    async def schedule_ai_turns(self, trigger_context: dict[str, str]) -> list[dict[str, Any]]:
        state = self._require_state()
        turn_mgr = self._require_turn_manager()
        mentioned = turn_mgr.mentioned_speakers(
            trigger_context.get("content", ""),
            state.ai_role_ids,
        )
        if state.pending_human_question_from and not mentioned:
            speakers = [state.pending_human_question_from]
        else:
            speakers = await turn_mgr.determine_speakers(
                state.ai_role_ids,
                state.public_history,
                trigger_context,
            )
        state.pending_human_question_from = None
        replies: list[dict[str, Any]] = []
        for role_id in speakers:
            if self.investigation_seconds_remaining() == 0:
                break
            reply = await self._process_ai_speech(role_id, trigger_context)
            if reply["content"]:
                replies.append(reply)
        return replies

    async def handle_mechanic_action(self, action: dict[str, Any]) -> dict[str, Any]:
        state = self._require_state()
        permission = self._require_permission()
        mechanic_type = action.get("type")
        self._require_investigation_action(str(mechanic_type))
        mechanic = self.mechanic_registry.get(mechanic_type)
        result = await mechanic.on_player_action(state, action)
        if mechanic_type == "search":
            human_role_id = state.human_player_role_id
            role_name = permission.role_name(human_role_id)
            target_id = str(action.get("target_id", ""))
            target = getattr(mechanic, "targets", {}).get(target_id, {})
            target_name = str(target.get("name", target_id or "未知地点"))
            result.update(
                {
                    "actor_role_id": human_role_id,
                    "actor_role_name": role_name,
                    "target_id": target_id,
                    "target_name": target_name,
                    "stage": state.current_stage_num,
                }
            )
            event = self._build_observed_event(
                actor_role_id=human_role_id,
                event_type="search",
                channel="public_action",
                content=f"前往{target_name}进行搜证。搜证结果仅由行动者和 DM 掌握。",
            )
            self._broadcast_observed_event(event)
            clue = result.get("clue")
            self._queue_activity(
                actor_role_id=human_role_id,
                target_role_id=None,
                event_type="search",
                channel="action",
                summary=(
                    f"{role_name}搜查了{target_name}"
                    + (f"，获得线索“{clue['content']}”" if clue else "，未获得新线索")
                ),
                details={
                    "target_id": target_id,
                    "target_name": target_name,
                    "clue": clue,
                    "message": result.get("message"),
                },
            )
            if clue:
                self.record_investigation_event("searches")
                self._register_acquired_clue(
                    role_id=human_role_id,
                    clue=clue,
                    target_id=target_id,
                    target_name=target_name,
                )
                self._queue_notebook(
                    role_id=human_role_id,
                    section="automatic",
                    source_type="search",
                    source_key=f"search:{clue['id']}",
                    title=f"搜证 · {target_name}",
                    content=str(clue["content"]),
                )
        return result

    def handle_clue_disclosure(self, action: dict[str, Any]) -> dict[str, Any]:
        state = self._require_state()
        role_id = state.human_player_role_id
        scope = str(action.get("scope") or "public")
        target_role_id = (
            str(action["target_role_id"])
            if action.get("target_role_id")
            else None
        )
        if scope == "public":
            self._require_investigation_action("public_speech")
        elif scope == "private":
            self._require_investigation_action("whisper")
            active_target = self.get_whisper_status().get("active_target_role_id")
            if not active_target or target_role_id != active_target:
                raise ValueError("请先与目标角色建立私聊，再向其分享线索")
        else:
            raise ValueError("未知的线索分享范围")

        disclosure = self._disclose_clue(
            role_id=role_id,
            clue_id=str(action.get("clue_id") or ""),
            mode=str(action.get("mode") or ""),
            shared_content=str(action.get("content") or ""),
            scope=scope,
            target_role_id=target_role_id,
        )
        return {
            "type": "clue_disclosed",
            **disclosure,
            "owner_view_mode": disclosure["disclosure_mode"],
        }

    async def handle_whisper_action(self, action: dict[str, Any]) -> dict[str, Any]:
        state = self._require_state()
        self._require_investigation_action("whisper")
        permission = self._require_permission()
        mechanic = self.mechanic_registry.get("whisper")
        result = await mechanic.on_player_action(state, action)
        if result.get("type") == "whisper_pending":
            target_role_id = result["target_role_id"]
            inviter_name = permission.role_name(state.human_player_role_id)
            inviter_role = permission.role_by_id(state.human_player_role_id)
            invitation_event = self._build_observed_event(
                actor_role_id=state.human_player_role_id,
                event_type="whisper_invitation",
                channel="private",
                content=f"{inviter_name}邀请你进行私聊。",
            )
            self._broadcast_observed_event(
                invitation_event,
                recipients=[target_role_id],
            )
            context = self._build_agent_context(
                role_id=target_role_id,
                channel="private",
                purpose="whisper_invitation",
                public_limit=8,
                private_history=[
                    {
                        "role": "user",
                        "content": self._format_observed_event(invitation_event),
                    }
                ],
                private_participants=[
                    state.human_player_role_id,
                    target_role_id,
                ],
                instruction=(
                    "[WHISPER_INVITATION]\n"
                    f"角色 {inviter_name}（role_id={state.human_player_role_id}；"
                    f"公开身份={inviter_role['public_identity']}）邀请你私聊。"
                    "请根据当前角色立场决定是否接受，只回答 ACCEPT 或 DECLINE。"
                ),
                instruction_source="dm_whisper_invitation",
            )
            decision, failed = await self._call_agent(context)
            normalized = decision.upper()
            accepted = (
                not failed
                and (
                    normalized.startswith("ACCEPT")
                    or normalized.startswith("接受")
                )
            )
            result = mechanic.resolve_invitation(state, target_role_id, accepted)

        target_role_id = result.get("target_role_id")
        if target_role_id:
            result["target_role_name"] = permission.role_name(target_role_id)
            self._queue_activity(
                actor_role_id=state.human_player_role_id,
                target_role_id=str(target_role_id),
                event_type=str(result.get("type", "whisper_invitation")),
                channel="private",
                summary=(
                    f"{permission.role_name(state.human_player_role_id)}邀请"
                    f"{permission.role_name(str(target_role_id))}私聊："
                    + (
                        "对方接受"
                        if result.get("type") == "whisper_accepted"
                        else "对方拒绝或会话结束"
                    )
                ),
                details={"result": dict(result)},
            )
        if result.get("type") == "whisper_accepted":
            self.record_investigation_event("whispers")
        return result

    async def handle_whisper_speech(self, content: str) -> list[dict[str, Any]]:
        state = self._require_state()
        self._require_investigation_action("whisper")
        permission = self._require_permission()
        validator = self._require_validator()
        mechanic = self.mechanic_registry.get("whisper")
        target_role_id = mechanic.active_target_role_id
        if target_role_id is None:
            raise ValueError("请先邀请一个角色进入私聊")

        normalized = content.strip()
        if not normalized:
            raise ValueError("私聊内容不能为空")

        human_role_id = state.human_player_role_id
        human_name = permission.role_name(human_role_id)
        target_name = permission.role_name(target_role_id)
        validation = validator.validate_human_speech(
            human_role_id,
            state.current_stage_num,
            normalized,
        )
        human_event = self._build_observed_event(
            actor_role_id=human_role_id,
            event_type="private_speech",
            channel="private",
            content=normalized,
        )
        self._broadcast_observed_event(human_event, recipients=[target_role_id])
        mechanic.record_message(
            state,
            human_role_id,
            target_role_id,
            "user",
            f"{human_name}（私聊）: {normalized}",
        )
        responses: list[dict[str, Any]] = [
            {
                "type": "whisper_message",
                "sender_type": "player",
                "sender_role_id": human_role_id,
                "sender_role_name": human_name,
                "conversation_role_id": target_role_id,
                "conversation_role_name": target_name,
                "content": normalized,
            }
        ]
        if validation.message:
            responses.append(
                {
                    "type": "speech_warning",
                    "channel": "whisper",
                    "message": validation.message,
                }
            )

        context = self._build_agent_context(
            role_id=target_role_id,
            channel="private",
            purpose="whisper_response",
            public_limit=8,
            private_history=mechanic.conversation_messages(target_role_id),
            private_participants=[human_role_id, target_role_id],
            instruction=(
                self._format_observed_event(human_event)
                + "\n请先确认行动者身份，再以你的角色立场私下回应。"
            ),
            instruction_source="dm_whisper_response",
        )
        exchange_key = self._next_record_key("human-whisper")
        self._queue_activity(
            actor_role_id=human_role_id, target_role_id=target_role_id,
            event_type="private_speech", channel="private",
            summary=f"{human_name}私下向{target_name}发言：{normalized}", details={"content": normalized},
        )
        self._queue_notebook(
            role_id=target_role_id, section="automatic", source_type="private_conversation",
            source_key=f"{exchange_key}:received", title=f"私聊获得 · {human_name}", content=normalized,
        )
        target_agent = self.agent_pool.get(target_role_id)
        target_agent.remember_private_exchange(state.current_stage_num, human_name, "received", normalized,
                                               source_key=f"{exchange_key}:received", counterpart_role_id=human_role_id,
                                               phase=state.scene_phase.value)
        response, fallback = await self._generate_agent_speech(context, "whisper")
        if self.investigation_seconds_remaining() == 0:
            return responses
        mechanic.record_message(
            state,
            target_role_id,
            target_role_id,
            "assistant",
            f"{target_name}（私聊）: {response}",
        )
        agent_response: dict[str, Any] = {
            "type": "whisper_message",
            "sender_type": "agent",
            "sender_role_id": target_role_id,
            "sender_role_name": target_name,
            "conversation_role_id": target_role_id,
            "conversation_role_name": target_name,
            "content": response,
        }
        if fallback:
            agent_response["fallback"] = True
        responses.append(agent_response)
        target_agent.remember_private_exchange(
            state.current_stage_num,
            human_name,
            "sent",
            response,
            source_key=f"{exchange_key}:response", counterpart_role_id=human_role_id,
            phase=state.scene_phase.value,
        )
        self._queue_activity(
            actor_role_id=target_role_id,
            target_role_id=human_role_id,
            event_type="private_response",
            channel="private",
            summary=f"{target_name}私下回应{human_name}：{response}",
            details={"content": response, "fallback": fallback},
        )
        self._queue_notebook(
            role_id=human_role_id,
            section="automatic",
            source_type="private_conversation",
            source_key=f"{exchange_key}:response",
            title=f"私聊获得 · {target_name}",
            content=response,
        )
        return responses

    async def run_replay(self) -> dict[str, Any]:
        state = self._require_state()
        replay = self.get_replay()
        state.phase = GamePhase.REPLAY
        self._set_scene_phase(ScenePhase.REPLAY)
        return replay

    def get_replay(self) -> dict[str, Any]:
        state = self._require_state()
        final_resolution = state.stage_resolutions.get(state.total_stages, {})
        vote = final_resolution.get("vote")
        if self.uses_scene_flow():
            if state.current_stage_num != state.total_stages or not final_resolution.get("resolved") or not isinstance(vote, dict) or vote.get("pending") or not str(vote.get("outcome_text", "")).strip():
                raise ValueError("最终决定尚未完成，不能进入终局")
            vote = self.get_stage_resolution()["vote"]
        final_decision = (
            dict(vote)
            if isinstance(vote, dict)
            and vote.get("kind") == "final"
            and not vote.get("pending", False)
            else None
        )
        return self.replay_engine.build(
            self._require_script(),
            state.public_history,
            final_decision=final_decision,
        )

    async def _process_ai_speech(
        self,
        role_id: str,
        trigger_context: dict[str, str],
    ) -> dict[str, Any]:
        self._require_investigation_action("public_speech")
        state = self._require_state()
        permission = self._require_permission()
        actor_role_id = str(
            trigger_context.get("role_id", state.human_player_role_id)
        )
        observed_event = self._build_observed_event(
            actor_role_id=actor_role_id,
            event_type=str(trigger_context.get("event_type", "public_speech")),
            channel=str(trigger_context.get("channel", "public")),
            content=str(trigger_context.get("content", "")),
        )
        response_context = self._build_agent_context(
            role_id=role_id,
            channel="public",
            purpose="public_response",
            instruction=(
                self._format_observed_event(observed_event)
                + "\n先根据角色表确认行动者身份，再从你的角色立场回应。"
                "不要复述身份识别过程。"
            ),
            instruction_source="dm_public_response",
        )
        response, fallback = await self._generate_agent_speech(
            response_context,
            "public",
        )
        role_name = permission.role_name(role_id)
        if self.investigation_seconds_remaining() == 0:
            return {"role_id": role_id, "role_name": role_name, "content": "", "fallback": True}
        self._require_investigation_action("public_speech")
        state.public_history.append({"role": "assistant", "content": f"{role_name}: {response}"})
        response_event = self._build_observed_event(
            actor_role_id=role_id,
            event_type="public_response",
            channel="public",
            content=response,
        )
        self._broadcast_observed_event(response_event, exclude=[role_id])
        self._queue_activity(
            actor_role_id=role_id,
            target_role_id=actor_role_id,
            event_type="public_response",
            channel="public",
            summary=(
                f"{role_name}回应{permission.role_name(actor_role_id)}：{response}"
            ),
            details={
                "content": response,
                "trigger": dict(trigger_context),
                "fallback": fallback,
            },
        )
        exchange_key = self._next_record_key("public-response")
        self._queue_notebook(
            role_id=role_id,
            section="automatic",
            source_type="public_conversation",
            source_key=f"{exchange_key}:heard",
            title=f"公开交流 · {permission.role_name(actor_role_id)}",
            content=str(trigger_context.get("content", "")),
        )
        if actor_role_id == state.human_player_role_id:
            self._queue_notebook(
                role_id=actor_role_id,
                section="automatic",
                source_type="public_conversation",
                source_key=f"{exchange_key}:response",
                title=f"公开回应 · {role_name}",
                content=response,
            )
        result: dict[str, Any] = {
            "role_id": role_id,
            "role_name": role_name,
            "target_role_id": actor_role_id,
            "target_role_name": permission.role_name(actor_role_id),
            "event_type": "public_response",
            "channel": "public",
            "stage": state.current_stage_num,
            "content": response,
        }
        if fallback:
            result["fallback"] = True
        return result

    def _register_acquired_clue(
        self,
        *,
        role_id: str,
        clue: dict[str, Any],
        target_id: str,
        target_name: str,
    ) -> dict[str, Any]:
        state = self._require_state()
        clue_id = str(clue["id"])
        existing = state.role_clues.setdefault(role_id, {}).get(clue_id)
        if existing is not None:
            return existing
        record = {
            "role_id": role_id,
            "clue_id": clue_id,
            "stage": state.current_stage_num,
            "target_id": target_id,
            "target_name": target_name,
            "truth_content": str(clue["content"]).strip(),
            "disclosure_mode": "private",
            "shared_content": "",
            "shared_scope": "",
            "target_role_id": None,
        }
        state.role_clues[role_id][clue_id] = record
        if role_id in state.ai_role_ids:
            self.agent_pool.remember_clue(
                role_id,
                clue_id=clue_id,
                stage=state.current_stage_num,
                target_name=target_name,
                truth_content=record["truth_content"],
            )
        self._queue_clue(record)
        return record

    def _disclose_clue(
        self,
        *,
        role_id: str,
        clue_id: str,
        mode: str,
        shared_content: str,
        scope: str,
        target_role_id: str | None,
    ) -> dict[str, Any]:
        state = self._require_state()
        permission = self._require_permission()
        clue = state.role_clues.get(role_id, {}).get(clue_id)
        if clue is None:
            raise ValueError("你并未持有这条线索")
        if mode not in {"truthful", "distorted"}:
            raise ValueError("请选择如实分享或改写后分享")
        if scope not in {"public", "private"}:
            raise ValueError("未知的线索分享范围")
        if scope == "private":
            if (
                target_role_id is None
                or target_role_id == role_id
                or not permission.role_exists(target_role_id)
            ):
                raise ValueError("请选择有效的私下分享对象")
            recipients = [target_role_id]
        else:
            target_role_id = None
            recipients = [
                candidate
                for candidate in [
                    state.human_player_role_id,
                    *state.ai_role_ids,
                ]
                if candidate != role_id
            ]

        truth_content = str(clue["truth_content"])
        claim = truth_content if mode == "truthful" else shared_content.strip()
        if mode == "distorted":
            if len(claim) < 2 or len(claim) > 300:
                raise ValueError("改写后的线索说法需要在 2 到 300 个字符之间")
            if claim == truth_content:
                mode = "truthful"

        actor_name = permission.role_name(role_id)
        clue.update(
            {
                "disclosure_mode": mode,
                "shared_content": claim,
                "shared_scope": scope,
                "target_role_id": target_role_id,
            }
        )
        if role_id in state.ai_role_ids:
            self.agent_pool.get(role_id).update_clue_disclosure(
                clue_id,
                mode,
                claim,
            )

        event = self._build_observed_event(
            actor_role_id=role_id,
            event_type="clue_claim",
            channel=scope,
            content=claim,
        )
        agent_recipients = [
            recipient
            for recipient in recipients
            if recipient in state.ai_role_ids
        ]
        self._broadcast_observed_event(event, recipients=agent_recipients)
        if scope == "public":
            state.public_history.append(
                {"role": "assistant", "content": f"{actor_name}: {claim}"}
            )
            self.record_investigation_event(
                "public_messages",
                actor_type=(
                    "human"
                    if role_id == state.human_player_role_id
                    else "agent"
                ),
            )
        else:
            self.record_investigation_event(
                "whispers",
                actor_type=(
                    "human"
                    if role_id == state.human_player_role_id
                    else "agent"
                ),
            )

        record_key = self._next_record_key("clue-claim")
        for recipient in recipients:
            self._queue_notebook(
                role_id=recipient,
                section="automatic",
                source_type="clue_claim",
                source_key=f"{record_key}:{recipient}",
                title=(
                    f"公开线索声明 · {actor_name}"
                    if scope == "public"
                    else f"私下线索声明 · {actor_name}"
                ),
                content=claim,
            )
        self._queue_activity(
            actor_role_id=role_id,
            target_role_id=target_role_id,
            event_type="clue_disclosure",
            channel=scope,
            summary=(
                f"{actor_name}公开分享线索说法：{claim}"
                if scope == "public"
                else (
                    f"{actor_name}向{permission.role_name(target_role_id or '')}"
                    f"私下分享线索说法：{claim}"
                )
            ),
            details={
                "clue_id": clue_id,
                "truth_content": truth_content,
                "disclosure_mode": mode,
                "shared_content": claim,
                "shared_scope": scope,
                "target_role_id": target_role_id,
            },
        )
        self._queue_clue(clue)
        state.audit_log.append(
            {
                "type": "clue_disclosure",
                "stage": state.current_stage_num,
                "actor_role_id": role_id,
                "target_role_id": target_role_id,
                "clue_id": clue_id,
                "truth_content": truth_content,
                "disclosure_mode": mode,
                "shared_content": claim,
                "scope": scope,
            }
        )
        return {
            "clue_id": clue_id,
            "actor_role_id": role_id,
            "actor_role_name": actor_name,
            "target_role_id": target_role_id,
            "target_role_name": (
                permission.role_name(target_role_id)
                if target_role_id
                else None
            ),
            "channel": scope,
            "content": claim,
            "disclosure_mode": mode,
        }
