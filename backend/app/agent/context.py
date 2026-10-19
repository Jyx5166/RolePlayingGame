from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import json
import re
from typing import Any, Literal
from runtime.contracts import RuntimeScope


class ContextAccessError(ValueError):
    """Raised when an Agent context would cross a visibility boundary."""


class ContextScope(str, Enum):
    PUBLIC = "public"
    PARTICIPANT_PRIVATE = "participant_private"
    ROLE_PRIVATE = "role_private"
    DM_ONLY = "dm_only"


def role_can_read_block(block: Mapping[str, Any], role_id: str, stage: int) -> bool:
    unlock = block.get("unlock_stage")
    if not isinstance(unlock, int) or isinstance(unlock, bool) or not 1 <= unlock <= stage:
        return False
    scope = block.get("visibility")
    return scope == "public" or (
        scope == "self_only" and block.get("owner_role") == role_id
    )


@dataclass(frozen=True)
class ContextMessage:
    role: Literal["user", "assistant"]
    content: str
    scope: ContextScope
    source_type: str
    source_key: str
    recipients: tuple[str, ...] = ()
    speaker_role_id: str = ""
    speaker_role_name: str = ""

    def to_llm_message(self) -> dict[str, str]:
        if self.source_type in {"public_history", "private_history"}:
            # A different character's assistant turn is quoted evidence, never
            # an assistant turn made by the receiving character.
            return {"role": "user", "content": "[QUOTED_DIALOGUE]\n" + json.dumps({
                "source_key": self.source_key, "speaker_role_id": self.speaker_role_id or "unknown",
                "speaker_role_name": self.speaker_role_name or "unknown",
                "epistemic_status": "unverified_testimony", "quote": self.content,
            }, ensure_ascii=False, separators=(",", ":"))}
        return {"role": self.role, "content": self.content}

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "scope": self.scope.value,
            "source_type": self.source_type,
            "source_key": self.source_key,
            "recipients": list(self.recipients),
            "speaker_role_id": self.speaker_role_id,
            "speaker_role_name": self.speaker_role_name,
        }


@dataclass(frozen=True)
class AgentContext:
    role_id: str
    stage: int
    channel: str
    purpose: str
    messages: tuple[ContextMessage, ...]
    runtime_scope: RuntimeScope | None = None

    def __post_init__(self) -> None:
        if not self.role_id:
            raise ContextAccessError("AgentContext 缺少接收角色")
        if self.runtime_scope is not None and self.runtime_scope.actor_role_id != self.role_id:
            raise ContextAccessError("上下文运行范围与接收角色不匹配")
        if self.stage < 1:
            raise ContextAccessError("AgentContext 阶段无效")
        for message in self.messages:
            if message.scope == ContextScope.DM_ONLY:
                raise ContextAccessError("DM 专属信息不能进入角色 Agent 上下文")
            if (
                message.scope == ContextScope.PARTICIPANT_PRIVATE
                and self.role_id not in message.recipients
            ):
                raise ContextAccessError(
                    f"角色 {self.role_id} 不是私密消息 {message.source_key} 的参与者"
                )
            if (
                message.scope == ContextScope.ROLE_PRIVATE
                and message.recipients != (self.role_id,)
            ):
                raise ContextAccessError(
                    f"角色私有消息 {message.source_key} 的接收者不匹配"
                )

    def to_llm_messages(self) -> list[dict[str, str]]:
        return [message.to_llm_message() for message in self.messages]

    def to_audit_record(self, system_prompt: str) -> dict[str, Any]:
        return {
            "runtime_scope": self.runtime_scope.model_dump() if self.runtime_scope else None,
            "role_id": self.role_id,
            "stage": self.stage,
            "channel": self.channel,
            "purpose": self.purpose,
            "system_prompt": system_prompt,
            "messages": [
                message.to_audit_record()
                for message in self.messages
            ],
        }


