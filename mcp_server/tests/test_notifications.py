"""v2.3: scene-change notification round-trip via fake Blender WS."""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("BLENDER_MCP_TOKEN", "test")

from blender_mcp.blender_client import BlenderWS  # noqa: E402


@pytest.mark.asyncio
async def test_notification_handler_invoked_on_broadcast(fake_blender):
    """A frame pushed by the server should reach the registered handler."""
    received: list[dict] = []
    cond = asyncio.Event()

    async def handler(frame: dict) -> None:
        received.append(frame)
        cond.set()

    bl = BlenderWS(url=f"ws://{fake_blender.host}:{fake_blender.port}", token="test")
    bl.set_notification_handler(handler)
    try:
        # Establish the connection by issuing a request.
        await bl.call("ping")

        # Push a notification from the "add-on" side.
        await fake_blender.broadcast({
            "type": "notification",
            "event": "scene.changed",
            "uri": "blender://scene/current",
            "hash": "abc1234567890def",
        })

        await asyncio.wait_for(cond.wait(), timeout=2.0)
    finally:
        await bl.close()

    assert len(received) == 1
    assert received[0]["event"] == "scene.changed"
    assert received[0]["hash"] == "abc1234567890def"


@pytest.mark.asyncio
async def test_response_after_notification(fake_blender):
    """A normal call/response must keep working after a notification."""
    seen = asyncio.Event()

    async def handler(frame):  # noqa: ARG001
        seen.set()

    bl = BlenderWS(url=f"ws://{fake_blender.host}:{fake_blender.port}", token="test")
    bl.set_notification_handler(handler)
    try:
        await bl.call("ping")
        await fake_blender.broadcast({
            "type": "notification",
            "event": "scene.changed",
            "uri": "blender://scene/current",
            "hash": "h1",
        })
        await asyncio.wait_for(seen.wait(), timeout=2.0)
        # And subsequent calls still work.
        out = await bl.call("ping")
        assert out == "pong"
    finally:
        await bl.close()


@pytest.mark.asyncio
async def test_notifications_dropped_with_no_handler(fake_blender):
    """Notifications must not crash the reader when no handler is set."""
    bl = BlenderWS(url=f"ws://{fake_blender.host}:{fake_blender.port}", token="test")
    # No handler.
    try:
        await bl.call("ping")
        await fake_blender.broadcast({
            "type": "notification",
            "event": "scene.changed",
            "uri": "blender://scene/current",
            "hash": "h2",
        })
        # Give the reader time to process the dropped frame.
        await asyncio.sleep(0.1)
        # Connection still alive.
        out = await bl.call("ping")
        assert out == "pong"
    finally:
        await bl.close()
