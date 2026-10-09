from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class AgentActionError(ValueError):
    pass


@dataclass(frozen=True)
class AgentAction:
    action: str
    target_role_id: str
    channel: str
    content: str
    search_target_id: str
    disclosure: str
    shared_content: str
    notebook_entry: str

    @classmethod
    def validate(
        cls,
        payload: dict[str, Any],
        *,
        candidate_role_ids: list[str],
        allowed_channels: set[str],
        search_target_ids: set[str],
    ) -> AgentAction:
        if not payload:
            raise AgentActionError("模型未返回有效 JSON 动作")

        action = str(payload.get("action") or "communicate")
        if action not in {"communicate", "search"}:
            raise AgentActionError(f"不支持的动作类型：{action}")

        target_role_id = str(payload.get("target_role_id") or "")
        channel = str(payload.get("channel") or "")
        content = str(payload.get("content") or "").strip()
        search_target_id = str(payload.get("search_target_id") or "")
        disclosure = str(payload.get("disclosure") or "keep")
        shared_content = str(payload.get("shared_content") or "").strip()
        notebook_entry = str(payload.get("notebook_entry") or "").strip()

        needs_recipient = action == "communicate" or (
            action == "search" and disclosure != "keep" and channel == "private"
        )
        if (needs_recipient or target_role_id) and target_role_id not in candidate_role_ids:
            raise AgentActionError("动作目标不在当前可选角色中")

        if (action == "communicate" or disclosure != "keep") and channel not in allowed_channels:
            raise AgentActionError("动作频道在当前阶段不可用")

        if len(content) > 500:
            raise AgentActionError("动作发言超过 500 字")
        if len(shared_content) > 500:
            raise AgentActionError("线索披露内容超过 500 字")
        if len(notebook_entry) > 500:
            raise AgentActionError("推理摘要超过 500 字")

        if action == "communicate":
            if not content:
                raise AgentActionError("交流动作缺少发言内容")
            return cls(
                action=action,
                target_role_id=target_role_id,
                channel=channel,
                content=content,
                search_target_id="",
                disclosure="keep",
                shared_content="",
                notebook_entry=notebook_entry,
            )

        if search_target_id not in search_target_ids:
            raise AgentActionError("搜证目标在当前阶段不可用")
        if disclosure not in {"keep", "truthful", "distorted"}:
            raise AgentActionError("线索披露策略无效")
        if disclosure == "distorted" and not shared_content:
            raise AgentActionError("扭曲披露必须提供对外说法")
        return cls(
            action=action,
            target_role_id=target_role_id,
            channel=channel,
            content=content,
            search_target_id=search_target_id,
            disclosure=disclosure,
            shared_content=shared_content,
            notebook_entry=notebook_entry,
        )
