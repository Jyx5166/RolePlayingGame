from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .budget import ContextBudget


class BaseLLM(ABC):
    budget = ContextBudget()
    last_usage: dict[str, int] | None = None
    last_finish_reason: str | None = None

    def reset_call_metadata(self) -> None:
        self.last_usage = None
        self.last_finish_reason = None

    def call_metadata(self) -> dict[str, Any]:
        return {"provider": getattr(self, "provider", self.__class__.__name__),
                "model": getattr(self, "model", None), "usage": self.last_usage,
                "finish_reason": self.last_finish_reason}

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]]) -> str:
        raise NotImplementedError
