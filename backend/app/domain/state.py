from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class GamePhase(str, Enum):
    INIT = "init"
    PLAYING = "playing"
    FINALE = "finale"
    REPLAY = "replay"


class ScenePhase(str, Enum):
    OPENING = "opening"
    BRIEFING = "briefing"
    PRIVATE_REVEAL = "private_reveal"
    INVESTIGATION = "investigation"
    DM_HOSTING = "dm_hosting"
    REPLAY = "replay"


@dataclass
class GameState:
    script_id: str
    human_player_role_id: str
    ai_role_ids: list[str]
    current_stage_num: int
    total_stages: int
    phase: GamePhase
    scene_phase: ScenePhase = ScenePhase.INVESTIGATION
    phase_started_at: float = field(default_factory=time.time)
    investigation_deadline_at: float | None = None
    investigation_metrics: dict[str, int] = field(
        default_factory=lambda: {"public_messages": 0, "searches": 0, "whispers": 0}
    )
    human_investigation_metrics: dict[str, int] = field(
        default_factory=lambda: {"public_messages": 0, "searches": 0, "whispers": 0}
    )
    autonomy_turn_count: int = 0
    autonomy_next_at: float | None = None
    pending_human_question_from: str | None = None
    public_history: list[dict[str, str]] = field(default_factory=list)
    role_clues: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    role_event_counts: dict[int, dict[str, dict[str, int]]] = field(default_factory=dict)
    role_scores: dict[str, int] = field(default_factory=dict)
    stage_resolutions: dict[int, dict[str, Any]] = field(default_factory=dict)
    penalties: list[dict[str, Any]] = field(default_factory=list)
    applied_penalty_keys: set[str] = field(default_factory=set)
    audit_log: list[dict[str, Any]] = field(default_factory=list)
    persistence_events: list[dict[str, Any]] = field(default_factory=list)
    record_sequence: int = 0
