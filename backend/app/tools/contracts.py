from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class SearchArguments(ToolArguments):
    target_id: str = Field(min_length=1, max_length=128)


class ExchangeArguments(ToolArguments):
    target_role_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=500)


class DisclosureArguments(ToolArguments):
    clue_id: str = Field(min_length=1, max_length=128)
    mode: Literal["truthful", "distorted"] = "truthful"
    scope: Literal["public", "private"] = "public"
    target_role_id: str | None = None
    shared_content: str = Field(default="", max_length=500)


class NoteArguments(ToolArguments):
    content: str = Field(min_length=1, max_length=500,
                         description="1 至 500 个字符（含标点）；请自行精简，建议 120 至 250 字。")


class SelectActorArguments(ToolArguments):
    role_id: str = Field(min_length=1, max_length=128)


class TaskArguments(ToolArguments):
    task_id: str = Field(min_length=1, max_length=128)


class EmptyArguments(ToolArguments):
    pass


class MemoryArguments(ToolArguments):
    query: str = Field(default='', max_length=200)
    memory_id: str | None = None
    offset: int = Field(default=0, ge=0, le=2000000)
    limit: int = Field(default=2, ge=1, le=3)


class SectionArguments(ToolArguments):
    section_id: Literal['public_briefing','dm_hosting']


class RoleReplyArguments(ToolArguments):
    content: str = Field(min_length=1, max_length=2000)


class InvitationDecisionArguments(ToolArguments):
    decision: Literal["ACCEPT", "REJECT"]


class PhaseEndDecisionArguments(ToolArguments):
    decision: Literal["APPROVE", "REJECT"]


class BoundaryDecisionArguments(ToolArguments):
    decision: Literal["ALLOW", "REJECT"]


class RoleVoteArguments(ToolArguments):
    target_role_id: str = Field(min_length=1, max_length=128)


def control_definition(purpose: str) -> tuple[str, type[ToolArguments], str]:
    return {
        "whisper_invitation": ("decide_invitation", InvitationDecisionArguments, "decision"),
        "investigation_end_vote": ("decide_phase_end", PhaseEndDecisionArguments, "decision"),
        "stage_vote": ("cast_role_vote", RoleVoteArguments, "target_role_id"),
        "semantic_boundary_review": ("review_speech", BoundaryDecisionArguments, "decision"),
    }.get(purpose, ("reply_dialogue", RoleReplyArguments, "content"))


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any]
    provider_call_id: str | None = None


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1.0"] = "1.0"
    tool_call_id: str
    status: Literal["succeeded", "rejected", "failed", "cancelled", "unknown"]
    code: str
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    gameplay_committed: bool = False


ROLE_TOOLS: dict[str, tuple[type[ToolArguments], str]] = {
    "speak_public": (NoteArguments, "直接在公开频道回应或发表证词，content 限 1 至 500 个字符（含标点），建议 120 至 250 字。被要求公开回应时先调用本工具，成功后才能研读或探索。只有成功工具收据才表示已公开；普通正文不会发布。所有角色均可读取，无需指定另一角色或等待其回复。只能使用自己已知的信息，证词不是已经证实的事实。"),
    "read_memory": (MemoryArguments, "按关键词检索自己的已授权记忆原文，或用 memory_id 与 next_offset 逐段读取。证词、推断不等于事实。"),
    "search_scene": (SearchArguments, "搜查当前可用地点。线索原文只返回给本角色，分享必须另行调用 share_clue。"),
    "public_exchange": (ExchangeArguments, "向指定角色公开发言。内容公开给所有玩家。"),
    "private_exchange": (ExchangeArguments, "邀请另一角色 Agent 私聊并交换信息。对方可以拒绝，不能强制真人玩家进入私聊。"),
    "share_clue": (DisclosureArguments, "分享自己已获得的线索；可保留原文并发布不同说法，接收方只得到发布的内容。"),
    "record_note": (NoteArguments, "保存自己的判断或假设摘要。不要提交隐藏思维过程。"),
}
DM_TOOLS: dict[str, tuple[type[ToolArguments], str]] = {
    'present_script_section': (SectionArguments, '在开场或主持阶段选择当前幕的授权公开段落。正文由剧本提供，不能自由编造或提前揭晓真相。'),
    "read_memory": (MemoryArguments, "检索本局 DM 档案的剧本全知信息及公开事件；默认不含私聊正文。"),
    "select_actor": (SelectActorArguments, "选择本次自主行动的角色 Agent，只能选择当前候选角色。"),
    "publish_task": (TaskArguments, "发布剧本当前幕已定义的公开任务，不能编造任务正文。"),
    "dispatch_stage_information": (EmptyArguments, "重新发放当前幕脚本定义的授权信息，不发布未来幕或 DM 真相。"),
}


def tool_definitions(actor_kind: str) -> list[dict[str, Any]]:
    catalog = DM_TOOLS if actor_kind == "dm" else ROLE_TOOLS
    return [{"type": "function", "function": {"name": name, "description": description,
            "parameters": schema.model_json_schema()}} for name, (schema, description) in catalog.items()]
