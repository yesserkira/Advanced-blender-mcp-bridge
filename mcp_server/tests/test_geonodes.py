"""Test geonodes.build tool through BlenderWS client."""

import pytest

from blender_mcp.blender_client import BlenderWS


@pytest.mark.asyncio
async def test_build_geonodes_minimal(fake_blender):
    """geonodes.build with one node and no links should succeed."""
    fake_blender._handlers["geonodes.build"] = lambda args: {
        "object": args.get("object_name", ""),
        "modifier": args.get("modifier_name", "AI_GeoNodes"),
        "node_count": len(args.get("nodes", [])) + 2,
        "link_count": len(args.get("links", [])),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "geonodes.build",
            {
                "object_name": "Cube",
                "nodes": [
                    {"id": "cube", "type": "GeometryNodeMeshCube"},
                ],
                "links": [],
            },
        )
        assert result["object"] == "Cube"
        assert result["modifier"] == "AI_GeoNodes"
        assert result["node_count"] == 3  # 1 user + GroupInput + GroupOutput
        assert result["link_count"] == 0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_build_geonodes_two_nodes_one_link(fake_blender):
    """geonodes.build with two nodes and a link returns correct counts."""
    fake_blender._handlers["geonodes.build"] = lambda args: {
        "object": args.get("object_name", ""),
        "modifier": args.get("modifier_name", "AI_GeoNodes"),
        "node_count": len(args.get("nodes", [])) + 2,
        "link_count": len(args.get("links", [])),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "geonodes.build",
            {
                "object_name": "Cube",
                "nodes": [
                    {"id": "cube", "type": "GeometryNodeMeshCube", "inputs": {"Size": [2, 2, 2]}},
                    {"id": "setpos", "type": "GeometryNodeSetPosition"},
                ],
                "links": [
                    {
                        "from_node": "cube",
                        "from_socket": "Mesh",
                        "to_node": "setpos",
                        "to_socket": "Geometry",
                    },
                ],
            },
        )
        assert result["object"] == "Cube"
        assert result["node_count"] == 4  # 2 user + GroupInput + GroupOutput
        assert result["link_count"] == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_build_geonodes_with_group_io(fake_blender):
    """geonodes.build with group_inputs and group_outputs passes them through."""
    fake_blender._handlers["geonodes.build"] = lambda args: {
        "object": args.get("object_name", ""),
        "modifier": args.get("modifier_name", "AI_GeoNodes"),
        "node_count": len(args.get("nodes", [])) + 2,
        "link_count": len(args.get("links", [])),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "geonodes.build",
            {
                "object_name": "Cube",
                "modifier_name": "CustomGeo",
                "group_name": "MyGeoGroup",
                "nodes": [
                    {"id": "cube", "type": "GeometryNodeMeshCube"},
                ],
                "links": [
                    {
                        "from_node": "cube",
                        "from_socket": "Mesh",
                        "to_node": "group_output",
                        "to_socket": "Geometry",
                    },
                ],
                "group_inputs": [
                    {"name": "Scale", "type": "NodeSocketFloat"},
                ],
                "group_outputs": [
                    {"name": "Geometry", "type": "NodeSocketGeometry"},
                ],
            },
        )
        assert result["object"] == "Cube"
        assert result["modifier"] == "CustomGeo"
        assert result["node_count"] == 3
        assert result["link_count"] == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_build_geonodes_custom_modifier_name(fake_blender):
    """geonodes.build with custom modifier name returns it in the response."""
    fake_blender._handlers["geonodes.build"] = lambda args: {
        "object": args.get("object_name", ""),
        "modifier": args.get("modifier_name", "AI_GeoNodes"),
        "node_count": len(args.get("nodes", [])) + 2,
        "link_count": len(args.get("links", [])),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "geonodes.build",
            {
                "object_name": "Sphere",
                "modifier_name": "ScatterGrass",
                "nodes": [],
                "links": [],
            },
        )
        assert result["object"] == "Sphere"
        assert result["modifier"] == "ScatterGrass"
        assert result["node_count"] == 2  # GroupInput + GroupOutput only
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_build_geonodes_group_input_link(fake_blender):
    """geonodes.build with a link from group_input passes correctly."""
    fake_blender._handlers["geonodes.build"] = lambda args: {
        "object": args.get("object_name", ""),
        "modifier": args.get("modifier_name", "AI_GeoNodes"),
        "node_count": len(args.get("nodes", [])) + 2,
        "link_count": len(args.get("links", [])),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "geonodes.build",
            {
                "object_name": "Cube",
                "nodes": [
                    {"id": "setpos", "type": "GeometryNodeSetPosition"},
                ],
                "links": [
                    {
                        "from_node": "group_input",
                        "from_socket": "Geometry",
                        "to_node": "setpos",
                        "to_socket": "Geometry",
                    },
                    {
                        "from_node": "setpos",
                        "from_socket": "Geometry",
                        "to_node": "group_output",
                        "to_socket": "Geometry",
                    },
                ],
            },
        )
        assert result["link_count"] == 2
    finally:
        await client.close()
