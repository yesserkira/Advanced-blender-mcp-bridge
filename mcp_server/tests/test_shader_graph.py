"""Test shader.set_graph tool through BlenderWS client."""

import pytest

from blender_mcp.blender_client import BlenderWS, BlenderError


@pytest.mark.asyncio
async def test_shader_graph_basic(fake_blender):
    """shader.set_graph with principled + noise + link should succeed."""
    fake_blender._handlers["shader.set_graph"] = lambda args: {
        "material": args.get("material_name", ""),
        "node_count": len(args.get("nodes", [])) + 1,
        "link_count": len(args.get("links", [])),
        "nodes_created": [n["type"] for n in args.get("nodes", [])],
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "shader.set_graph",
            {
                "material_name": "TestMat",
                "nodes": [
                    {"id": "principled", "type": "ShaderNodeBsdfPrincipled"},
                    {"id": "noise", "type": "ShaderNodeTexNoise", "inputs": {"Scale": 8.0}},
                ],
                "links": [
                    {
                        "from_node": "noise",
                        "from_socket": "Color",
                        "to_node": "principled",
                        "to_socket": "Base Color",
                    },
                ],
            },
        )
        assert result["material"] == "TestMat"
        assert result["node_count"] == 3  # 2 user + Material Output
        assert result["link_count"] == 1
        assert "ShaderNodeBsdfPrincipled" in result["nodes_created"]
        assert "ShaderNodeTexNoise" in result["nodes_created"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_shader_graph_with_output_node(fake_blender):
    """shader.set_graph with output_node should pass it through."""
    fake_blender._handlers["shader.set_graph"] = lambda args: {
        "material": args.get("material_name", ""),
        "node_count": len(args.get("nodes", [])) + 1,
        "link_count": len(args.get("links", [])) + (1 if args.get("output_node") else 0),
        "nodes_created": [n["type"] for n in args.get("nodes", [])],
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "shader.set_graph",
            {
                "material_name": "AutoConnect",
                "nodes": [
                    {"id": "principled", "type": "ShaderNodeBsdfPrincipled"},
                ],
                "links": [],
                "output_node": "principled",
            },
        )
        assert result["material"] == "AutoConnect"
        assert result["link_count"] == 1  # auto-connection to Surface
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_shader_graph_create_if_missing(fake_blender):
    """shader.set_graph with create_if_missing=True creates the material."""
    fake_blender._handlers["shader.set_graph"] = lambda args: {
        "material": args.get("material_name", ""),
        "node_count": len(args.get("nodes", [])) + 1,
        "link_count": len(args.get("links", [])),
        "nodes_created": [n["type"] for n in args.get("nodes", [])],
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "shader.set_graph",
            {
                "material_name": "NewMaterial",
                "create_if_missing": True,
                "nodes": [
                    {"id": "principled", "type": "ShaderNodeBsdfPrincipled"},
                ],
                "links": [],
            },
        )
        assert result["material"] == "NewMaterial"
        assert result["node_count"] == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_shader_graph_preserve_existing(fake_blender):
    """shader.set_graph with clear_existing=False passes that flag."""
    received_args = {}

    def handler(args):
        received_args.update(args)
        return {
            "material": args.get("material_name", ""),
            "node_count": len(args.get("nodes", [])) + 1,
            "link_count": len(args.get("links", [])),
            "nodes_created": [n["type"] for n in args.get("nodes", [])],
        }

    fake_blender._handlers["shader.set_graph"] = handler

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "shader.set_graph",
            {
                "material_name": "ExistingMat",
                "clear_existing": False,
                "nodes": [
                    {"id": "noise", "type": "ShaderNodeTexNoise"},
                ],
                "links": [],
            },
        )
        assert result["material"] == "ExistingMat"
        assert received_args["clear_existing"] is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_shader_graph_unknown_op(fake_blender):
    """shader.set_graph without handler registered returns NOT_FOUND error."""
    # Don't register a handler — default fake server has no shader.set_graph
    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        with pytest.raises(BlenderError) as exc_info:
            await client.call(
                "shader.set_graph",
                {
                    "material_name": "Test",
                    "nodes": [{"id": "x", "type": "ShaderNodeInvalid"}],
                    "links": [],
                },
            )
        assert exc_info.value.code == "NOT_FOUND"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_shader_graph_full_procedural(fake_blender):
    """shader.set_graph with a full procedural rock setup."""
    fake_blender._handlers["shader.set_graph"] = lambda args: {
        "material": args.get("material_name", ""),
        "node_count": len(args.get("nodes", [])) + 1,
        "link_count": len(args.get("links", [])) + (1 if args.get("output_node") else 0),
        "nodes_created": [n["type"] for n in args.get("nodes", [])],
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "shader.set_graph",
            {
                "material_name": "ProceduralRock",
                "nodes": [
                    {"id": "principled", "type": "ShaderNodeBsdfPrincipled"},
                    {"id": "noise", "type": "ShaderNodeTexNoise", "inputs": {"Scale": 8.0}},
                    {"id": "bump", "type": "ShaderNodeBump", "inputs": {"Strength": 0.3}},
                ],
                "links": [
                    {"from_node": "noise", "from_socket": "Fac", "to_node": "bump", "to_socket": "Height"},
                    {"from_node": "bump", "from_socket": "Normal", "to_node": "principled", "to_socket": "Normal"},
                    {"from_node": "noise", "from_socket": "Color", "to_node": "principled", "to_socket": "Base Color"},
                ],
                "output_node": "principled",
            },
        )
        assert result["material"] == "ProceduralRock"
        assert result["node_count"] == 4  # 3 user + Material Output
        assert result["link_count"] == 4  # 3 manual + 1 auto
        assert len(result["nodes_created"]) == 3
    finally:
        await client.close()
