from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from runtime.contracts import ExecutionBudgetError, RuntimeAccessError, RuntimeScope, execution_frame
from runtime.store import RuntimeStore
from workflow_config import WorkflowSettings


async def recorded_model_call(store: RuntimeStore, settings: WorkflowSettings, scope: RuntimeScope,
                              model_id: str, client: Any, messages: list[dict[str, Any]], transport: str,
                              operation: Callable[[], Awaitable[Any]], metadata: dict[str, Any]) -> Any:
    frame = execution_frame.get()
    turn_id = frame.turn_id if frame else model_id
    epoch = store.assert_scope(scope)["phase_epoch"]
    store.start_model(scope, model_id, turn_id, transport, messages, metadata)
    started = time.perf_counter()
    output = None
    status = "failed"
    error = ""
    try:
        if frame is not None:
            key = f"{scope.actor_kind}:{scope.actor_role_id}"
            used = frame.model_counts.get(key, 0)
            if used >= settings.max_model_requests_per_role_turn:
                status = "rejected"
                raise ExecutionBudgetError("本角色回合的模型请求次数已达到 YAML 上限")
            frame.model_counts[key] = used + 1
        value = await operation()
        output = value.wire_message if hasattr(value, "wire_message") else {"content": value}
        store.assert_scope(scope, expected_epoch=epoch)
        status = "completed"
        return value
    except asyncio.CancelledError:
        status = "cancelled"
        error = "请求已取消，供应商最终完成与计费情况可能未知"
        raise
    except Exception as exc:
        if isinstance(exc, RuntimeAccessError):
            status = "rejected"
        error = f"{type(exc).__name__}: {exc}"
        key = getattr(client, "api_key", "")
        if key:
            error = error.replace(key, "[REDACTED]")
        raise
    finally:
        fields = {**metadata, **client.call_metadata(), "latency_ms": round((time.perf_counter()-started)*1000, 2)}
        store.finish_model(model_id, status, output, fields, error)
