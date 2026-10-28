"""State passed between workflow nodes; confidential text stays in scoped storage."""

from __future__ import annotations

from typing import TypedDict


class ActorState(TypedDict, total=False):
    # Checkpoints hold references; confidential messages stay in their scoped store.
    role_id: str
    rounds: int
    model_ids: list[str]
    tool_ids: list[str]
    pending_tool_ids: list[str]
    selected_role_id: str
    stopped: bool


class DirectorState(TypedDict, total=False):
    game_id: int
    run_id: str
    request_id: str
    turn_id: str
    scheduled: bool
    hosting: bool
    recommended_role_id: str
    selected_role_id: str
