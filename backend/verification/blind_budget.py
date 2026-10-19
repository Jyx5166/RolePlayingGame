"""Durable, single-process paid-call guard for blind acceptance; never retries.

All model clients in a run must share ONE MoneyRequestLedger. Reservations use
the entire validated input/output limits, with cache misses charged for all
input. The ledger contains accounting metadata, never prompts or reasoning.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

from llm.base import BaseLLM
from llm.openai_compatible import OpenAICompatibleLLM
from llm.tools import ToolModelReply, json_transport_messages


class BlindBudgetError(RuntimeError):
    """No provider may be invoked after this guard rejects a reservation."""


class BudgetAmbiguityError(BlindBudgetError):
    """Usage contradicts the conservative reservation; further calls stop."""


def _decimal(value: Decimal | str | int) -> Decimal:
    if isinstance(value, (float, bool)):
        raise ValueError("Money must use Decimal, a decimal string, or an integer")
    result = Decimal(value)
    if not result.is_finite() or result < 0:
        raise ValueError("Money must be finite and nonnegative")
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Pricing:
    input_cny_per_million: Decimal | str | int
    output_cny_per_million: Decimal | str | int
    source: str
    verified_at: str
    model: str = ""

    def __post_init__(self) -> None:
        for name in ("input_cny_per_million", "output_cny_per_million"):
            value = _decimal(getattr(self, name))
            if value <= 0:
                raise ValueError("Paid-call rates must be positive")
            object.__setattr__(self, name, value)
        if not self.source or not self.verified_at:
            raise ValueError("Verified pricing source and date are required")

    def cost(self, prompt_tokens: int, completion_tokens: int) -> Decimal:
        return (self.input_cny_per_million * prompt_tokens
                + self.output_cny_per_million * completion_tokens) / Decimal(1_000_000)

    def as_dict(self) -> dict[str, str]:
        return {"input_cny_per_million": str(self.input_cny_per_million),
                "output_cny_per_million": str(self.output_cny_per_million),
                "source": self.source, "verified_at": self.verified_at,
                "model": self.model, "input_cache_policy": "all_input_cache_miss"}


def _usage(usage: Any) -> tuple[dict[str, int] | None, str]:
    if not isinstance(usage, dict):
        return None, "missing"
    tokens: dict[str, int] = {}
    def inspect(values: dict[str, Any], prefix: str = "") -> str | None:
        for key, value in values.items():
            if isinstance(value, dict):
                invalid = inspect(value, prefix + str(key) + ".")
                if invalid:
                    return invalid
            elif str(key).endswith("tokens"):
                if isinstance(value, int) and not isinstance(value, bool) and value < 0:
                    return "negative"
                if not isinstance(value, int) or isinstance(value, bool):
                    return "malformed"
                tokens[prefix + str(key)] = value
        return None
    invalid = inspect(usage)
    if invalid:
        return None, invalid
    if not {"prompt_tokens", "completion_tokens"} <= tokens.keys():
        return None, "missing"
    if "total_tokens" in tokens and tokens["total_tokens"] != tokens["prompt_tokens"] + tokens["completion_tokens"]:
        return None, "malformed"
    return tokens, "verified"


class MoneyRequestLedger:
    """Share this instance among clients; persistence must succeed before dispatch.

    Resume retains pending reservations. Parallel operating-system processes
    must not write the same ledger; the acceptance runner uses one process.
    """
    def __init__(self, path: str | Path, pricing: Pricing, *, request_limit: int = 300,
                 max_cny: Decimal | str | int = "20", resume: bool = False) -> None:
        if isinstance(request_limit, bool) or not isinstance(request_limit, int) or not 1 <= request_limit <= 300:
            raise ValueError("Request limit must be an integer between 1 and 300")
        self.path = Path(path)
        self.pricing = pricing
        self.request_limit = request_limit
        self.max_cny = _decimal(max_cny)
        if not 0 < self.max_cny <= Decimal(20):
            raise ValueError("The authorized hard cap is CNY 20")
        self.calls: list[dict[str, Any]] = []
        self.frozen_reason: str | None = None
        self._lock = threading.RLock()
        if self.path.exists():
            if not resume:
                raise BlindBudgetError("Ledger exists; explicitly resume instead of resetting paid calls")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (data["pricing"] != pricing.as_dict() or data["max_cny"] != str(self.max_cny)
                    or data["request_limit"] != request_limit):
                raise BlindBudgetError("Resume requires identical verified pricing and limits")
            self.calls = data["calls"]
            self.frozen_reason = data.get("frozen_reason")
            for row in self.calls:
                if row["status"] == "reserved":
                    row.update(status="interrupted_unknown", usage_status="missing")
            if len(self.calls) > self.request_limit or self.accounted_upper_cny > self.max_cny:
                self.frozen_reason = "resumed ledger exceeds configured limits"
        self.save()

    @property
    def accounted_upper_cny(self) -> Decimal:
        return sum((_decimal(row["accounted_upper_cny"]) for row in self.calls), Decimal(0))

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {"max_cny": str(self.max_cny), "accounted_upper_cny": str(self.accounted_upper_cny),
                    "remaining_cny": str(max(Decimal(0), self.max_cny - self.accounted_upper_cny)),
                    "reserved_requests": len(self.calls), "request_limit": self.request_limit,
                    "automatic_retries": 0, "frozen_reason": self.frozen_reason}

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".tmp")
            data = {"version": 1, **self.summary(), "pricing": self.pricing.as_dict(), "calls": self.calls}
            try:
                with temporary.open("w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            except Exception:
                self.frozen_reason = "ledger persistence failed"
                raise BlindBudgetError("Paid-call ledger could not be saved; further calls blocked") from None

    def reserve(self, *, input_limit: int, output_limit: int, context: Mapping[str, Any],
                model: str, transport: str, estimated_input_tokens: int) -> dict[str, Any]:
        with self._lock:
            if self.frozen_reason:
                raise BlindBudgetError("Paid calls are frozen: " + self.frozen_reason)
            for value in (input_limit, output_limit):
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ValueError("Reservation token limits must be positive integers")
            if self.pricing.model and model != self.pricing.model:
                raise BlindBudgetError("Client model differs from verified pricing model")
            if len(self.calls) >= self.request_limit:
                raise BlindBudgetError("Shared paid request limit reached")
            reservation = self.pricing.cost(input_limit, output_limit)
            if self.accounted_upper_cny + reservation > self.max_cny:
                raise BlindBudgetError("Shared CNY cap cannot cover the full next reservation")
            row = {"number": len(self.calls) + 1, "status": "reserved", "reserved_at": _now(),
                   "script": str(context.get("script", "")), "phase": str(context.get("phase", "")),
                   "actor": str(context.get("actor", "")), "purpose": str(context.get("purpose", "")),
                   "model": model, "transport": transport, "estimated_input_tokens": estimated_input_tokens,
                   "reserved_input_tokens": input_limit, "reserved_completion_tokens": output_limit,
                   "reserved_cny": str(reservation), "accounted_upper_cny": str(reservation),
                   "usage": None, "usage_status": "pending", "finish_reason": None}
            self.calls.append(row)
            self.save()
            return row

    def finish(self, row: dict[str, Any], *, status: str, usage: Any, metadata: Mapping[str, Any],
               latency_ms: float, error_type: str | None = None) -> None:
        with self._lock:
            parsed, usage_status = _usage(usage)
            row.update(status=status, completed_at=_now(), latency_ms=round(latency_ms, 2),
                       usage=parsed, usage_status=usage_status,
                       finish_reason=metadata.get("finish_reason"), provider_invoked=metadata.get("provider_invoked"))
            if error_type:
                # Error text/provider bodies can contain keys; store only the exception class.
                row["error_type"] = error_type
            ambiguity = usage_status == "negative"
            if parsed is not None:
                actual = self.pricing.cost(parsed["prompt_tokens"], parsed["completion_tokens"])
                row["provider_usage_cost_cny"] = str(actual)
                reservation = _decimal(row["reserved_cny"])
                ambiguity = (actual > reservation or parsed["prompt_tokens"] > row["reserved_input_tokens"]
                             or parsed["completion_tokens"] > row["reserved_completion_tokens"])
                if ambiguity:
                    row["accounted_upper_cny"] = str(max(reservation, actual))
                elif status == "completed":
                    row["accounted_upper_cny"] = str(actual)
            if ambiguity:
                row["usage_status"] = "ambiguous_" + usage_status
                self.frozen_reason = "provider usage contradicted the reserved bounds"
            self.save()
            if ambiguity:
                raise BudgetAmbiguityError("Provider usage contradicted the reservation; all future paid calls blocked")


class BudgetedLLM(BaseLLM):
    def __init__(self, delegate: BaseLLM, ledger: MoneyRequestLedger,
                 context: Mapping[str, Any] | Callable[[], Mapping[str, Any]]) -> None:
        self.delegate, self.ledger, self.context = delegate, ledger, context
        self.budget = delegate.budget
        self.supports_native_tools = delegate.supports_native_tools
        self.provider = getattr(delegate, "provider", delegate.__class__.__name__)
        self.model = getattr(delegate, "model", "")

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    @property
    def budget(self) -> Any:
        return self.delegate.budget

    @budget.setter
    def budget(self, value: Any) -> None:
        self.delegate.budget = value

    @property
    def model(self) -> str:
        return getattr(self.delegate, "model", "")

    @model.setter
    def model(self, value: str) -> None:
        self.delegate.model = value

    @property
    def reasoning_effort(self) -> str:
        return getattr(self.delegate, "reasoning_effort", "")

    @reasoning_effort.setter
    def reasoning_effort(self, value: str) -> None:
        self.delegate.reasoning_effort = value

    def call_metadata(self) -> dict[str, Any]:
        return {**self.delegate.call_metadata(), "usage": self.last_usage,
                "finish_reason": self.last_finish_reason, "provider_invoked": self.last_provider_invoked}

    async def _guard(self, messages: list[dict[str, Any]], definitions: list[dict[str, Any]] | None,
                     transport: str) -> Any:
        self.reset_call_metadata()
        self.delegate.reset_call_metadata()
        self.last_provider_invoked = False
        if definitions is None:
            budget_messages = messages
        elif transport == "native_tools":
            if not self.supports_native_tools:
                raise BlindBudgetError("Client does not support native tools")
            budget_messages = [*messages, {"role": "user", "content": json.dumps(definitions, ensure_ascii=False)}]
        elif transport == "validated_action_json":
            budget_messages = json_transport_messages(messages, definitions)
        else:
            raise BlindBudgetError("Unknown tool transport")
        estimate = self.budget.validate(budget_messages)
        context = self.context() if callable(self.context) else self.context
        row = self.ledger.reserve(input_limit=self.budget.input_limit, output_limit=self.budget.output_limit,
                                  context=context, model=self.model, transport=transport,
                                  estimated_input_tokens=estimate)
        started = time.perf_counter()
        status, error_type = "failed", None
        try:
            if definitions is None:
                result = await self.delegate.chat(messages)
            else:
                result = await self.delegate.chat_tools(messages, definitions, transport=transport)
            status = "completed"
            return result
        except asyncio.CancelledError:
            status, error_type = "canceled", "CancelledError"
            raise
        except Exception as exc:
            error_type = type(exc).__name__
            # Never let provider error bodies or keys escape into the runner report.
            raise BlindBudgetError("Provider call failed: " + error_type) from None
        finally:
            metadata = self.delegate.call_metadata()
            self.last_usage = metadata.get("usage")
            self.last_finish_reason = metadata.get("finish_reason")
            self.last_provider_invoked = metadata.get("provider_invoked")
            raw_usage = getattr(self.delegate, "raw_provider_usage", self.last_usage)
            self.ledger.finish(row, status=status, usage=raw_usage, metadata=metadata,
                               latency_ms=(time.perf_counter() - started) * 1000, error_type=error_type)

    async def chat(self, messages: list[dict[str, str]]) -> str:
        return await self._guard(messages, None, "chat")

    async def chat_tools(self, messages: list[dict[str, Any]], definitions: list[dict[str, Any]],
                         *, transport: str = "native_tools") -> ToolModelReply:
        return await self._guard(messages, definitions, transport)


class _UsageAuditedOpenAICompatibleLLM(OpenAICompatibleLLM):
    raw_provider_usage: Any = None

    def reset_call_metadata(self) -> None:
        super().reset_call_metadata()
        self.raw_provider_usage = None

    async def _request(self, payload: dict[str, Any], headers: dict[str, str]) -> Any:
        data = await super()._request(payload, headers)
        if isinstance(data, dict):
            self.raw_provider_usage = data.get("usage")
        return data


class BudgetedOpenAICompatibleLLM(BudgetedLLM):
    def __init__(self, model: str, base_url: str, api_key: str, timeout: float = 30.0,
                 *, ledger: MoneyRequestLedger,
                 context: Mapping[str, Any] | Callable[[], Mapping[str, Any]],
                 budget: Any = None, reasoning_effort: str = "") -> None:
        super().__init__(_UsageAuditedOpenAICompatibleLLM(model, base_url, api_key, timeout,
                         budget=budget, reasoning_effort=reasoning_effort), ledger, context)
