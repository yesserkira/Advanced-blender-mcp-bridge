"""Shared test fixtures."""

import asyncio
import json
import pytest
import websockets


class FakeBlenderServer:
    """Minimal fake Blender WS server for testing."""

    def __init__(self, host="127.0.0.1", port=19876):
        self.host = host
        self.port = port
        self._server = None
        self._handlers: dict[str, callable] = {
            "ping": lambda args: "pong",
            "scene.get": lambda args: {
                "scene": "Scene",
                "frame": {"current": 1, "start": 1, "end": 250, "fps": 24},
                "object_counts": {"MESH": 1, "LIGHT": 1, "CAMERA": 1},
                "active_camera": "Camera",
            },
        }

    async def _handler(self, websocket):
        async for raw in websocket:
            msg = json.loads(raw)
            op = msg.get("op", "")
            handler = self._handlers.get(op)
            if handler:
                result = handler(msg.get("args", {}))
                response = {"id": msg.get("id"), "ok": True, "result": result}
            else:
                response = {
                    "id": msg.get("id"),
                    "ok": False,
                    "error": {"code": "NOT_FOUND", "message": f"Unknown op: {op}"},
                }
            await websocket.send(json.dumps(response))

    async def start(self):
        self._server = await websockets.serve(self._handler, self.host, self.port)

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()


@pytest.fixture
async def fake_blender():
    """Start a fake Blender WS server for the duration of the test."""
    server = FakeBlenderServer()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
def blender_token():
    return "test-token-for-testing"
