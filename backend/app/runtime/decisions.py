from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError

from runtime.contracts import ExecutionBudgetError, execution_frame
from tools.contracts import ToolResult


def accept_control_reply(dm: Any, scope: Any, reply: Any, definition: tuple) -> str:
    """Record a validated decision proposal; its gameplay effect belongs to the caller's transaction."""
    name, schema, field = definition
    if len(reply.tool_calls) != 1:
        raise ValueError("角色决策必须返回恰好一个指定函数调用")
    call = reply.tool_calls[0]
    frame = execution_frame.get()
    turn_id = frame.turn_id if frame else reply.model_request_id
    request_id = frame.request_id if frame else reply.model_request_id
    call_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{scope.game_id}:{reply.model_request_id}:decision"))
    dm.runtime_store.enqueue_tool(scope, call_id, turn_id, request_id, call.name, call.arguments,
                                  reply.model_request_id, call.provider_call_id)
    result = ToolResult(tool_call_id=call_id, status="rejected", code="INVALID_DECISION")
    try:
        if call.name != name:
            raise ValueError("角色决策调用了未授权函数")
        args = schema.model_validate(call.arguments)
        if frame:
            key = f"{scope.actor_kind}:{scope.actor_role_id}"
            if frame.tool_counts.get(key, 0) >= dm.workflow_settings.max_tool_calls_per_role_turn:
                raise ExecutionBudgetError("角色决策工具已达到 YAML 上限")
            frame.tool_counts[key] = frame.tool_counts.get(key, 0) + 1
        value = args.model_dump()[field]
        if name == "cast_role_vote" and value not in dm._stage_vote_candidate_ids():
            raise ValueError("投票目标不在本幕候选范围内")
        dm.runtime_store.assert_scope(scope)
        result = ToolResult(tool_call_id=call_id, status="succeeded", code="DECISION_VALIDATED",
                            data={field: value}, gameplay_committed=False)
        return value
    except (ValueError, ValidationError):
        raise
    finally:
        dm.runtime_store.finish_tool(call_id, result.model_dump())
