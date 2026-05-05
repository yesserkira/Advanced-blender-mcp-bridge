"""v2.0 tests covering the new tool surface end-to-end via fake Blender WS."""

import os

import pytest

# Ensure server.py finds connection details before import.
os.environ.setdefault("BLENDER_MCP_TOKEN", "test")
os.environ.setdefault("BLENDER_MCP_URL", "ws://127.0.0.1:19876")

from blender_mcp import server  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch, fake_blender):
    """Re-point the server's BlenderWS at the fake server for each test."""
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


# -- P2 -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_object():
    out = await server.query(target="object:Cube")
    assert out["name"] == "Cube"


@pytest.mark.asyncio
async def test_list_kind():
    out = await server.list_(kind="objects", filter={"type": "MESH"})
    assert out[0]["name"] == "Cube"


@pytest.mark.asyncio
async def test_describe_api():
    out = await server.describe_api(rna_path="SubsurfModifier")
    assert out["rna"] == "SubsurfModifier"
    assert any(p["name"] == "levels" for p in out["properties"])


# -- P3 -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_modifier_single():
    out = await server.add_modifier(
        object="Cube", type="BEVEL",
        properties={"width": 0.05, "segments": 3},
    )
    assert out["type"] == "BEVEL"
    assert "width" in out["properties_set"]
    assert "segments" in out["properties_set"]


@pytest.mark.asyncio
async def test_add_modifier_batch():
    out = await server.add_modifier(object=[
        {"object": "Cube", "type": "SUBSURF", "properties": {"levels": 2}},
        {"object": "Plane", "type": "SOLIDIFY", "properties": {"thickness": 0.1}},
    ])
    assert out["batch"] is True
    assert out["count"] == 2
    assert out["ok_count"] == 2


@pytest.mark.asyncio
async def test_build_nodes():
    out = await server.build_nodes(
        target="material:Gold!",
        graph={
            "nodes": [
                {"name": "bsdf", "type": "ShaderNodeBsdfPrincipled"},
                {"name": "out", "type": "ShaderNodeOutputMaterial"},
            ],
            "links": [{"from": "bsdf.BSDF", "to": "out.Surface"}],
        },
    )
    assert out["node_count"] == 2
    assert out["link_count"] == 1


@pytest.mark.asyncio
async def test_set_property():
    out = await server.set_property(
        path="bpy.data.scenes['Scene'].cycles.samples", value=128,
    )
    assert out["value"] == 128


@pytest.mark.asyncio
async def test_call_operator():
    out = await server.call_operator(operator="object.shade_smooth")
    assert "FINISHED" in out["result"]


# -- Mesh + scene basics -----------------------------------------------


@pytest.mark.asyncio
async def test_create_primitive_single():
    out = await server.create_primitive(kind="cube", name="A", size=2)
    assert out["name"] == "A"
    assert out["polys"] == 6


@pytest.mark.asyncio
async def test_create_primitive_batch():
    out = await server.create_primitive(kind=[
        {"kind": "cube", "name": f"C{i}", "location": [i, 0, 0]} for i in range(5)
    ])
    assert out["batch"] is True
    assert out["count"] == 5


@pytest.mark.asyncio
async def test_set_transform_batch():
    out = await server.set_transform(object=[
        {"object": "C0", "location": [0, 0, 0]},
        {"object": "C1", "location": [1, 0, 0]},
    ])
    assert out["batch"] is True
    assert out["ok_count"] == 2


# -- P4 composition ----------------------------------------------------


@pytest.mark.asyncio
async def test_create_objects():
    specs = [
        {"kind": "cube", "name": "Pedestal", "location": [0, 0, 0]},
        {"kind": "light", "light_type": "POINT", "name": "Key",
         "location": [3, -2, 4], "energy": 800},
        {"kind": "camera", "name": "Cam", "location": [7, -5, 3], "lens": 85,
         "set_active": True},
    ]
    out = await server.create_objects(specs=specs)
    assert out["count"] == 3
    names = [r["name"] for r in out["created"]]
    assert names == ["Pedestal", "Key", "Cam"]


@pytest.mark.asyncio
async def test_transaction():
    out = await server.transaction(steps=[
        {"tool": "create_objects", "args": {"specs": [{"kind": "cube"}]}},
        {"tool": "build_nodes", "args": {"target": "material:Gold!", "graph": {}}},
    ], label="setup")
    assert out["ok"] is True
    assert out["step_count"] == 2


@pytest.mark.asyncio
async def test_apply_to_selection():
    out = await server.apply_to_selection(
        tool="add_modifier",
        args={"type": "BEVEL", "properties": {"width": 0.02}},
    )
    assert out["count"] == 1


# -- P5 assets ---------------------------------------------------------


@pytest.mark.asyncio
async def test_import_asset(tmp_path, monkeypatch):
    # Bypass the path jail by configuring an allowed root
    server._policy = None
    fake = tmp_path / "x.glb"
    fake.write_bytes(b"\x00")
    monkeypatch.setenv("BLENDER_MCP_POLICY", "")
    pol = server._get_policy()
    pol.allowed_roots = [str(tmp_path.resolve())]
    out = await server.import_asset(path=str(fake))
    assert out["count"] == 1


@pytest.mark.asyncio
async def test_link_blend(tmp_path, monkeypatch):
    server._policy = None
    fake = tmp_path / "lib.blend"
    fake.write_bytes(b"\x00")
    pol = server._get_policy()
    pol.allowed_roots = [str(tmp_path.resolve())]
    out = await server.link_blend(
        path=str(fake),
        datablocks=[{"type": "Object", "name": "Tree"}],
        link=True,
    )
    assert out["loaded"] == {"Object": ["Tree"]}


# -- P6 visual ---------------------------------------------------------


@pytest.mark.asyncio
async def test_viewport_screenshot():
    out = await server.viewport_screenshot(width=512, height=512)
    assert out["mime"] == "image/png"
    assert out["width"] == 512


@pytest.mark.asyncio
async def test_render_region():
    out = await server.render_region(x=0, y=0, w=128, h=128, samples=8)
    assert out["w"] == 128
    assert out["samples"] == 8


@pytest.mark.asyncio
async def test_scene_diff_baseline():
    out = await server.scene_diff()
    assert out["baseline"] is True


# -- Exec --------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_python(monkeypatch):
    # Bypass the confirm_required gate
    server._policy = None
    pol = server._get_policy()
    pol.confirm_required = []
    out = await server.execute_python(code="x = 1\ny = 2", mode="trusted")
    assert out["executed"] is True
    assert out["lines"] == 2
    assert out["mode"] == "trusted"
