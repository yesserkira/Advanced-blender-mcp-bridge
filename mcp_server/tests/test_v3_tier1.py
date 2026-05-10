"""v3.0 Tier-1 capability wrappers — round-trip tests against fake Blender."""

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


# --- Data-block creators -----------------------------------------------------


@pytest.mark.asyncio
async def test_create_light_point():
    out = await server.create_light(kind="point", name="Key", energy=500.0)
    assert out["name"] == "Key"
    assert out["type"] == "POINT"
    assert out["energy"] == 500.0


@pytest.mark.asyncio
async def test_create_camera_active():
    out = await server.create_camera(name="Cam01", lens=35.0, set_active=True)
    assert out["name"] == "Cam01"
    assert out["lens"] == 35.0
    assert out["is_active"] is True


@pytest.mark.asyncio
async def test_set_active_camera():
    out = await server.set_active_camera(name="Cam01")
    assert out["camera"] == "Cam01"


@pytest.mark.asyncio
async def test_create_empty():
    out = await server.create_empty(name="Ctrl", display="ARROWS", size=2.0)
    assert out["name"] == "Ctrl"
    assert out["display"] == "ARROWS"


@pytest.mark.asyncio
async def test_create_text():
    out = await server.create_text(body="Hello", size=2.5)
    assert out["body"] == "Hello"
    assert out["size"] == 2.5


@pytest.mark.asyncio
async def test_create_curve():
    pts = [[0, 0, 0], [1, 0, 0], [1, 1, 0]]
    out = await server.create_curve(points=pts, kind="bezier", closed=True)
    assert out["point_count"] == 3
    assert out["closed"] is True
    assert out["kind"] == "bezier"


@pytest.mark.asyncio
async def test_create_armature_with_bones():
    bones = [
        {"name": "root", "head": [0, 0, 0], "tail": [0, 0, 1]},
        {"name": "spine", "head": [0, 0, 1], "tail": [0, 0, 2], "parent": "root", "use_connect": True},
    ]
    out = await server.create_armature(name="Rig", bones=bones)
    assert out["name"] == "Rig"
    assert "root" in out["bones_created"]
    assert "spine" in out["bones_created"]


@pytest.mark.asyncio
async def test_load_image(tmp_path):
    import os
    img = tmp_path / "x.png"
    img.write_bytes(b"")  # validate_path doesn't require existence, but be safe
    out = await server.load_image(path=str(img), colorspace="Non-Color")
    # validate_path normalises the path, so compare with normpath on both sides.
    assert os.path.normpath(out["filepath"]) == os.path.normpath(str(img))


@pytest.mark.asyncio
async def test_create_image():
    out = await server.create_image(name="Bake", width=512, height=512, is_data=True)
    assert out["name"] == "Bake"
    assert out["size"] == [512, 512]


# --- Mode + mesh DSL + read --------------------------------------------------


@pytest.mark.asyncio
async def test_set_mode():
    out = await server.set_mode(mode="EDIT", object="Cube")
    assert out["ok"] is True
    assert out["mode"] == "EDIT"


@pytest.mark.asyncio
async def test_mesh_edit_multiple_ops():
    ops = [
        {"op": "extrude_faces", "faces": [0, 1], "offset": [0, 0, 1]},
        {"op": "bevel_edges", "edges": [3, 4], "offset": 0.05, "segments": 2},
        {"op": "recalc_normals"},
    ]
    out = await server.mesh_edit(object="Cube", ops=ops)
    assert out["ok_count"] == 3
    assert out["error_count"] == 0
    assert len(out["results"]) == 3


@pytest.mark.asyncio
async def test_mesh_read():
    out = await server.mesh_read(object="Cube", what=["vertices"], limit=2)
    assert out["counts"]["vertices"] == 8
    assert "vertices" in out


# --- Constraints -------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_constraint_object():
    out = await server.add_constraint(
        object="Cube", type="COPY_LOCATION", target="Empty",
        properties={"use_x": True, "use_y": False},
    )
    assert out["owner_kind"] == "object"
    assert out["type"] == "COPY_LOCATION"
    assert "use_x" in out["properties_set"]


@pytest.mark.asyncio
async def test_add_constraint_pose_bone():
    out = await server.add_constraint(
        object="Rig", bone="spine", type="IK", subtarget="ik_target",
    )
    assert out["owner_kind"] == "bone"
    assert "spine" in out["owner"]


@pytest.mark.asyncio
async def test_remove_and_list_constraints():
    rm = await server.remove_constraint(object="Cube", name="Copy Location")
    assert rm["removed"] == "Copy Location"
    lst = await server.list_constraints(object="Cube")
    assert lst["owner_kind"] == "object"


# --- Vertex groups -----------------------------------------------------------


@pytest.mark.asyncio
async def test_vertex_group_lifecycle():
    create = await server.create_vertex_group(object="Cube", name="head")
    assert create["group"] == "head"
    weights = await server.set_vertex_weights(
        object="Cube", group="head", indices=[0, 1, 2], weights=[1.0, 0.5, 0.25],
    )
    assert weights["set_count"] == 3
    weights_uniform = await server.set_vertex_weights(
        object="Cube", group="head", indices=[3, 4], weights=0.75, type="ADD",
    )
    assert weights_uniform["type"] == "ADD"
    rm = await server.remove_vertex_group(object="Cube", name="head")
    assert rm["removed"] == "head"


# --- Shape keys --------------------------------------------------------------


@pytest.mark.asyncio
async def test_shape_key_lifecycle():
    sk = await server.add_shape_key(object="Cube", name="Smile", value=0.0,
                                     slider_min=-1.0, slider_max=2.0)
    assert sk["name"] == "Smile"
    upd = await server.set_shape_key_value(object="Cube", name="Smile", value=0.5)
    assert upd["value"] == 0.5
    rm = await server.remove_shape_key(object="Cube", name="Smile")
    assert rm["removed"] == ["Smile"]
    rm_all = await server.remove_shape_key(object="Cube", all=True)
    assert "removed" in rm_all
    lst = await server.list_shape_keys(object="Cube")
    assert "keys" in lst
