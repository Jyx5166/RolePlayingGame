from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .base import BaseLLM
from .budget import ContextBudget


class OpenAICompatibleLLM(BaseLLM):
    def __init__(self, model: str, base_url: str, api_key: str, timeout: float = 30.0,
                 *, budget: ContextBudget | None = None, reasoning_effort: str = "") -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.provider = "openai_compatible"
        self.budget = budget or ContextBudget()
        self.reasoning_effort = reasoning_effort

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.reset_call_metadata()
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
            raise RuntimeError("大模型输出达到额度而被截断；本次结果不作为有效行动，请提高输出预算或缩短输入")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("大模型返回了空内容")
        return content

    async def _request(self, payload: dict[str, Any], headers: dict[str, str]) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()


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
