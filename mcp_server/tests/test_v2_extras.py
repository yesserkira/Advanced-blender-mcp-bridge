"""Tests for v2.4 spatial helpers, v2.5 selection/collections/object ops, and rename."""

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


# ===========================================================================
# rename
# ===========================================================================


@pytest.mark.asyncio
async def test_rename():
    out = await server.rename(kind="object", from_name="Cube", to_name="MyCube")
    assert out["kind"] == "object"
    assert out["final_name"] == "MyCube"


# ===========================================================================
# Spatial helpers (v2.4)
# ===========================================================================


@pytest.mark.asyncio
async def test_place_above():
    out = await server.place_above(object="Sphere", target="Cube", gap=0.1)
    assert out["object"] == "Sphere"
    assert out["target"] == "Cube"
    assert "location" in out


@pytest.mark.asyncio
async def test_place_above_ground():
    out = await server.place_above(object="Sphere", target="ground")
    assert out["target"] == "ground"


@pytest.mark.asyncio
async def test_align_to():
    out = await server.align_to(
        object="Sphere", target="Cube", axes=["x", "z"], mode="min",
    )
    assert out["object"] == "Sphere"
    assert out["mode"] == "min"


@pytest.mark.asyncio
async def test_array_around():
    out = await server.array_around(object="Post", count=8, radius=3.0)
    assert out["count"] == 8
    assert len(out["created"]) == 8


@pytest.mark.asyncio
async def test_distribute():
    out = await server.distribute(
        objects=["A", "B", "C"], start=[0, 0, 0], end=[10, 0, 0],
    )
    assert out["count"] == 3


@pytest.mark.asyncio
async def test_look_at_target():
    out = await server.look_at(object="Camera", target="Cube")
    assert out["object"] == "Camera"
    assert out["target"] == "Cube"


@pytest.mark.asyncio
async def test_look_at_point():
    out = await server.look_at(object="Camera", point=[1, 2, 3])
    assert out["object"] == "Camera"
    assert out["point"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_bbox_info():
    out = await server.bbox_info(object="Cube")
    assert out["object"] == "Cube"
    assert out["min"] == [-1, -1, -1]
    assert out["max"] == [1, 1, 1]
    assert out["size"] == [2, 2, 2]
    assert out["center"] == [0, 0, 0]


# ===========================================================================
# Selection (v2.5)
# ===========================================================================


@pytest.mark.asyncio
async def test_select():
    out = await server.select(objects=["Cube", "Sphere"])
    assert out["count"] == 2
    assert out["active"] == "Sphere"


@pytest.mark.asyncio
async def test_select_with_active():
    out = await server.select(objects=["Cube", "Sphere"], active="Cube")
    assert out["active"] == "Cube"


@pytest.mark.asyncio
async def test_deselect_all():
    out = await server.deselect_all()
    assert out["deselected_count"] == 3


@pytest.mark.asyncio
async def test_set_active():
    out = await server.set_active(object="Cube")
    assert out["object"] == "Cube"
    assert out["selected"] is True


@pytest.mark.asyncio
async def test_set_active_no_select():
    out = await server.set_active(object="Cube", select=False)
    assert out["selected"] is False


@pytest.mark.asyncio
async def test_select_all():
    out = await server.select_all()
    assert out["count"] == 5


@pytest.mark.asyncio
async def test_select_all_filtered():
    out = await server.select_all(type="MESH")
    assert out["type"] == "MESH"


# ===========================================================================
# Object ops (v2.5)
# ===========================================================================


@pytest.mark.asyncio
async def test_duplicate_object():
    out = await server.duplicate_object(object="Cube")
    assert out["original"] == "Cube"
    assert out["new_name"] == "Cube.copy"
    assert out["linked"] is False


@pytest.mark.asyncio
async def test_duplicate_object_linked():
    out = await server.duplicate_object(object="Cube", linked=True, name="CubeLinked")
    assert out["linked"] is True
    assert out["new_name"] == "CubeLinked"


@pytest.mark.asyncio
async def test_set_visibility():
    out = await server.set_visibility(object="Cube", viewport=False, render=True)
    assert "Cube" in out["objects"]
    assert out["viewport"] is False
    assert out["render"] is True


@pytest.mark.asyncio
async def test_set_visibility_batch():
    out = await server.set_visibility(objects=["Cube", "Sphere"], viewport=True)
    assert len(out["objects"]) == 2


@pytest.mark.asyncio
async def test_set_parent():
    out = await server.set_parent(parent="Empty", child="Cube")
    assert out["parent"] == "Empty"
    assert "Cube" in out["children"]


@pytest.mark.asyncio
async def test_set_parent_multi():
    out = await server.set_parent(parent="Empty", children=["Cube", "Sphere"])
    assert len(out["children"]) == 2


@pytest.mark.asyncio
async def test_clear_parent():
    out = await server.clear_parent(object="Cube")
    assert "Cube" in out["objects"]
    assert out["keep_transform"] is True


@pytest.mark.asyncio
async def test_clear_parent_batch():
    out = await server.clear_parent(objects=["Cube", "Sphere"], keep_transform=False)
    assert len(out["objects"]) == 2
    assert out["keep_transform"] is False


# ===========================================================================
# Collections (v2.5)
# ===========================================================================


@pytest.mark.asyncio
async def test_create_collection():
    out = await server.create_collection(name="Props")
    assert out["name"] == "Props"
    assert out["parent"] == "Scene Collection"


@pytest.mark.asyncio
async def test_create_collection_with_parent():
    out = await server.create_collection(name="SubProps", parent="Props")
    assert out["parent"] == "Props"


@pytest.mark.asyncio
async def test_delete_collection():
    out = await server.delete_collection(name="Props")
    assert out["name"] == "Props"
    assert out["unlink_objects"] is False


@pytest.mark.asyncio
async def test_delete_collection_unlink():
    out = await server.delete_collection(name="Props", unlink_objects=True)
    assert out["unlink_objects"] is True


@pytest.mark.asyncio
async def test_move_to_collection():
    out = await server.move_to_collection(collection="Props", object="Cube")
    assert out["collection"] == "Props"
    assert "Cube" in out["objects"]


@pytest.mark.asyncio
async def test_move_to_collection_batch():
    out = await server.move_to_collection(
        collection="Props", objects=["Cube", "Sphere"], unlink_others=False,
    )
    assert len(out["objects"]) == 2
    assert out["unlink_others"] is False


@pytest.mark.asyncio
async def test_list_collections():
    out = await server.list_collections()
    assert out["count"] == 2
    assert any(c["name"] == "Scene Collection" for c in out["collections"])
