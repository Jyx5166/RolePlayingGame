from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from typing import Any


MAX_REQUEST_BYTES = 5 * 1024 * 1024 + 64 * 1024
MAX_SCRIPT_BYTES = 5 * 1024 * 1024
MAX_SCRIPT_DEPTH = 20
MAX_SCRIPT_NODES = 50_000
MAX_SCRIPT_STRING_LENGTH = 100_000
MAX_SCRIPT_ROLES = 50


class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def retry_after(self, keys: list[str]) -> int:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                self._prune(key, now)
            blocked_until = max(
                (
                    attempts[0] + self.window_seconds
                    for key in keys
                    if len(attempts := self._attempts[key]) >= self.max_attempts
                ),
                default=now,
            )
        return max(0, int(blocked_until - now + 0.999))

    def record_failure(self, keys: list[str]) -> None:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                self._prune(key, now)
                self._attempts[key].append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def _prune(self, key: str, now: float) -> None:
        attempts = self._attempts[key]
        threshold = now - self.window_seconds
        while attempts and attempts[0] <= threshold:
            attempts.popleft()
        if not attempts:
            self._attempts.pop(key, None)


def validate_script_payload(script: dict[str, Any]) -> None:
    encoded_size = len(
        json.dumps(script, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    if encoded_size > MAX_SCRIPT_BYTES:
        raise ValueError("剧本文件不能超过 5 MB")
    roles = script.get("roles")
    if isinstance(roles, list) and len(roles) > MAX_SCRIPT_ROLES:
        raise ValueError(f"剧本角色不能超过 {MAX_SCRIPT_ROLES} 个")

    node_count = 0
    stack: list[tuple[Any, int]] = [(script, 1)]
    while stack:
        value, depth = stack.pop()
        node_count += 1
        if node_count > MAX_SCRIPT_NODES:
            raise ValueError("剧本结构过于复杂")
        if depth > MAX_SCRIPT_DEPTH:
            raise ValueError("剧本嵌套层级过深")
        if isinstance(value, str) and len(value) > MAX_SCRIPT_STRING_LENGTH:
            raise ValueError("剧本单个文本字段过长")
        if isinstance(value, dict):
            stack.extend((key, depth + 1) for key in value)
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
