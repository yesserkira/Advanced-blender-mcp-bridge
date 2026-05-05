"""Test animation keyframe tools through BlenderWS client."""

import pytest

from blender_mcp.blender_client import BlenderWS, BlenderError


@pytest.mark.asyncio
async def test_keyframe_with_value(fake_blender):
    """animation.keyframe with value should return the set value."""
    fake_blender._handlers["animation.keyframe"] = lambda args: {
        "object": args["object_name"],
        "data_path": args["data_path"],
        "frame": args["frame"],
        "value": args.get("value", [0, 0, 0]),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("animation.keyframe", {
            "object_name": "Cube",
            "data_path": "location",
            "frame": 1,
            "value": [1.0, 2.0, 3.0],
        })
        assert result["object"] == "Cube"
        assert result["data_path"] == "location"
        assert result["frame"] == 1
        assert result["value"] == [1.0, 2.0, 3.0]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_keyframe_without_value(fake_blender):
    """animation.keyframe without value should keyframe the current value."""
    fake_blender._handlers["animation.keyframe"] = lambda args: {
        "object": args["object_name"],
        "data_path": args["data_path"],
        "frame": args["frame"],
        "value": [0, 0, 0],
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("animation.keyframe", {
            "object_name": "Cube",
            "data_path": "location",
            "frame": 10,
        })
        assert result["object"] == "Cube"
        assert result["data_path"] == "location"
        assert result["frame"] == 10
        assert result["value"] == [0, 0, 0]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_keyframe_with_index(fake_blender):
    """animation.keyframe with index should keyframe a single channel."""
    fake_blender._handlers["animation.keyframe"] = lambda args: {
        "object": args["object_name"],
        "data_path": args["data_path"],
        "frame": args["frame"],
        "value": args.get("value", 5.0),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("animation.keyframe", {
            "object_name": "Cube",
            "data_path": "location",
            "frame": 20,
            "value": 5.0,
            "index": 2,
        })
        assert result["object"] == "Cube"
        assert result["frame"] == 20
        assert result["value"] == 5.0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_keyframe_rotation(fake_blender):
    """animation.keyframe on rotation_euler should work."""
    fake_blender._handlers["animation.keyframe"] = lambda args: {
        "object": args["object_name"],
        "data_path": args["data_path"],
        "frame": args["frame"],
        "value": args.get("value", [0, 0, 0]),
    }

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("animation.keyframe", {
            "object_name": "Cube",
            "data_path": "rotation_euler",
            "frame": 30,
            "value": [0, 0, 1.5708],
        })
        assert result["data_path"] == "rotation_euler"
        assert result["frame"] == 30
        assert result["value"] == [0, 0, 1.5708]
    finally:
        await client.close()
