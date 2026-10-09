from __future__ import annotations

from typing import Any

from .base import BaseLLM
from .budget import ContextBudget
from .echo import EchoLLM
from .openai_compatible import OpenAICompatibleLLM


class LLMFactory:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {"provider": "echo"}

    def create(self) -> BaseLLM:
        budget = ContextBudget.from_config(self.config)
        provider = self.config.get("provider", "openai_compatible")
        if provider == "echo":
            llm = EchoLLM()
            llm.budget = budget
            return llm
        return OpenAICompatibleLLM(
            model=self.config.get("model", "qwen3-32b"),
            base_url=self.config.get("base_url", "http://localhost:11434/v1"),
            api_key=self.config.get("api_key", "ollama"),
            timeout=float(self.config.get("timeout", 30.0)),
            budget=budget,
            reasoning_effort=str(self.config.get("reasoning_effort", "")),
        )
