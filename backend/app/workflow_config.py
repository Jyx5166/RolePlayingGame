from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from paths import app_root


class WorkflowSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    version: Literal[1, 2] = 1
    transport: Literal["native_tools", "validated_action_json"] = "native_tools"
    max_model_requests_per_role_turn: int = Field(default=4, ge=1, le=100)
    max_tool_calls_per_role_turn: int = Field(default=3, ge=1, le=100)
    max_rounds_per_role_turn: int = Field(default=3, ge=1, le=100)
    max_public_responders: int = Field(default=3, ge=1, le=20)
    max_graph_steps: int = Field(default=32, ge=8, le=1000)
    concurrency: Literal[1] = 1
    automatic_retries: Literal[0] = 0
    dm_reads_private_dialogue: bool = False
    context_strategy: Literal["legacy_bounded", "archive_retrieval"] = "legacy_bounded"
    memory_index_items: int = Field(default=12, ge=1, le=40)
    memory_chunk_chars: int = Field(default=1500, ge=200, le=4000)
    lease_seconds: int = Field(default=20, ge=10, le=120)
    heartbeat_seconds: int = Field(default=5, ge=1, le=10)
    reconnect_grace_seconds: int = Field(default=30, ge=0, le=300)
    model_hosting: bool = False
    reasoning_effort: Literal['','none','low','high','max'] = ''

    @model_validator(mode='after')
    def check_lease_intervals(self):
        if self.heartbeat_seconds>=self.lease_seconds:
            raise ValueError('心跳间隔必须短于租约有效期')
        return self


def load_workflow_settings(path: Path | None = None) -> WorkflowSettings:
    path = path or app_root() / "backend" / "config" / "workflow.yaml"
    return WorkflowSettings.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
