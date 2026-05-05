"""Test mesh edit tools through BlenderWS client."""

import pytest

from blender_mcp.blender_client import BlenderWS, BlenderError


@pytest.mark.asyncio
async def test_mesh_edit_extrude(fake_blender):
    """mesh.edit extrude should return updated mesh info."""
    fake_blender._handlers["mesh.edit"] = lambda args: {
        "object": args["object_name"],
        "operation": args["operation"],
        "offset": args.get("params", {}).get("offset", 1.0),
        "direction": args.get("params", {}).get("direction", [0, 0, 1]),
        "vertices": 16,
        "polys": 10,
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "mesh.edit",
            {
                "object_name": "Cube",
                "operation": "extrude",
                "params": {"offset": 2.0, "direction": [0, 0, 1]},
            },
        )
        assert result["object"] == "Cube"
        assert result["operation"] == "extrude"
        assert result["offset"] == 2.0
        assert result["vertices"] == 16
        assert result["polys"] == 10
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mesh_edit_bevel(fake_blender):
    """mesh.edit bevel should return bevel params and updated counts."""
    fake_blender._handlers["mesh.edit"] = lambda args: {
        "object": args["object_name"],
        "operation": args["operation"],
        "offset": args.get("params", {}).get("offset", 0.1),
        "segments": args.get("params", {}).get("segments", 1),
        "affect": args.get("params", {}).get("affect", "EDGES"),
        "vertices": 26,
        "polys": 24,
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "mesh.edit",
            {
                "object_name": "Cube",
                "operation": "bevel",
                "params": {"offset": 0.2, "segments": 3, "affect": "EDGES"},
            },
        )
        assert result["object"] == "Cube"
        assert result["operation"] == "bevel"
        assert result["offset"] == 0.2
        assert result["segments"] == 3
        assert result["affect"] == "EDGES"
        assert result["vertices"] == 26
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mesh_edit_loop_cut(fake_blender):
    """mesh.edit loop_cut should return cut count and edge index."""
    fake_blender._handlers["mesh.edit"] = lambda args: {
        "object": args["object_name"],
        "operation": args["operation"],
        "cuts": args.get("params", {}).get("cuts", 1),
        "edge_index": args.get("params", {}).get("edge_index", 0),
        "vertices": 12,
        "polys": 8,
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "mesh.edit",
            {
                "object_name": "Cube",
                "operation": "loop_cut",
                "params": {"cuts": 2, "edge_index": 4},
            },
        )
        assert result["object"] == "Cube"
        assert result["operation"] == "loop_cut"
        assert result["cuts"] == 2
        assert result["edge_index"] == 4
        assert result["vertices"] == 12
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mesh_edit_boolean(fake_blender):
    """mesh.edit boolean should return boolean mode and other object."""
    fake_blender._handlers["mesh.edit"] = lambda args: {
        "object": args["object_name"],
        "operation": args["operation"],
        "boolean_mode": args.get("params", {}).get("operation", "DIFFERENCE"),
        "other_object": args.get("params", {}).get("other_object", ""),
        "vertices": 20,
        "polys": 18,
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "mesh.edit",
            {
                "object_name": "Cube",
                "operation": "boolean",
                "params": {"other_object": "Sphere", "operation": "UNION"},
            },
        )
        assert result["object"] == "Cube"
        assert result["operation"] == "boolean"
        assert result["boolean_mode"] == "UNION"
        assert result["other_object"] == "Sphere"
        assert result["vertices"] == 20
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mesh_edit_defaults(fake_blender):
    """mesh.edit extrude with no params should use defaults."""
    fake_blender._handlers["mesh.edit"] = lambda args: {
        "object": args["object_name"],
        "operation": args["operation"],
        "offset": args.get("params", {}).get("offset", 1.0),
        "direction": args.get("params", {}).get("direction", [0, 0, 1]),
        "vertices": 16,
        "polys": 10,
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "mesh.edit",
            {
                "object_name": "Cube",
                "operation": "extrude",
            },
        )
        assert result["object"] == "Cube"
        assert result["operation"] == "extrude"
        assert result["offset"] == 1.0
        assert result["direction"] == [0, 0, 1]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mesh_edit_unknown_op(fake_blender):
    """mesh.edit with unknown operation should fail."""
    del fake_blender._handlers["mesh.edit"]
    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        with pytest.raises(BlenderError) as exc_info:
            await client.call(
                "mesh.edit",
                {"object_name": "Cube", "operation": "unknown_op"},
            )
        assert exc_info.value.code == "NOT_FOUND"
    finally:
        await client.close()
