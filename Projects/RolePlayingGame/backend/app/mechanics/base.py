from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MechanicBase(ABC):
    name: str

    @abstractmethod
    def describe_actions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def on_stage_advance(self, state: Any, new_stage: int) -> None:
        return None

    async def on_player_action(self, state: Any, action: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def export_runtime_state(self) -> dict[str, Any]:
        return {}

    def restore_runtime_state(self, state: Any, payload: dict[str, Any]) -> None:
        return None
