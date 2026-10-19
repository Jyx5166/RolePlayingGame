from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .budget import ContextBudget
from .tools import ToolModelReply, json_transport_messages, parse_json_reply


class ModelOutputTruncated(RuntimeError):
    """A provider receipt explicitly reports length, not a usable completion."""


class BaseLLM(ABC):
    budget = ContextBudget()
    last_usage: dict[str, int] | None = None
    last_finish_reason: str | None = None
    supports_native_tools = False
    last_provider_invoked: bool | None = None

    def reset_call_metadata(self) -> None:
        self.last_usage = None
        self.last_finish_reason = None
        self.last_provider_invoked = None

    def call_metadata(self) -> dict[str, Any]:
        return {"provider": getattr(self, "provider", self.__class__.__name__),
                "model": getattr(self, "model", None), "usage": self.last_usage,
                "finish_reason": self.last_finish_reason, "provider_invoked": self.last_provider_invoked}

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]]) -> str:
        raise NotImplementedError

    async def chat_tools(self, messages: list[dict[str, Any]], definitions: list[dict[str, Any]],
                         *, transport: str = "native_tools") -> ToolModelReply:
        if transport != "validated_action_json":
            raise RuntimeError("当前模型适配器未实现原生工具调用；需明确配置 validated_action_json")
        return parse_json_reply(await self.chat(json_transport_messages(messages, definitions)))
