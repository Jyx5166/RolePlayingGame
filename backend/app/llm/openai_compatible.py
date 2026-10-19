from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .base import BaseLLM, ModelOutputTruncated
from .budget import ContextBudget
from .tools import ToolModelReply, parse_native_message


class OpenAICompatibleLLM(BaseLLM):
    supports_native_tools = True
    def __init__(self, model: str, base_url: str, api_key: str, timeout: float = 30.0,
                 *, budget: ContextBudget | None = None, reasoning_effort: str = "") -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.provider = "openai_compatible"
        self.budget = budget or ContextBudget()
        self.reasoning_effort = reasoning_effort

    def call_metadata(self):
        return {**super().call_metadata(),'reasoning_effort':self.reasoning_effort or 'provider_default',
                'output_limit':self.budget.output_limit,'timeout_seconds':self.timeout}

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.reset_call_metadata()
        self.last_provider_invoked = False
        self.budget.validate(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            "stream": False,
            "max_tokens": self.budget.output_limit,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            # HTTP read timeout only bounds silence between chunks, not total keep-alive time.
            data = await asyncio.wait_for(self._request(payload, headers), timeout=self.timeout)
            if not isinstance(data, dict):
                raise ValueError("response must be an object")
            usage = data.get("usage")
            if isinstance(usage, dict):
                self.last_usage = {key: int(value) for key, value in usage.items()
                                   if key.endswith("tokens") and isinstance(value, int) and not isinstance(value, bool) and value >= 0}
            choice = data["choices"][0]
            if not isinstance(choice, dict):
                raise ValueError("choice must be an object")
            self.last_finish_reason = choice.get("finish_reason")
            content = choice["message"]["content"]
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            raise RuntimeError(
                f"大模型响应超时（请求限时 {self.timeout:g} 秒），请稍后重试或调大 LLM_TIMEOUT_SECONDS"
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = _response_error_detail(exc.response)
            raise RuntimeError(f"大模型服务返回 HTTP {exc.response.status_code}：{detail}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"无法连接大模型服务：{exc.__class__.__name__}") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError("大模型返回的数据格式不正确") from exc

        if self.last_finish_reason == "length":
            raise ModelOutputTruncated("大模型输出达到额度而被截断；本次结果不作为有效行动，请提高输出预算或缩短输入")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("大模型返回了空内容")
        return content

    async def _request(self, payload: dict[str, Any], headers: dict[str, str]) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            self.last_provider_invoked = True
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    async def chat_tools(self, messages: list[dict[str, Any]], definitions: list[dict[str, Any]],
                         *, transport: str = "native_tools") -> ToolModelReply:
        if transport == "validated_action_json":
            return await super().chat_tools(messages, definitions, transport=transport)
        self.reset_call_metadata()
        self.last_provider_invoked = False
        # Count tool schemas and provider continuation fields against the same input budget.
        import json
        self.budget.validate([*messages, {"role": "user", "content": json.dumps(definitions, ensure_ascii=False)}])
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "tools": definitions,
            "tool_choice": "auto", "stream": False, "temperature": 0.7, "max_tokens": self.budget.output_limit}
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        try:
            data = await asyncio.wait_for(self._request(payload, {"Authorization": f"Bearer {self.api_key}"}), timeout=self.timeout)
            usage = data.get("usage")
            if isinstance(usage, dict):
                self.last_usage = {key: value for key, value in usage.items() if key.endswith("tokens") and isinstance(value, int) and not isinstance(value, bool) and value >= 0}
            choice = data["choices"][0]
            self.last_finish_reason = choice.get("finish_reason")
            if self.last_finish_reason == "length":
                raise ModelOutputTruncated("工具调用输出被截断，不能执行")
            return parse_native_message(choice["message"])
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            raise RuntimeError(f"大模型工具调用超时（请求限时 {self.timeout:g} 秒）") from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"大模型服务返回 HTTP {exc.response.status_code}：{_response_error_detail(exc.response)}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"无法连接大模型服务：{exc.__class__.__name__}") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError("大模型工具调用回复格式无效") from exc


def _response_error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
        error = data.get("error") if isinstance(data, dict) else None
        detail = error.get("message") if isinstance(error, dict) else None
        if detail:
            return str(detail)[:300]
    except (TypeError, ValueError):
        pass
    return response.text.strip()[:300] or "未提供错误详情"