class AgentContextBroker:
    """Builds immutable Agent contexts from explicitly scoped information."""

    def __init__(self, role_ids: Collection[str]) -> None:
        normalized = tuple(dict.fromkeys(str(role_id) for role_id in role_ids))
        if not normalized:
            raise ValueError("AgentContextBroker 至少需要一个有效角色")
        self._role_ids = frozenset(normalized)
        self.runtime_scopes: dict[str, RuntimeScope] = {}

    def build(
        self,
        *,
        role_id: str,
        stage: int,
        channel: str,
        purpose: str,
        public_history: Sequence[Mapping[str, Any]] = (),
        public_limit: int = 10,
        private_history: Sequence[Mapping[str, Any]] = (),
        private_participants: Collection[str] = (),
        private_limit: int = 20,
        instruction: str = "",
        instruction_source: str = "dm_instruction",
    ) -> AgentContext:
        self._require_role(role_id)
        messages: list[ContextMessage] = []
        visible_public = self._window(public_history, public_limit)
        for index, raw in visible_public:
            messages.append(
                self._message_from_mapping(
                    raw,
                    scope=ContextScope.PUBLIC,
                    source_type="public_history",
                    source_key=str(raw.get("source_key") or f"public:legacy:{index}"),
                )
            )

        visible_private = self._window(private_history, private_limit)
        if visible_private:
            participants = tuple(
                dict.fromkeys(str(item) for item in private_participants)
            )
            unknown = set(participants) - self._role_ids
            if unknown:
                raise ContextAccessError(
                    "私密上下文包含未知角色：" + "、".join(sorted(unknown))
                )
            if role_id not in participants:
                raise ContextAccessError(
                    f"角色 {role_id} 不是当前私密上下文的参与者"
                )
            for index, raw in visible_private:
                messages.append(
                    self._message_from_mapping(
                        raw,
                        scope=ContextScope.PARTICIPANT_PRIVATE,
                        source_type="private_history",
                        source_key=str(raw.get("source_key") or f"private:legacy:{index}"),
                        recipients=participants,
                    )
                )

        normalized_instruction = instruction.strip()
        if normalized_instruction:
            messages.append(
                ContextMessage(
                    role="user",
                    content=normalized_instruction,
                    scope=ContextScope.ROLE_PRIVATE,
                    source_type=instruction_source,
                    source_key=f"{instruction_source}:{purpose}",
                    recipients=(role_id,),
                )
            )

        return AgentContext(
            role_id=role_id,
            stage=stage,
            channel=channel,
            purpose=purpose,
            messages=tuple(messages),
            runtime_scope=self.runtime_scopes.get(role_id),
        )

    def with_role_instruction(
        self,
        context: AgentContext,
        *,
        purpose: str,
        instruction: str,
        instruction_source: str,
    ) -> AgentContext:
        self._require_role(context.role_id)
        message = ContextMessage(
            role="user",
            content=instruction.strip(),
            scope=ContextScope.ROLE_PRIVATE,
            source_type=instruction_source,
            source_key=f"{instruction_source}:{purpose}",
            recipients=(context.role_id,),
        )
        return AgentContext(
            role_id=context.role_id,
            stage=context.stage,
            channel=context.channel,
            purpose=purpose,
            messages=(*context.messages, message),
            runtime_scope=context.runtime_scope,
        )

    def _require_role(self, role_id: str) -> None:
        if role_id not in self._role_ids:
            raise ContextAccessError(f"未知的 Agent 角色：{role_id}")

    @staticmethod
    def _window(history: Sequence[Mapping[str, Any]], limit: int) -> list[tuple[int, Mapping[str, Any]]]:
        if limit <= 0:
            return []
        start = max(0, len(history) - limit)
        return list(enumerate(history))[start:]

    @staticmethod
    def _message_from_mapping(
        raw: Mapping[str, Any],
        *,
        scope: ContextScope,
        source_type: str,
        source_key: str,
        recipients: tuple[str, ...] = (),
    ) -> ContextMessage:
        raw_role = str(raw.get("role", "user"))
        if raw_role not in {"user", "assistant"}:
            raise ContextAccessError(
                f"{source_type} 不允许使用 {raw_role} 消息角色"
            )
        content = str(raw.get("content", "")).strip()
        if not content:
            raise ContextAccessError(f"{source_type} 包含空消息")
        speaker_id = str(raw.get("actor_role_id") or raw.get("sender_role_id") or "")
        speaker_name = str(raw.get("actor_role_name") or raw.get("sender_role_name") or "")
        if not speaker_name:
            prefix = re.match(r"^([^\n:：]{1,40})[:：]", content)
            speaker_name = prefix.group(1).strip() if prefix else ""
        return ContextMessage(
            role="user",
            content=content,
            scope=scope,
            source_type=source_type,
            source_key=source_key,
            recipients=recipients,
            speaker_role_id=speaker_id,
            speaker_role_name=speaker_name,
        )
