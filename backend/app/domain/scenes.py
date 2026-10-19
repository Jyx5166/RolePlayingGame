from __future__ import annotations
import asyncio
import math
import time
from typing import Any
from mechanics.whisper import WhisperMechanic
from domain.state import GamePhase, ScenePhase, GameState


class SceneRules:
    @staticmethod
    def has_scene_flow(script: dict[str, Any]) -> bool:
        return bool(script.get("stage_flow"))

    def uses_scene_flow(self) -> bool:
        return self.has_scene_flow(self._require_script())

    def has_opening(self) -> bool:
        return bool(self._require_script().get("opening"))

    def get_scene_summary(self) -> dict[str, Any]:
        state = self._require_state()
        config = self._stage_flow_config()
        investigation = config.get("investigation", {})
        has_opening = self.has_opening()
        before_first_stage = has_opening and state.current_stage_num == 1 and state.scene_phase in {
            ScenePhase.OPENING, ScenePhase.PRIVATE_REVEAL,
        }
        duration = 0 if before_first_stage else max(0, int(investigation.get("duration_seconds", 0)))
        enabled_actions = (
            []
            if before_first_stage or state.scene_phase == ScenePhase.REPLAY
            else list(investigation.get("enabled_actions", self._default_enabled_actions()))
        )
        stage_title = config.get("title", f"第 {state.current_stage_num} 幕")
        if before_first_stage:
            stage_title = self._require_script()["opening"]["title"] if state.scene_phase == ScenePhase.OPENING else "角色剧本"
        return {
            "phase": state.scene_phase.value,
            "phase_label": {
                ScenePhase.OPENING: "剧本开幕",
                ScenePhase.BRIEFING: "DM 开场",
                ScenePhase.PRIVATE_REVEAL: "个人剧本",
                ScenePhase.INVESTIGATION: "自由调查",
                ScenePhase.DM_HOSTING: "DM 主持",
                ScenePhase.REPLAY: "终局复盘",
            }[state.scene_phase],
            "stage": state.current_stage_num,
            "total_stages": state.total_stages,
            "stage_title": stage_title,
            "has_opening": has_opening,
            "before_first_stage": before_first_stage,
            "continue_label": self._scene_continue_label(),
            "public_tasks": [] if before_first_stage else list(config.get("public_tasks", [])),
            "enabled_actions": enabled_actions,
            "duration_seconds": duration,
            "remaining_seconds": self.investigation_seconds_remaining(),
            "can_manual_end": (
                state.scene_phase == ScenePhase.INVESTIGATION
                and bool(investigation.get("allow_manual_end", True))
            ),
            "end_condition_text": "" if before_first_stage else self._end_condition_text(investigation.get("end_conditions", {})),
            "end_condition": self.investigation_condition_status(),
            "autonomy": self.get_autonomy_status(),
            "resolution": (
                self.get_stage_resolution()
                if state.scene_phase in {ScenePhase.DM_HOSTING, ScenePhase.REPLAY}
                else None
            ),
            "player_penalties": self._role_penalties_for_stage(
                state.human_player_role_id,
                state.current_stage_num,
            ),
        }

    def _scene_continue_label(self) -> str:
        state = self._require_state()
        if state.scene_phase == ScenePhase.OPENING:
            return "接收角色剧本"
        if state.scene_phase == ScenePhase.PRIVATE_REVEAL:
            return "开始第一幕" if self.has_opening() and state.current_stage_num == 1 else "我已阅读，进入调查"
        if state.scene_phase == ScenePhase.BRIEFING:
            return "开始调查" if self.has_opening() and state.current_stage_num == 1 else "接收我的角色剧本"
        if self.stage_resolution_pending():
            return "完成最终指认后查看结局" if state.current_stage_num >= state.total_stages else "完成本幕投票后继续"
        return "查看终局复盘" if state.current_stage_num >= state.total_stages else "进入下一幕"

    def get_opening_narration(self) -> str:
        return str(self._require_script().get("opening", {}).get("content", "")).strip()

    def get_briefing_narration(self) -> str:
        state = self._require_state()
        script = self._require_script()
        config = self._stage_flow_config()
        parts: list[str] = []
        if state.current_stage_num == 1 and not self.has_opening():
            parts.append(str(script.get("story_background", "")).strip())
        parts.append(str(config.get("public_briefing", "")).strip())
        return "\n\n".join(part for part in parts if part)

    def get_hosting_narration(self) -> str:
        state = self._require_state()
        config = self._stage_flow_config()
        configured = str(config.get("dm_hosting", "")).strip()
        if configured:
            return configured
        timeline = self._require_script().get("truth", {}).get("complete_timeline", {})
        return str(timeline.get(f"stage_{state.current_stage_num}", "DM 正在整理本幕的调查结果。"))

    def get_private_assignment(self) -> dict[str, Any]:
        state = self._require_state()
        permission = self._require_permission()
        role = permission.role_by_id(state.human_player_role_id)
        task = self._script_personal_task(self._require_script(), role, state.current_stage_num)
        task = self._task_with_penalties(
            state.human_player_role_id,
            str(task),
            state.current_stage_num,
        )
        private_blocks = [
            block
            for block in permission.current_stage_blocks(
                state.human_player_role_id,
                state.current_stage_num,
            )
            if block.get("visibility") != "public"
        ]
        return {
            "role_id": state.human_player_role_id,
            "role_name": role["role_name"],
            "public_identity": role["public_identity"],
            "personal_task": task,
            "blocks": private_blocks,
        }

    def get_autonomy_status(self) -> dict[str, Any]:
        state = self._require_state()
        config = self._autonomy_config()
        enabled = (
            bool(config["enabled"])
            and state.scene_phase == ScenePhase.INVESTIGATION
            and bool(state.ai_role_ids)
            and state.autonomy_turn_count < int(config["max_turns"])
        )
        return {
            "enabled": enabled,
            "turns_completed": state.autonomy_turn_count,
            "max_turns": int(config["max_turns"]),
            "next_action_seconds": (
                int(math.ceil(self.autonomy_seconds_until_next() or 0))
                if enabled
                else None
            ),
            "allow_private": bool(config["allow_private"]),
        }

    def autonomy_seconds_until_next(self) -> float | None:
        state = self._require_state()
        config = self._autonomy_config()
        if (
            state.scene_phase != ScenePhase.INVESTIGATION
            or not config["enabled"]
            or not state.ai_role_ids
            or state.autonomy_turn_count >= int(config["max_turns"])
            or state.autonomy_next_at is None
        ):
            return None
        return max(0.0, state.autonomy_next_at - time.time())

    def preview_autonomous_turn(self) -> dict[str, Any] | None:
        remaining = self.autonomy_seconds_until_next()
        if remaining is None or remaining > 0:
            return None
        state = self._require_state()
        permission = self._require_permission()
        config = self._autonomy_config()
        enabled_actions = set(
            self._stage_flow_config()
            .get("investigation", {})
            .get("enabled_actions", self._default_enabled_actions())
        )
        plan = self._require_turn_manager().plan_autonomous_turn(
            turn_number=state.autonomy_turn_count,
            stage=state.current_stage_num,
            ai_role_ids=state.ai_role_ids,
            human_role_id=state.human_player_role_id,
            allow_private=bool(config["allow_private"]) and "whisper" in enabled_actions,
        )
        if plan is None:
            return None
        actor_role_id = str(plan["actor_role_id"])
        target_role_id = str(plan["target_role_id"])
        return {
            **plan,
            "actor_role_name": permission.role_name(actor_role_id),
            "target_role_name": permission.role_name(target_role_id),
        }

    async def advance_stage(self) -> GameState:
        state = self._require_state()
        permission = self._require_permission()
        if state.current_stage_num >= state.total_stages:
            state.phase = GamePhase.FINALE
            return state

        state.current_stage_num += 1
        for role_id in state.ai_role_ids:
            role = permission.role_by_id(role_id)
            info = permission.current_stage_blocks(role_id, state.current_stage_num)
            self.agent_pool.inject_info(role_id, info, state.current_stage_num)
            self.agent_pool.set_objective(
                role_id,
                state.current_stage_num,
                self._task_with_penalties(
                    role_id,
                    self._script_personal_task(
                        self._require_script(),
                        role,
                        state.current_stage_num,
                    ),
                    state.current_stage_num,
                ),
            )
        self._record_intelligence_dispatch(state.current_stage_num)
        for mechanic in self.mechanic_registry.active():
            await mechanic.on_stage_advance(state, state.current_stage_num)
        self._apply_stage_penalties(state.current_stage_num)
        return state

    async def advance_scene_phase(self) -> dict[str, Any]:
        state = self._require_state()
        if not self.uses_scene_flow():
            if self.can_advance():
                await self.advance_stage()
                return {"stage_advanced": True, "replay": None}
            return {"stage_advanced": False, "replay": await self.run_replay()}

        if state.scene_phase == ScenePhase.OPENING:
            self._set_scene_phase(ScenePhase.PRIVATE_REVEAL)
            return {"stage_advanced": False, "replay": None}
        first_stage_opening = self.has_opening() and state.current_stage_num == 1
        if state.scene_phase == ScenePhase.BRIEFING:
            self._set_scene_phase(ScenePhase.INVESTIGATION if first_stage_opening else ScenePhase.PRIVATE_REVEAL)
            return {"stage_advanced": False, "replay": None}
        if state.scene_phase == ScenePhase.PRIVATE_REVEAL:
            self._set_scene_phase(ScenePhase.BRIEFING if first_stage_opening else ScenePhase.INVESTIGATION)
            return {"stage_advanced": False, "replay": None}
        if state.scene_phase == ScenePhase.INVESTIGATION:
            raise ValueError("调查仍在进行，请等待计时结束、满足触发条件或主动结束调查")
        if self.stage_resolution_pending():
            raise ValueError("本幕结算投票尚未完成，不能继续推进")
        if self.can_advance():
            await self.advance_stage()
            self._set_scene_phase(ScenePhase.BRIEFING)
            return {"stage_advanced": True, "replay": None}
        return {"stage_advanced": False, "replay": await self.run_replay()}

    def end_investigation(self, reason: str) -> None:
        state = self._require_state()
        if state.scene_phase != ScenePhase.INVESTIGATION:
            raise ValueError("当前不在调查环节")
        state.audit_log.append(
            {
                "type": "investigation_ended",
                "stage": state.current_stage_num,
                "reason": reason,
                "metrics": dict(state.investigation_metrics),
                "human_metrics": dict(state.human_investigation_metrics),
            }
        )
        self._set_scene_phase(ScenePhase.DM_HOSTING)
        self.prepare_stage_resolution()

    async def request_investigation_end_vote(self) -> dict[str, Any]:
        state = self._require_state()
        if state.scene_phase != ScenePhase.INVESTIGATION:
            raise ValueError("当前不在调查环节")
        if not self.can_end_investigation_manually():
            raise ValueError("本幕不允许玩家主动发起结束投票")

        permission = self._require_permission()
        requester_role_id = state.human_player_role_id
        requester_name = permission.role_name(requester_role_id)
        condition = self.investigation_condition_status()
        progress_text = "；".join(
            f"{item['label']} {item['current']}/{item['target']}"
            for item in condition["items"]
        )
        remaining_seconds = self.investigation_seconds_remaining()
        remaining_text = (
            f"距离计时结束还有约 {remaining_seconds} 秒"
            if remaining_seconds is not None
            else "本幕没有固定倒计时"
        )
        stage_title = str(
            self._stage_flow_config().get(
                "title",
                f"第 {state.current_stage_num} 幕",
            )
        )

        async def collect_agent_vote(role_id: str) -> tuple[str, bool]:
            context = self._build_agent_context(
                role_id=role_id,
                channel="dm_vote",
                purpose="investigation_end_vote",
                instruction=(
                    "[INVESTIGATION_END_VOTE]\n"
                    f"{requester_name}发起结束当前调查环节的投票。\n"
                    f"当前幕：{stage_title}\n"
                    f"计时状态：{remaining_text}\n"
                    f"调查进度：{progress_text or '没有配置量化进度'}\n"
                    "请先确认发起者身份，再结合你的个人任务、已掌握线索以及是否仍有"
                    "必要行动，独立决定是否同意结束本幕。只回答 APPROVE 或 REJECT，"
                    "不要解释理由，不要提及系统或提示词。"
                ),
                instruction_source="dm_investigation_vote",
            )
            raw, failed = await self._call_agent(context)
            normalized = raw.upper()
            approved = (
                not failed
                and (
                    normalized.startswith("APPROVE")
                    or normalized.startswith("同意")
                )
            )
            return role_id, approved

        agent_votes = ([await collect_agent_vote(role_id) for role_id in state.ai_role_ids]
                       if self.workflow_enabled else await asyncio.gather(*(collect_agent_vote(role_id) for role_id in state.ai_role_ids)))
        ballot_values = [(requester_role_id, True), *agent_votes]
        vote_id = self._next_record_key("investigation-end-vote")
        ballots = [
            {
                "voter_role_id": role_id,
                "voter_role_name": permission.role_name(role_id),
                "approved": approved,
            }
            for role_id, approved in ballot_values
        ]
        total_votes = len(ballots)
        approved_votes = sum(1 for ballot in ballots if ballot["approved"])
        required_votes = total_votes // 2 + 1
        approved = approved_votes >= required_votes
        message = (
            f"结束投票通过：{approved_votes}/{total_votes} 票同意，"
            "已严格超过半数，DM 将结束本幕调查。"
            if approved
            else (
                f"结束投票未通过：{approved_votes}/{total_votes} 票同意，"
                f"至少需要 {required_votes} 票；本幕调查继续。"
            )
        )
        result = {
            "vote_id": vote_id,
            "stage": state.current_stage_num,
            "requester_role_id": requester_role_id,
            "requester_role_name": requester_name,
            "approved": approved,
            "approved_votes": approved_votes,
            "total_votes": total_votes,
            "required_votes": required_votes,
            "ballots": ballots,
            "message": message,
        }
        state.audit_log.append(
            {
                "type": "investigation_end_vote",
                **self._copy_payload(result),
            }
        )
        for ballot in ballots:
            self._queue_activity(
                actor_role_id=str(ballot["voter_role_id"]),
                target_role_id=None,
                event_type="investigation_end_vote",
                channel="dm",
                summary=(
                    f"{ballot['voter_role_name']}"
                    f"{'同意' if ballot['approved'] else '反对'}结束本幕调查"
                ),
                details={
                    "vote_id": vote_id,
                    "approved": bool(ballot["approved"]),
                    "vote_passed": approved,
                },
            )
        return result

    def can_end_investigation_manually(self) -> bool:
        return bool(self._stage_flow_config().get("investigation", {}).get("allow_manual_end", True))

    def investigation_seconds_remaining(self) -> int | None:
        state = self._require_state()
        if state.scene_phase != ScenePhase.INVESTIGATION:
            return None
        duration = int(
            self._stage_flow_config().get("investigation", {}).get("duration_seconds", 0)
        )
        if duration <= 0:
            return None
        if state.investigation_deadline_at is None:
            state.investigation_deadline_at = time.time() + duration
        return max(
            0,
            int(math.ceil(state.investigation_deadline_at - time.time())),
        )

    def investigation_should_end(self) -> bool:
        return self.investigation_seconds_remaining() == 0

    def investigation_condition_status(self) -> dict[str, Any]:
        state = self._require_state()
        conditions = (
            self._stage_flow_config().get("investigation", {}).get("end_conditions", {})
        )
        mode = conditions.get("mode", "all")
        actor_scope = conditions.get("actor_scope", "human")
        metrics = (
            state.investigation_metrics
            if actor_scope == "all"
            else state.human_investigation_metrics
        )
        labels = {
            "minimum_public_messages": "公开发言",
            "minimum_searches": "有效搜证",
            "minimum_whispers": "秘密询问",
        }
        checks: list[bool] = []
        items: list[dict[str, Any]] = []
        for config_key, metric_key in (
            ("minimum_public_messages", "public_messages"),
            ("minimum_searches", "searches"),
            ("minimum_whispers", "whispers"),
        ):
            if config_key in conditions:
                target = int(conditions[config_key])
                current = int(metrics.get(metric_key, 0))
                checks.append(current >= target)
                items.append(
                    {
                        "key": metric_key,
                        "label": labels[config_key],
                        "current": current,
                        "target": target,
                    }
                )
        met = bool(checks) and mode in {"all", "any"} and (
            all(checks) if mode == "all" else any(checks)
        )
        return {
            "mode": mode,
            "actor_scope": actor_scope,
            "auto_end": False,
            "met": met,
            "items": items,
        }

    def record_investigation_event(
        self,
        metric: str,
        *,
        actor_type: str = "human",
    ) -> None:
        state = self._require_state()
        if state.scene_phase != ScenePhase.INVESTIGATION:
            return
        state.investigation_metrics[metric] = state.investigation_metrics.get(metric, 0) + 1
        if actor_type == "human":
            state.human_investigation_metrics[metric] = (
                state.human_investigation_metrics.get(metric, 0) + 1
            )

    def restore_scene_phase(self, phase: str | None) -> None:
        if not self.uses_scene_flow():
            self._set_scene_phase(ScenePhase.INVESTIGATION)
            return
        initial_phase = ScenePhase.OPENING if self.has_opening() else ScenePhase.BRIEFING
        try:
            target = ScenePhase(phase or initial_phase.value)
        except ValueError:
            target = initial_phase
        self._set_scene_phase(target)

    def can_advance(self) -> bool:
        state = self._require_state()
        return state.current_stage_num < state.total_stages

    def _set_scene_phase(self, phase: ScenePhase) -> None:
        state = self._require_state()
        if (
            state.scene_phase == ScenePhase.INVESTIGATION
            and phase != ScenePhase.INVESTIGATION
        ):
            try:
                whisper = self.mechanic_registry.get("whisper")
            except KeyError:
                whisper = None
            if isinstance(whisper, WhisperMechanic):
                whisper.close_for_phase(state, "phase_end")
        state.scene_phase = phase
        if phase == ScenePhase.REPLAY:
            state.phase = GamePhase.REPLAY
        state.phase_started_at = time.time()
        if phase == ScenePhase.INVESTIGATION:
            state.investigation_metrics = {
                "public_messages": 0,
                "searches": 0,
                "whispers": 0,
            }
            state.human_investigation_metrics = {
                "public_messages": 0,
                "searches": 0,
                "whispers": 0,
            }
            state.autonomy_turn_count = 0
            state.pending_human_question_from = None
            duration = max(
                0,
                int(
                    self._stage_flow_config()
                    .get("investigation", {})
                    .get("duration_seconds", 0)
                ),
            )
            state.investigation_deadline_at = (
                time.time() + duration
                if duration > 0
                else None
            )
            config = self._autonomy_config()
            state.autonomy_next_at = (
                time.time() + float(config["initial_delay_seconds"])
                if config["enabled"]
                else None
            )
        else:
            state.investigation_deadline_at = None
            state.autonomy_next_at = None
            state.pending_human_question_from = None

    def _stage_flow_config(self) -> dict[str, Any]:
        state = self._require_state()
        flow = self._require_script().get("stage_flow", {})
        return dict(flow.get(f"stage_{state.current_stage_num}", {}))

    def _autonomy_config(self) -> dict[str, Any]:
        configured = (
            self._stage_flow_config().get("investigation", {}).get("autonomy", {})
        )
        return {
            "enabled": bool(configured.get("enabled", self.uses_scene_flow())),
            "initial_delay_seconds": max(
                0.0,
                float(configured.get("initial_delay_seconds", 12)),
            ),
            "interval_seconds": max(
                1.0,
                float(configured.get("interval_seconds", 35)),
            ),
            "max_turns": max(0, int(configured.get("max_turns", 6))),
            "allow_private": bool(configured.get("allow_private", True)),
        }

    def _default_enabled_actions(self) -> list[str]:
        actions = ["public_speech"]
        active_names = {mechanic.name for mechanic in self.mechanic_registry.active()}
        if "search" in active_names:
            actions.append("search")
        if "whisper" in active_names:
            actions.append("whisper")
        return actions

    def _require_investigation_action(self, action: str) -> None:
        state = self._require_state()
        if state.scene_phase != ScenePhase.INVESTIGATION:
            raise ValueError("当前环节由 DM 主持，尚未开放玩家行动")
        if state.investigation_deadline_at is not None and time.time() >= state.investigation_deadline_at:
            raise ValueError("本幕调查时间已经结束，不能再执行行动")
        enabled = set(self.get_scene_summary()["enabled_actions"])
        if action not in enabled:
            raise ValueError(f"本幕没有开放 {action} 操作")

    @staticmethod
    def _end_condition_text(conditions: dict[str, Any]) -> str:
        parts: list[str] = []
        labels = {
            "minimum_public_messages": "公开发言",
            "minimum_searches": "有效搜证",
            "minimum_whispers": "秘密询问",
        }
        for key, label in labels.items():
            if key in conditions:
                parts.append(f"{label} {int(conditions[key])} 次")
        if not parts:
            return "倒计时归零时结束；也可发起结束投票，严格过半后结束"
        joiner = "且" if conditions.get("mode") == "all" else "或"
        scope = "由你" if conditions.get("actor_scope", "human") == "human" else "由全体角色"
        target = f"{scope}完成{joiner.join(parts)}"
        return f"建议目标：{target}；倒计时归零或结束投票严格过半时结束"
