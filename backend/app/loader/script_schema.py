"""Typed authoring contract for a static script, separate from per-game state.

JSON Schema describes structure. ScriptLoader also checks cross references,
stage reachability, and the runtime's task/vote rules before accepting a script.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
StageKey = Annotated[str, StringConstraints(pattern=r"^stage_[1-9][0-9]*$")]
Tag = Annotated[Text, StringConstraints(max_length=24)]
PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
Skill = Literal["narrative", "deduction", "faction"]
Mechanic = Literal["search", "whisper"]
Action = Literal["public_speech", "search", "whisper"]
ActionEvent = Literal[
    "search", "public_speech", "public_response", "autonomous_public_speech",
    "autonomous_public_response", "private_speech", "private_response",
    "autonomous_private_speech", "autonomous_private_response", "clue_disclosure",
]


class ScriptModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Provenance(ScriptModel):
    kind: Literal["original", "adaptation", "unknown"]
    creator: Text
    source: Text


class ScriptMeta(ScriptModel):
    script_id: Text
    title: Text
    tags: Annotated[list[Tag], Field(max_length=12)] = Field(default_factory=list)
    total_stages: PositiveInt
    supported_skills: Annotated[list[Skill], Field(min_length=1)]
    recommended_player_role: Text | None = None
    provenance: Provenance | None = None


class InfoBlock(ScriptModel):
    block_id: Text
    type: Text
    content: Text
    visibility: Literal["public", "self_only", "dm_only"] = Field(
        description="读取权限。public 允许角色读取该块，但不会自动广播；self_only 仅所有者可读；dm_only 仅 DM 可读。"
    )
    unlock_stage: PositiveInt = Field(description="最早允许读取的幕次，还受所在 stage_knowledge 幕次限制。")
    owner_role: Text


class StageKnowledge(ScriptModel):
    blocks: list[InfoBlock] = Field(default_factory=list)


class Role(ScriptModel):
    role_id: Text
    role_name: Text
    human_playable: bool
    public_identity: Text
    personality: Text | None = None
    hidden_goal: Text | None = Field(
        default=None, description="角色从开局就知道的私人目标；尚未解锁的真相应放入对应幕次的知识块。"
    )
    stage_knowledge: dict[StageKey, StageKnowledge]


class Clue(ScriptModel):
    id: Text
    content: Text
    exclusivity: Literal["shared", "exclusive"] = "shared"


class SearchTarget(ScriptModel):
    id: Text
    name: Text | None = None
    description: Text | None = None
    unlock_stage: PositiveInt = 1
    clues: list[Clue] = Field(default_factory=list)


class SearchConfig(ScriptModel):
    ap_per_stage: Annotated[list[NonNegativeInt], Field(min_length=1)] = Field(default_factory=lambda: [1])
    search_targets: list[SearchTarget] = Field(default_factory=list)


class WhisperConfig(ScriptModel):
    max_sessions_per_stage: NonNegativeInt = 2
    role_available_from_stage: dict[Text, PositiveInt] = Field(default_factory=dict)


class MechanicsConfig(ScriptModel):
    search: SearchConfig | None = None
    whisper: WhisperConfig | None = None


class ActivityCountCheck(ScriptModel):
    type: Literal["activity_count"]
    label: Text
    event_types: Annotated[list[ActionEvent], Field(min_length=1)]
    minimum: PositiveInt


class ClueDisclosureCheck(ScriptModel):
    type: Literal["clue_disclosure"]
    label: Text
    channel: Literal["public", "private"]
    disclosure_mode: Literal["truthful", "distorted"] = "truthful"
    clue_id: Text | None = None
    target_role_id: Text | None = None
    new_public: bool = False


TaskCheck = Annotated[ActivityCountCheck | ClueDisclosureCheck, Field(discriminator="type")]
TaskChecks = Annotated[list[TaskCheck], Field(min_length=1)]


class EndConditions(ScriptModel):
    mode: Literal["all", "any"] = "all"
    actor_scope: Literal["human", "all"] = "human"
    auto_end: Literal[False] = False
    minimum_public_messages: NonNegativeInt = 0
    minimum_searches: NonNegativeInt = 0
    minimum_whispers: NonNegativeInt = 0


class Autonomy(ScriptModel):
    enabled: bool = True
    initial_delay_seconds: Annotated[int | float, Field(ge=0)] = 12
    interval_seconds: Annotated[int | float, Field(ge=1)] = 35
    max_turns: NonNegativeInt = 6
    allow_private: bool = True


class Investigation(ScriptModel):
    duration_seconds: NonNegativeInt = 0
    enabled_actions: Annotated[list[Action], Field(min_length=1)]
    allow_manual_end: bool = True
    end_conditions: EndConditions = Field(default_factory=EndConditions)
    autonomy: Autonomy = Field(default_factory=Autonomy)


class Metric(ScriptModel):
    key: Text
    label: Text
    unit: Text
    initial: int = 0


class ScoringRule(ScriptModel):
    label: Text
    event_types: Annotated[list[ActionEvent], Field(min_length=1)]
    points_per_event: int
    max_points: NonNegativeInt


class RoleAdjustment(ScriptModel):
    points: int
    reason: Text


class Penalty(ScriptModel):
    label: Text
    description: Text
    target_stage_offset: PositiveInt = 1
    search_ap_reduction: NonNegativeInt = 0
    extra_task: str = ""
    completion_checks: TaskChecks | None = None


class StageVote(ScriptModel):
    prompt: Text
    eligible_role_ids: Annotated[list[Text], Field(min_length=2)]
    penalty: Penalty | None = None


class FinalDecision(ScriptModel):
    prompt: Text
    eligible_role_ids: Annotated[list[Text], Field(min_length=2)]
    correct_verdict: Text
    incorrect_verdict: Text
    reveal_truth_on_correct: Literal[True] = True


class Resolution(ScriptModel):
    title: Text
    metric: Metric
    scoring_rules: Annotated[list[ScoringRule], Field(min_length=1)]
    role_adjustments: dict[Text, RoleAdjustment] = Field(default_factory=dict)
    vote: StageVote | None = None
    final_decision: FinalDecision | None = None


class StageFlow(ScriptModel):
    title: Text
    public_briefing: Text
    public_tasks: list[Text] = Field(default_factory=list)
    personal_tasks: dict[Text, Text] = Field(default_factory=dict)
    personal_task_checks: dict[Text, TaskChecks] = Field(default_factory=dict)
    investigation: Investigation
    resolution: Resolution
    dm_hosting: Text


class Opening(ScriptModel):
    title: Text
    content: Text = Field(description="选角后、角色剧本和第一幕之前展示的全剧开幕；仅包含公开背景与人物关系。")


class HardConstraint(ScriptModel):
    role_id: Text
    until_stage: PositiveInt
    keywords: Annotated[list[Text], Field(min_length=1)]
    message: Text


class EvidenceStep(ScriptModel):
    conclusion: Text
    clue_ids: Annotated[list[Text], Field(min_length=1)]
    reasoning: Text


class Truth(ScriptModel):
    full_story: Text
    culprit_role_id: Text | None = None
    complete_timeline: dict[Text, Text] = Field(
        default_factory=dict, description="真实事件时间或事件标识到事实的映射；事件时间线与分幕调查流程分别表达。"
    )
    role_arcs: dict[Text, Text] = Field(default_factory=dict)
    evidence_chain: list[EvidenceStep] = Field(default_factory=list)


class ScriptDocument(ScriptModel):
    schema_version: Literal["1.0"]
    script_meta: ScriptMeta
    story_background: Text
    opening: Opening | None = None
    roles: Annotated[list[Role], Field(min_length=2)]
    mechanics_enabled: list[Mechanic] = Field(default_factory=list)
    mechanics_config: MechanicsConfig = Field(default_factory=MechanicsConfig)
    stage_flow: dict[StageKey, StageFlow] = Field(default_factory=dict)
    hard_constraints: list[HardConstraint] = Field(default_factory=list)
    truth: Truth

    model_config = ConfigDict(
        extra="forbid", strict=True,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://jujing.local/schemas/script-1.0.schema.json",
            "description": "剧镜剧本 1.0。跨引用、权限、幕次与任务可达性由 ScriptLoader 校验。",
            "allOf": [{
                "if": {"required": ["opening"], "properties": {"opening": {"type": "object"}}},
                "then": {"required": ["stage_flow"], "properties": {"stage_flow": {"type": "object", "minProperties": 1}}},
            }, {
                "if": {"properties": {"script_meta": {"properties": {
                    "supported_skills": {"contains": {"const": "deduction"}}
                }}}},
                "then": {
                    "required": ["stage_flow"],
                    "properties": {
                        "stage_flow": {"type": "object", "minProperties": 1},
                        "truth": {"required": ["evidence_chain"], "properties": {
                            "evidence_chain": {"type": "array", "minItems": 1}
                        }},
                    },
                },
            }],
        },
    )
