"""Test modifier tools through BlenderWS client."""

import pytest

from blender_mcp.blender_client import BlenderWS, BlenderError


@pytest.mark.asyncio
async def test_modifier_add_subsurf(fake_blender):
    """modifier.add SUBSURF should return modifier info."""
    fake_blender._handlers["modifier.add"] = lambda args: {
        "object": args["object_name"],
        "modifier_name": args.get("modifier_name") or args["modifier_type"],
        "modifier_type": args["modifier_type"],
        "index": 0,
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("modifier.add", {
            "object_name": "Cube",
            "modifier_type": "SUBSURF",
            "params": {"levels": 3, "render_levels": 4},
        })
        assert result["object"] == "Cube"
        assert result["modifier_type"] == "SUBSURF"
        assert result["modifier_name"] == "SUBSURF"
        assert result["index"] == 0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_modifier_add_bevel(fake_blender):
    """modifier.add BEVEL should return modifier info."""
    fake_blender._handlers["modifier.add"] = lambda args: {
        "object": args["object_name"],
        "modifier_name": args.get("modifier_name") or args["modifier_type"],
        "modifier_type": args["modifier_type"],
        "index": 0,
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("modifier.add", {
            "object_name": "Cube",
            "modifier_type": "BEVEL",
            "params": {"width": 0.2, "segments": 3},
        })
        assert result["object"] == "Cube"
        assert result["modifier_type"] == "BEVEL"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_modifier_add_mirror(fake_blender):
    """modifier.add MIRROR should return modifier info."""
    fake_blender._handlers["modifier.add"] = lambda args: {
        "object": args["object_name"],
        "modifier_name": args.get("modifier_name") or args["modifier_type"],
        "modifier_type": args["modifier_type"],
        "index": 0,
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("modifier.add", {
            "object_name": "Cube",
            "modifier_type": "MIRROR",
            "params": {"use_axis": [True, True, False]},
        })
        assert result["object"] == "Cube"
        assert result["modifier_type"] == "MIRROR"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_modifier_add_array(fake_blender):
    """modifier.add ARRAY should return modifier info."""
    fake_blender._handlers["modifier.add"] = lambda args: {
        "object": args["object_name"],
        "modifier_name": args.get("modifier_name") or args["modifier_type"],
        "modifier_type": args["modifier_type"],
        "index": 0,
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("modifier.add", {
            "object_name": "Cube",
            "modifier_type": "ARRAY",
            "params": {"count": 5, "relative_offset_displace": [1.5, 0, 0]},
        })
        assert result["object"] == "Cube"
        assert result["modifier_type"] == "ARRAY"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_modifier_add_boolean(fake_blender):
    """modifier.add BOOLEAN should return modifier info."""
    fake_blender._handlers["modifier.add"] = lambda args: {
        "object": args["object_name"],
        "modifier_name": args.get("modifier_name") or args["modifier_type"],
        "modifier_type": args["modifier_type"],
        "index": 0,
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("modifier.add", {
            "object_name": "Cube",
            "modifier_type": "BOOLEAN",
            "params": {"operation": "DIFFERENCE", "object": "Sphere"},
        })
        assert result["object"] == "Cube"
        assert result["modifier_type"] == "BOOLEAN"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_modifier_add_with_custom_name(fake_blender):
    """modifier.add with modifier_name should use that name."""
    fake_blender._handlers["modifier.add"] = lambda args: {
        "object": args["object_name"],
        "modifier_name": args.get("modifier_name") or args["modifier_type"],
        "modifier_type": args["modifier_type"],
        "index": 0,
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("modifier.add", {
            "object_name": "Cube",
            "modifier_type": "SUBSURF",
            "modifier_name": "Smooth",
        })
        assert result["modifier_name"] == "Smooth"
        assert result["modifier_type"] == "SUBSURF"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_modifier_add_no_params(fake_blender):
    """modifier.add without params should use defaults."""
    fake_blender._handlers["modifier.add"] = lambda args: {
        "object": args["object_name"],
        "modifier_name": args.get("modifier_name") or args["modifier_type"],
        "modifier_type": args["modifier_type"],
        "index": 0,
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("modifier.add", {
            "object_name": "Cube",
            "modifier_type": "BEVEL",
        })
        assert result["object"] == "Cube"
        assert result["modifier_type"] == "BEVEL"
        assert result["index"] == 0
    finally:
        await client.close()
