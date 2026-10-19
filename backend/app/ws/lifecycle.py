from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar

from starlette.websockets import WebSocket, WebSocketDisconnect

from .protocol import PROTOCOL_VERSION


HEARTBEAT_INTERVAL_SECONDS = 5.0
T = TypeVar("T")


async def send_connected(ws: WebSocket, message: dict[str, Any]) -> None:
    try:
        await ws.send_json(message)
    except RuntimeError as exc:
        if "after sending 'websocket.close'" in str(exc) or "once a close message has been sent" in str(exc):
            raise WebSocketDisconnect(code=1006) from exc
        raise


def heartbeat_message(game_id: int, protocol_v1: bool) -> dict[str, Any]:
    payload = {"type": "heartbeat"}
    if not protocol_v1:
        return payload
    return {
        "protocol_version": PROTOCOL_VERSION,
        "kind": "event",
        "type": "heartbeat",
        "event_id": None,
        "request_id": None,
        "game_id": game_id,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


async def await_with_heartbeat(
    ws: WebSocket,
    operation: Awaitable[T],
    game_id: int,
    protocol_v1: bool,
    *, on_tick: Callable[[], Awaitable[None]] | None = None,
) -> T:
    task = asyncio.ensure_future(operation)
    last_heartbeat = asyncio.get_running_loop().time()
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.1 if on_tick else HEARTBEAT_INTERVAL_SECONDS)
            if on_tick:
                await on_tick()
            if done:
                return task.result()
            if asyncio.get_running_loop().time()-last_heartbeat>=HEARTBEAT_INTERVAL_SECONDS:
                await send_connected(ws, heartbeat_message(game_id, protocol_v1))
                last_heartbeat=asyncio.get_running_loop().time()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
