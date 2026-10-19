from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field


class RuntimeScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    game_id: int = Field(gt=0)
    run_id: str
    context_id: str
    agent_instance_id: str
    actor_kind: Literal["dm", "role", "human"]
    actor_role_id: str


@dataclass
class ExecutionFrame:
    game_id: int
    run_id: str
    request_id: str
    turn_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    model_counts: dict[str, int] = field(default_factory=dict)
    tool_counts: dict[str, int] = field(default_factory=dict)
    public_events: list[dict[str, Any]] = field(default_factory=list)
    candidate_role_ids: list[str] = field(default_factory=list)
    response_role_ids: set[str] = field(default_factory=set)
    responded_role_ids: set[str] = field(default_factory=set)
    public_trigger: str = ""
    activity_sink: Callable[[dict[str, Any]], Awaitable[None]] | None = None


execution_frame: ContextVar[ExecutionFrame | None] = ContextVar("game_execution_frame", default=None)


class RuntimeAccessError(ValueError):
    pass


class ExecutionBudgetError(ValueError):
    pass
