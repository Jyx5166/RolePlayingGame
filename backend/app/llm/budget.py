from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ContextBudgetError(ValueError):
    pass


def estimate_tokens(messages: list[dict[str, str]]) -> int:
    # Conservative UTF-8 estimate, not provider-reported token usage.
    return 8 + sum(len(message["content"].encode("utf-8")) + 16 for message in messages)


@dataclass(frozen=True)
class ContextBudget:
    context_window: int = 32768
    input_limit: int = 23000
    output_limit: int = 8192
    safety_margin: int = 1024

    def __post_init__(self) -> None:
        if min(self.context_window, self.input_limit, self.output_limit, self.safety_margin) < 1:
            raise ValueError("上下文预算必须为正整数")
        if self.input_limit + self.output_limit + self.safety_margin > self.context_window:
            raise ValueError("输入、输出及安全余量之和不能超过配置的上下文窗口")

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> ContextBudget:
        return cls(**{key: int(config[key]) for key in (
            "context_window", "input_limit", "output_limit", "safety_margin",
        ) if key in config})

    def validate(self, messages: list[dict[str, str]]) -> int:
        count = estimate_tokens(messages)
        if count > self.input_limit:
            raise ContextBudgetError(f"必要上下文超出输入预算：估算 {count}，上限 {self.input_limit}；请缩短剧本或提高预算")
        return count
