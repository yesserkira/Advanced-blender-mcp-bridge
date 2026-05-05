"""Test material tools through BlenderWS client."""

import pytest

from blender_mcp.blender_client import BlenderWS, BlenderError


@pytest.mark.asyncio
async def test_create_material_pbr(fake_blender):
    """material.create_pbr should create a material and return its info."""
    # Register handler for this test
    fake_blender._handlers["material.create_pbr"] = lambda args: {
        "name": args.get("name", "Material"),
        "node_tree": "Principled BSDF",
        "inputs_set": ["Base Color", "Metallic", "Roughness"],
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "material.create_pbr",
            {
                "name": "RedMetal",
                "base_color": [1.0, 0.0, 0.0, 1.0],
                "metallic": 0.9,
                "roughness": 0.2,
            },
        )
        assert result["name"] == "RedMetal"
        assert result["node_tree"] == "Principled BSDF"
        assert "Base Color" in result["inputs_set"]
        assert "Metallic" in result["inputs_set"]
        assert "Roughness" in result["inputs_set"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_create_material_pbr_defaults(fake_blender):
    """material.create_pbr with only name should return default inputs."""
    fake_blender._handlers["material.create_pbr"] = lambda args: {
        "name": args.get("name", "Material"),
        "node_tree": "Principled BSDF",
        "inputs_set": ["Base Color", "Metallic", "Roughness"],
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("material.create_pbr", {"name": "Default"})
        assert result["name"] == "Default"
        assert result["node_tree"] == "Principled BSDF"
        assert len(result["inputs_set"]) >= 3
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_create_material_pbr_with_emission(fake_blender):
    """material.create_pbr with emission params should include them in inputs_set."""
    fake_blender._handlers["material.create_pbr"] = lambda args: {
        "name": args.get("name", "Material"),
        "node_tree": "Principled BSDF",
        "inputs_set": [
            "Base Color",
            "Metallic",
            "Roughness",
            "Emission Color",
            "Emission Strength",
        ],
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "material.create_pbr",
            {
                "name": "Glow",
                "emission_color": [1.0, 1.0, 0.0, 1.0],
                "emission_strength": 5.0,
            },
        )
        assert "Emission Color" in result["inputs_set"]
        assert "Emission Strength" in result["inputs_set"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_assign_material(fake_blender):
    """material.assign should assign a material to an object."""
    fake_blender._handlers["material.assign"] = lambda args: {
        "object": args.get("object_name", ""),
        "material": args.get("material_name", ""),
        "slot": args.get("slot", 0),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "material.assign",
            {"object_name": "Cube", "material_name": "RedMetal", "slot": 0},
        )
        assert result["object"] == "Cube"
        assert result["material"] == "RedMetal"
        assert result["slot"] == 0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_assign_material_default_slot(fake_blender):
    """material.assign without slot should default to slot 0."""
    fake_blender._handlers["material.assign"] = lambda args: {
        "object": args.get("object_name", ""),
        "material": args.get("material_name", ""),
        "slot": args.get("slot", 0),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call(
            "material.assign",
            {"object_name": "Sphere", "material_name": "Blue"},
        )
        assert result["object"] == "Sphere"
        assert result["material"] == "Blue"
        assert result["slot"] == 0
    finally:
        await client.close()
