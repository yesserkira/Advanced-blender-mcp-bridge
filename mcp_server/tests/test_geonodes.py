"""v2.2: Geometry Nodes tool round-trip via fake Blender WS.

Validates the MCP tool wrappers, dry-run plumbing, and preset discovery.
The add-on capability (capabilities/geonodes.py) requires real Blender and
is exercised by the headless integration suite added in Phase D.
"""

from __future__ import annotations

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
async def test_create_modifier_with_new_group():
    out = await server.geonodes_create_modifier(object="Cube")
    assert out["object"] == "Cube"
    assert out["created_group"] is True


@pytest.mark.asyncio
async def test_create_modifier_with_existing_group():
    out = await server.geonodes_create_modifier(object="Cube", group="MyGroup")
    assert out["group"] == "MyGroup"
    assert out["created_group"] is False


@pytest.mark.asyncio
async def test_describe_group_returns_interface():
    out = await server.geonodes_describe_group(name="BMCP_ScatterOnSurface")
    assert "inputs" in out
    assert "outputs" in out
    assert any(i["identifier"] == "Input_1" for i in out["inputs"])


@pytest.mark.asyncio
async def test_set_input_by_name():
    out = await server.geonodes_set_input(object="Cube", input="Density", value=5.0)
    assert out["value"] == 5.0
    assert out["identifier"]


@pytest.mark.asyncio
async def test_set_input_dry_run():
    out = await server.geonodes_set_input(
        object="Cube", input="Density", value=5.0, dry_run=True,
    )
    assert out.get("dry_run") is True


@pytest.mark.asyncio
async def test_animate_input():
    kfs = [{"frame": 1, "value": 0.0}, {"frame": 60, "value": 10.0}]
    out = await server.geonodes_animate_input(
        object="Cube", input="Density", keyframes=kfs,
    )
    assert out["count"] == 2


@pytest.mark.asyncio
async def test_create_group():
    out = await server.geonodes_create_group(
        name="MyGN",
        inputs=[{"name": "Geometry", "socket_type": "NodeSocketGeometry"},
                {"name": "Density", "socket_type": "NodeSocketFloat", "default_value": 5.0}],
        outputs=[{"name": "Geometry", "socket_type": "NodeSocketGeometry"}],
    )
    assert out["created"] is True
    assert out["input_count"] == 2


@pytest.mark.asyncio
async def test_realize_dry_run_does_not_apply():
    out = await server.geonodes_realize(object="Cube", dry_run=True)
    assert out.get("dry_run") is True


@pytest.mark.asyncio
async def test_list_presets_returns_three():
    out = await server.geonodes_list_presets()
    names = {p["name"] for p in out["presets"]}
    assert names == {"scatter-on-surface", "array-along-curve", "displace-noise"}


@pytest.mark.asyncio
async def test_get_preset_returns_full_payload():
    out = await server.geonodes_get_preset(name="scatter-on-surface")
    assert "group" in out and "graph" in out


@pytest.mark.asyncio
async def test_apply_preset_no_object():
    out = await server.geonodes_apply_preset(preset="scatter-on-surface")
    assert out["preset"] == "scatter-on-surface"
    assert "group" in out
    assert "object" not in out


@pytest.mark.asyncio
async def test_apply_preset_with_object():
    out = await server.geonodes_apply_preset(
        preset="scatter-on-surface", object="Cube", modifier="MyGN",
    )
    assert out["object"] == "Cube"
    assert out["modifier"] == "MyGN"


@pytest.mark.asyncio
async def test_apply_preset_dry_run():
    out = await server.geonodes_apply_preset(
        preset="scatter-on-surface", object="Cube", dry_run=True,
    )
    assert out.get("dry_run") is True
