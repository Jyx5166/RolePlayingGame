from __future__ import annotations
from copy import deepcopy
from typing import Any
from agent.context import AgentContext
from domain.state import ScenePhase


class GameRecords:
    def record_dm_narration_for_notebooks(
        self,
        phase: str,
        title: str,
        content: str,
    ) -> None:
        state = self._require_state()
        normalized = content.strip()
        if not normalized:
            return
        recipients = [state.human_player_role_id, *state.ai_role_ids]
        if phase == ScenePhase.OPENING.value:
            entries = [("opening", "dm-opening:1", title, normalized)]
        elif phase == ScenePhase.BRIEFING.value:
            script = self._require_script()
            config = self._stage_flow_config()
            entries: list[tuple[str, str, str, str]] = []
            if state.current_stage_num == 1 and not self.has_opening():
                entries.append(
                    (
                        "story_background",
                        "dm-background:1",
                        "案件背景",
                        str(script.get("story_background", "")),
                    )
                )
            entries.append(
                (
                    "public_briefing",
                    f"dm-public-briefing:{state.current_stage_num}",
                    f"{title} · 公开通报",
                    str(config.get("public_briefing", "")),
                )
            )
            public_tasks = [
                str(task).strip()
                for task in config.get("public_tasks", [])
                if str(task).strip()
            ]
            if public_tasks:
                entries.append(
                    (
                        "public_tasks",
                        f"dm-public-tasks:{state.current_stage_num}",
                        f"{title} · 公开任务",
                        "\n".join(
                            f"{index}. {task}"
                            for index, task in enumerate(public_tasks, start=1)
                        ),
                    )
                )
        elif phase == ScenePhase.DM_HOSTING.value:
            entries = [
                (
                    "dm_hosting",
                    f"dm-hosting:{state.current_stage_num}",
                    f"{title} · DM 主持",
                    normalized,
                )
            ]
        else:
            entries = [
                (
                    "dm_narration",
                    f"dm:{state.current_stage_num}:{phase}",
                    title,
                    normalized,
                )
            ]

        for _, source_key, entry_title, entry_content in entries:
            self._remember_public_announcement(source_key, entry_title, entry_content)

        for role_id in recipients:
            for source_type, source_key, entry_title, entry_content in entries:
                self._queue_notebook(
                    role_id=role_id,
                    section="automatic",
                    source_type=source_type,
                    source_key=source_key,
                    title=entry_title,
                    content=entry_content,
                )

    def _remember_public_announcement(self, source_key: str, title: str, content: str) -> None:
        if not content.strip():
            return
        state = self._require_state()
        if not any(item.get("source_key") == source_key for item in state.public_history):
            state.public_history.append({"role": "user", "content": f"DM · {title}: {content}", "source_key": source_key})
        for role_id in state.ai_role_ids:
            self.agent_pool.get(role_id).remember_public_announcement(source_key, content)

    def _restore_legacy_public_announcements(self) -> None:
        state = self._require_state()
        script = self._require_script()
        if self.has_opening():
            self._remember_public_announcement("dm-opening:1", script["opening"]["title"], script["opening"]["content"])
        else:
            self._remember_public_announcement("dm-background:1", "案件背景", script["story_background"])
        for stage in range(1, state.current_stage_num + 1):
            if self.has_opening() and stage == state.current_stage_num == 1 and state.scene_phase in {
                ScenePhase.OPENING, ScenePhase.PRIVATE_REVEAL,
            }:
                continue
            config = script.get("stage_flow", {}).get(f"stage_{stage}", {})
            self._remember_public_announcement(f"dm-public-briefing:{stage}", "公开通报", str(config.get("public_briefing", "")))
            self._remember_public_announcement(f"dm-public-tasks:{stage}", "公开任务", "\n".join(config.get("public_tasks", [])))
            if stage < state.current_stage_num or state.scene_phase in {ScenePhase.DM_HOSTING, ScenePhase.REPLAY}:
                self._remember_public_announcement(f"dm-hosting:{stage}", "DM 主持", str(config.get("dm_hosting", "")))

    def drain_persistence_events(self) -> list[dict[str, Any]]:
        state = self._require_state()
        events = list(state.persistence_events)
        state.persistence_events.clear()
        return events

    def _record_intelligence_dispatch(self, stage: int) -> None:
        state = self._require_state()
        permission = self._require_permission()
        recipients = [state.human_player_role_id, *state.ai_role_ids]
        for role_id in recipients:
            role = permission.role_by_id(role_id)
            blocks = permission.current_stage_blocks(role_id, stage)
            for index, block in enumerate(blocks, start=1):
                is_public = block.get("visibility") == "public"
                self._queue_notebook(
                    role_id=role_id,
                    section="automatic",
                    source_type=(
                        "public_information"
                        if is_public
                        else "role_script"
                    ),
                    source_key=(
                        f"role-script:{stage}:"
                        f"{block.get('block_id', index)}"
                    ),
                    title=(
                        f"第 {stage} 幕 · DM 公开信息"
                        if is_public
                        else f"第 {stage} 幕 · 角色剧本"
                    ),
                    content=str(block["content"]),
                )
            self._queue_notebook(
                role_id=role_id,
                section="automatic",
                source_type="personal_task",
                source_key=f"personal-task:{stage}:{role_id}",
                title=f"第 {stage} 幕 · 个人任务",
                content=self._script_personal_task(
                    self._require_script(),
                    role,
                    stage,
                ),
            )
        deliveries = [
            {
                "role_id": role_id,
                "role_name": permission.role_name(role_id),
                "recipient_type": "player" if role_id == state.human_player_role_id else "agent",
                "block_count": len(permission.current_stage_blocks(role_id, stage)),
            }
            for role_id in recipients
        ]
        state.audit_log.append(
            {
                "type": "intelligence_dispatch",
                "stage": stage,
                "deliveries": deliveries,
            }
        )

    def _build_observed_event(
        self,
        *,
        actor_role_id: str,
        event_type: str,
        channel: str,
        content: str,
    ) -> dict[str, str]:
        state = self._require_state()
        permission = self._require_permission()
        role = permission.role_by_id(actor_role_id)
        return {
            "source_key": self._next_record_key("observed-event"),
            "phase": state.scene_phase.value,
            "stage": str(state.current_stage_num),
            "actor_role_id": actor_role_id,
            "actor_role_name": str(role["role_name"]),
            "actor_public_identity": str(role["public_identity"]),
            "actor_controller": (
                "真人玩家"
                if actor_role_id == state.human_player_role_id
                else "角色 Agent"
            ),
            "event_type": event_type,
            "channel": channel,
            "content": content.strip(),
        }

    def _broadcast_observed_event(
        self,
        event: dict[str, str],
        *,
        recipients: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> None:
        state = self._require_state()
        target_ids = recipients if recipients is not None else state.ai_role_ids
        excluded = set(exclude or [])
        for role_id in target_ids:
            if role_id in excluded and event["channel"] != "public":
                continue
            self.agent_pool.observe_event(role_id, event)

    @staticmethod
    def _format_observed_event(event: dict[str, str]) -> str:
        return (
            "[OBSERVED_EVENT]\n"
            f"source_key: {event.get('source_key', 'legacy_unknown')}\n"
            f"stage: {event['stage']}\n"
            f"actor_role_id: {event['actor_role_id']}\n"
            f"actor_role_name: {event['actor_role_name']}\n"
            f"actor_public_identity: {event['actor_public_identity']}\n"
            f"actor_controller: {event['actor_controller']}\n"
            f"event_type: {event['event_type']}\n"
            f"channel: {event['channel']}\n"
            f"content: {event['content']}"
        )

    def _queue_notebook(
        self,
        *,
        role_id: str,
        section: str,
        source_type: str,
        source_key: str,
        title: str,
        content: str,
    ) -> None:
        state = self._require_state()
        normalized = content.strip()
        if not normalized:
            return
        state.persistence_events.append(
            {
                "kind": "notebook",
                "role_id": role_id,
                "section": section,
                "source_type": source_type,
                "source_key": source_key,
                "stage": state.current_stage_num,
                "title": title,
                "content": normalized,
            }
        )

    def _queue_clue(self, clue: dict[str, Any]) -> None:
        state = self._require_state()
        state.persistence_events.append(
            {
                "kind": "clue",
                **dict(clue),
            }
        )

    def _queue_activity(
        self,
        *,
        actor_role_id: str,
        target_role_id: str | None,
        event_type: str,
        channel: str,
        summary: str,
        details: dict[str, Any],
    ) -> None:
        state = self._require_state()
        stage_counts = state.role_event_counts.setdefault(state.current_stage_num, {})
        role_counts = stage_counts.setdefault(actor_role_id, {})
        if event_type != "search" or details.get("clue"):
            role_counts[event_type] = role_counts.get(event_type, 0) + 1
        state.persistence_events.append(
            {
                "kind": "activity",
                "actor_role_id": actor_role_id,
                "target_role_id": target_role_id,
                "event_type": event_type,
                "stage": state.current_stage_num,
                "phase": state.scene_phase.value,
                "channel": channel,
                "summary": summary,
                "details": details,
            }
        )

    def _queue_agent_context(
        self,
        context: AgentContext,
        *,
        system_prompt: str,
        status: str,
        error: str,
        response: str,
        payload: dict[str, Any] | None = None,
        call_id: str | None = None,
    ) -> None:
        state = self._require_state()
        payload = deepcopy(payload) if payload is not None else context.to_audit_record(system_prompt)
        payload["response"] = response
        state.persistence_events.append(
            {
                "kind": "agent_context",
                "call_id": call_id or self._next_record_key("agent-context"),
                "role_id": context.role_id,
                "stage": context.stage,
                "phase": state.scene_phase.value,
                "channel": context.channel,
                "purpose": context.purpose,
                "status": status,
                "error": error,
                "context": payload,
            }
        )

    def _next_record_key(self, prefix: str) -> str:
        state = self._require_state()
        state.record_sequence += 1
        return (
            f"{prefix}:{state.current_stage_num}:"
            f"{state.record_sequence}"
        )
