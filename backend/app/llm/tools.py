from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from tools.contracts import ToolCall


@dataclass(frozen=True)
class ToolModelReply:
    content: str
    tool_calls: tuple[ToolCall, ...]
    wire_message: dict[str, Any]
    transport: str
    model_request_id: str | None = None


def parse_native_message(message: Any) -> ToolModelReply:
    if not isinstance(message, dict):
        raise ValueError("模型消息必须为对象")
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise ValueError("模型消息内容格式无效")
    calls = message.get("tool_calls", [])
    if not isinstance(calls, list):
        raise ValueError("工具调用列表格式无效")
    parsed: list[ToolCall] = []
    seen = set()
    for raw in calls:
        if not isinstance(raw, dict) or raw.get("type") != "function":
            raise ValueError("只支持 function 工具调用")
        provider_id = raw.get("id")
        if not isinstance(provider_id, str) or not provider_id or provider_id in seen:
            raise ValueError("供应商工具调用编号缺失或重复")
        seen.add(provider_id)
        function = raw.get("function", {})
        if not isinstance(function, dict):
            raise ValueError("工具函数定义格式无效")
        arguments = function.get("arguments")
        if not isinstance(arguments, str) or len(arguments.encode("utf-8")) > 65536:
            raise ValueError("工具参数格式或长度无效")
        parsed.append(ToolCall(name=function.get("name"), arguments=json.loads(arguments), provider_call_id=provider_id))
    if not parsed and not (content or "").strip():
        raise ValueError("模型未返回内容或工具调用")
    wire = {"role": "assistant", "content": content}
    if calls:
        wire["tool_calls"] = calls
    # Preserve opaque provider continuation data, but never expose it as a reasoning notebook or player log.
    if isinstance(message.get("reasoning_content"), str):
        wire["reasoning_content"] = message["reasoning_content"]
    return ToolModelReply(content or "", tuple(parsed), wire, "native_tools")


def parse_json_reply(raw: str) -> ToolModelReply:
    payload = json.loads(raw)
    if not isinstance(payload, dict) or set(payload) - {"content", "tool_calls"}:
        raise ValueError("JSON 工具回复格式无效")
    calls = []
    if not isinstance(payload.get("tool_calls", []), list):
        raise ValueError("JSON 工具调用列表格式无效")
    for call in payload.get("tool_calls", []):
        if not isinstance(call, dict) or set(call) - {"name", "arguments"}:
            raise ValueError("JSON 工具调用只能包含 name 和 arguments")
        calls.append(ToolCall.model_validate(call))
    content = payload.get("content", "")
    if not isinstance(content, str):
        raise ValueError("JSON 工具回复内容无效")
    if not calls and not content.strip():
        raise ValueError("JSON 回复没有内容或工具调用")
    return ToolModelReply(content, tuple(calls), {"role": "assistant", "content": raw}, "validated_action_json")


def json_transport_messages(messages: list[dict[str, Any]], definitions: list[dict[str, Any]]) -> list[dict[str, str]]:
    converted = [{"role": message["role"] if message["role"] in {"system", "user", "assistant"} else "user",
                  "content": message.get("content") or json.dumps(message, ensure_ascii=False)} for message in messages]
    converted.append({"role": "user", "content": "[FUNCTION_CALL_JSON]\n可用工具：" + json.dumps(definitions, ensure_ascii=False)
        + '\n只返回 {"content":"结束本回合时的简短摘要，可为空","tool_calls":[{"name":"工具名","arguments":{}}]}。不调用工具时返回空列表。'})
    return converted
