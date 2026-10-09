from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from starlette.websockets import WebSocketDisconnect
from ws.lifecycle import await_with_heartbeat, send_connected


class WebSocketLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_closed_transport_cancels_pending_inference(self) -> None:
        cancelled = asyncio.Event()

        class ClosedSocket:
            async def send_json(self, message):
                raise RuntimeError("Unexpected ASGI message 'websocket.send', after sending 'websocket.close'.")

        async def operation():
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()

        with patch("ws.lifecycle.HEARTBEAT_INTERVAL_SECONDS", 0.01):
            with self.assertRaises(WebSocketDisconnect):
                await await_with_heartbeat(ClosedSocket(), operation(), 1, True)
        self.assertTrue(cancelled.is_set())

    async def test_unrelated_runtime_errors_are_not_hidden(self) -> None:
        class BrokenSocket:
            async def send_json(self, message):
                raise RuntimeError("unrelated application bug")

        with self.assertRaisesRegex(RuntimeError, "unrelated application bug"):
            await send_connected(BrokenSocket(), {"type": "heartbeat"})
