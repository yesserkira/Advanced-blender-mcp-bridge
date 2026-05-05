"""Test ping round-trip through BlenderWS client."""

import pytest

from blender_mcp.blender_client import BlenderWS


@pytest.mark.asyncio
async def test_ping_pong(fake_blender):
    """BlenderWS.call('ping') should return 'pong' from the fake server."""
    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("ping")
        assert result == "pong"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_scene_get(fake_blender):
    """BlenderWS.call('scene.get') should return scene info from fake server."""
    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("scene.get", {"detail": "summary"})
        assert result["scene"] == "Scene"
        assert "frame" in result
        assert result["object_counts"]["MESH"] == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_unknown_op(fake_blender):
    """Unknown op should raise BlenderError."""
    from blender_mcp.blender_client import BlenderError

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        with pytest.raises(BlenderError) as exc_info:
            await client.call("nonexistent.op")
        assert exc_info.value.code == "NOT_FOUND"
    finally:
        await client.close()
