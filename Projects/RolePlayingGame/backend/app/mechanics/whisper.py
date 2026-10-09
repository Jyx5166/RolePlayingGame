from __future__ import annotations

from typing import Any

from .base import MechanicBase


class WhisperMechanic(MechanicBase):
    name = "whisper"

    def __init__(self, config: dict[str, Any]) -> None:
        self.max_sessions_per_stage = int(config.get("max_sessions_per_stage", 2))
        self.role_available_from_stage = {
            role_id: int(stage)
            for role_id, stage in config.get("role_available_from_stage", {}).items()
        }
        self._active_target_role_id: str | None = None
        self._active_stage: int | None = None
        self._session_counts: dict[int, int] = {}
        self._history: dict[str, list[dict[str, str]]] = {}

    @property
    def active_target_role_id(self) -> str | None:
        return self._active_target_role_id

    def describe_actions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "whisper_invite",
                "label": "发起私聊",
                "max_sessions_per_stage": self.max_sessions_per_stage,
            }
        ]

    async def on_stage_advance(self, state: Any, new_stage: int) -> None:
        if self._active_target_role_id is not None and self._active_stage != new_stage:
            self.close_for_phase(state, "stage_advance")

    def close_for_phase(self, state: Any, reason: str) -> None:
        if self._active_target_role_id is None:
            return
        state.audit_log.append(
            {
                "type": "whisper_closed",
                "stage": state.current_stage_num,
                "target_role_id": self._active_target_role_id,
                "reason": reason,
            }
        )
        self._active_target_role_id = None
        self._active_stage = None

    async def on_player_action(self, state: Any, action: dict[str, Any]) -> dict[str, Any]:
        action_type = action.get("type")
        if action_type == "whisper_invite":
            return self._invite(state, str(action.get("target_role_id", "")))
        if action_type == "whisper_close":
            return self._close(state)
        raise ValueError(f"不支持的私聊操作：{action_type}")

    def status(self, state: Any) -> dict[str, Any]:
        stage = int(state.current_stage_num)
        used = self._session_counts.get(stage, 0)
        return {
            "enabled": True,
            "active_target_role_id": self._active_target_role_id,
            "remaining_sessions": max(0, self.max_sessions_per_stage - used),
        }

    def conversation_messages(self, target_role_id: str) -> list[dict[str, str]]:
        return [
            {"role": item["message_role"], "content": item["content"],
             "source_key": item.get("source_key") or f"private:legacy:{target_role_id}:{index}"}
            for index, item in enumerate(self._history.get(target_role_id, []))
        ]

    def export_runtime_state(self) -> dict[str, Any]:
        return {
            "active_target_role_id": self._active_target_role_id,
            "active_stage": self._active_stage,
            "session_counts": dict(self._session_counts),
            "history": {
                role_id: [dict(message) for message in messages]
                for role_id, messages in self._history.items()
            },
        }

    def restore_runtime_state(self, state: Any, payload: dict[str, Any]) -> None:
        valid_targets = set(state.ai_role_ids)
        active_target = payload.get("active_target_role_id")
        active_stage = payload.get("active_stage")
        if (
            state.scene_phase.value == "investigation"
            and active_target in valid_targets
            and int(active_stage or 0) == int(state.current_stage_num)
        ):
            self._active_target_role_id = str(active_target)
            self._active_stage = int(active_stage)
        else:
            self._active_target_role_id = None
            self._active_stage = None
        self._session_counts = {
            int(stage): max(0, int(count))
            for stage, count in payload.get("session_counts", {}).items()
            if int(stage) >= 1
        }
        self._history = {
            str(role_id): [
                {
                    "sender_role_id": str(message.get("sender_role_id", "")),
                    "message_role": str(message.get("message_role", "user")),
                    "content": str(message.get("content", "")),
                    "source_key": str(message.get("source_key") or f"private:legacy:{role_id}:{index}"),
                    "stage": message.get("stage"), "phase": message.get("phase", "legacy_unknown"),
                    "created_at": message.get("created_at"),
                }
                for index, message in enumerate(messages)
                if isinstance(message, dict)
            ]
            for role_id, messages in payload.get("history", {}).items()
            if role_id in valid_targets and isinstance(messages, list)
        }

    def record_message(
        self,
        state: Any,
        sender_role_id: str,
        target_role_id: str,
        message_role: str,
        content: str,
    ) -> None:
        if self._active_target_role_id != target_role_id:
            raise ValueError("当前没有与该角色进行私聊")
        state.record_sequence += 1
        self._history.setdefault(target_role_id, []).append(
            {
                "sender_role_id": sender_role_id,
                "message_role": message_role,
                "content": content,
                "source_key": f"whisper:{state.current_stage_num}:{state.record_sequence}",
                "stage": state.current_stage_num, "phase": state.scene_phase.value,
            }
        )
        state.audit_log.append(
            {
                "type": "whisper_message",
                "stage": state.current_stage_num,
                "sender_role_id": sender_role_id,
                "conversation_role_id": target_role_id,
                "content": content,
            }
        )

    def resolve_invitation(
        self,
        state: Any,
        target_role_id: str,
        accepted: bool,
    ) -> dict[str, Any]:
        if not accepted:
            return self._decline(state, target_role_id, "该角色基于当前立场拒绝了私聊邀请。")

        stage = int(state.current_stage_num)
        used = self._session_counts.get(stage, 0)
        self._session_counts[stage] = used + 1
        self._active_target_role_id = target_role_id
        self._active_stage = stage
        state.audit_log.append(
            {
                "type": "whisper_accepted",
                "stage": stage,
                "target_role_id": target_role_id,
            }
        )
        return {
            "type": "whisper_accepted",
            "target_role_id": target_role_id,
            "remaining_sessions": self.max_sessions_per_stage - self._session_counts[stage],
        }

    def _invite(self, state: Any, target_role_id: str) -> dict[str, Any]:
        if target_role_id not in state.ai_role_ids:
            raise ValueError("只能邀请当前游戏中的子 Agent 角色")
        if self._active_target_role_id is not None:
            if self._active_target_role_id == target_role_id:
                return {
                    "type": "whisper_accepted",
                    "target_role_id": target_role_id,
                    "message": "你们已经在私聊中。",
                }
            raise ValueError("请先结束当前私聊")

        stage = int(state.current_stage_num)
        available_from = self.role_available_from_stage.get(target_role_id, 1)
        if stage < available_from:
            return self._decline(
                state,
                target_role_id,
                f"该角色现在不愿进入私聊，阶段 {available_from} 后可以再次尝试。",
            )

        used = self._session_counts.get(stage, 0)
        if used >= self.max_sessions_per_stage:
            return self._decline(state, target_role_id, "本阶段的私聊次数已经用完。")

        return {
            "type": "whisper_pending",
            "target_role_id": target_role_id,
        }

    def _decline(self, state: Any, target_role_id: str, message: str) -> dict[str, Any]:
        state.audit_log.append(
            {
                "type": "whisper_declined",
                "stage": state.current_stage_num,
                "target_role_id": target_role_id,
                "message": message,
            }
        )
        return {
            "type": "whisper_declined",
            "target_role_id": target_role_id,
            "message": message,
        }

    def _close(self, state: Any) -> dict[str, Any]:
        target_role_id = self._active_target_role_id
        if target_role_id is None:
            return {"type": "whisper_closed", "target_role_id": None, "message": "当前没有进行中的私聊。"}
        state.audit_log.append(
            {
                "type": "whisper_closed",
                "stage": state.current_stage_num,
                "target_role_id": target_role_id,
                "reason": "player_request",
            }
        )
        self._active_target_role_id = None
        self._active_stage = None
        return {"type": "whisper_closed", "target_role_id": target_role_id}
