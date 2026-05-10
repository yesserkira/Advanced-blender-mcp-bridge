"""v2.2: snapshot + MCP resource round-trip via fake Blender WS.

The add-on side (capabilities/snapshot.py) is exercised by the headless
Blender integration suite (Phase D). Here we verify the MCP-side wiring:

- The two `blender://scene/...` resources are registered.
- `resource_scene_current()` and `resource_scene_summary()` return JSON.
- Calling the underlying op via _call works.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("BLENDER_MCP_TOKEN", "test")
os.environ.setdefault("BLENDER_MCP_URL", "ws://127.0.0.1:19876")

from blender_mcp import server  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch, fake_blender):
    monkeypatch.setenv("BLENDER_MCP_TOKEN", "test")
    monkeypatch.setenv("BLENDER_MCP_URL", f"ws://{fake_blender.host}:{fake_blender.port}")
    server._bl = None
    server._policy = None
    yield
    if server._bl is not None:
        try:
            import asyncio
            asyncio.get_event_loop().run_until_complete(server._bl.close())
        except Exception:
            pass
        server._bl = None
    server._policy = None


@pytest.mark.asyncio
async def test_scene_current_resource_returns_full_payload():
    body = await server.resource_scene_current()
    data = json.loads(body)
    assert data["scene"] == "Scene"
    assert "objects" in data
    assert "collections" in data
    assert "hash" in data
    assert data["counts"]["objects"] == 3


@pytest.mark.asyncio
async def test_scene_summary_resource_omits_per_object_data():
    body = await server.resource_scene_summary()
    data = json.loads(body)
    assert "counts" in data
    assert "objects" not in data
    assert "collections" not in data
    assert "hash" in data


def test_resources_are_registered_with_correct_uris():
    """FastMCP exposes registered resource URIs via _resource_manager."""
    rm = server.mcp._resource_manager
    uris = {str(r.uri) for r in rm._resources.values()}
    assert "blender://scene/current" in uris
    assert "blender://scene/summary" in uris
