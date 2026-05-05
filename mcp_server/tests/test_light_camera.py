"""Test light and camera tools through BlenderWS client."""

import pytest

from blender_mcp.blender_client import BlenderWS, BlenderError


@pytest.mark.asyncio
async def test_create_light_point(fake_blender):
    """light.create with POINT type should return light info."""
    fake_blender._handlers["light.create"] = lambda args: {
        "name": args.get("name", "Point"),
        "type": args["type"],
        "location": args.get("location", [0, 0, 0]),
        "energy": args.get("energy", 1000.0),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("light.create", {
            "type": "POINT",
            "name": "MyLight",
            "location": [1, 2, 3],
            "energy": 500.0,
        })
        assert result["name"] == "MyLight"
        assert result["type"] == "POINT"
        assert result["location"] == [1, 2, 3]
        assert result["energy"] == 500.0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_create_light_sun(fake_blender):
    """light.create with SUN type should use default energy 1.0."""
    fake_blender._handlers["light.create"] = lambda args: {
        "name": args.get("name", "Sun"),
        "type": args["type"],
        "location": args.get("location", [0, 0, 0]),
        "energy": args.get("energy", 1.0),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("light.create", {"type": "SUN"})
        assert result["type"] == "SUN"
        assert result["energy"] == 1.0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_create_camera(fake_blender):
    """camera.create should return camera info."""
    fake_blender._handlers["camera.create"] = lambda args: {
        "name": args.get("name", "Camera"),
        "lens": args.get("lens", 50.0),
        "location": args.get("location", [0, 0, 5]),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("camera.create", {
            "name": "MyCam",
            "location": [5, -3, 7],
            "lens": 85.0,
        })
        assert result["name"] == "MyCam"
        assert result["lens"] == 85.0
        assert result["location"] == [5, -3, 7]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_create_camera_defaults(fake_blender):
    """camera.create with no args should use defaults."""
    fake_blender._handlers["camera.create"] = lambda args: {
        "name": "Camera",
        "lens": args.get("lens", 50.0),
        "location": args.get("location", [0, 0, 5]),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("camera.create", {})
        assert result["name"] == "Camera"
        assert result["lens"] == 50.0
        assert result["location"] == [0, 0, 5]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_set_active_camera(fake_blender):
    """camera.set_active should return the active camera name."""
    fake_blender._handlers["camera.set_active"] = lambda args: {
        "active_camera": args["name"],
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("camera.set_active", {"name": "MyCam"})
        assert result["active_camera"] == "MyCam"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_create_light_unknown_op(fake_blender):
    """Calling light.create without a handler should return NOT_FOUND."""
    del fake_blender._handlers["light.create"]
    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        with pytest.raises(BlenderError) as exc_info:
            await client.call("light.create", {"type": "POINT"})
        assert exc_info.value.code == "NOT_FOUND"
    finally:
        await client.close()
