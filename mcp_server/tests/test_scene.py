"""Test scene info tool through BlenderWS client."""

import pytest

from blender_mcp.blender_client import BlenderWS


@pytest.mark.asyncio
async def test_scene_get_returns_scene_info(fake_blender):
    """scene.get should return scene structure from fake server."""
    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("scene.get", {"detail": "summary"})
        assert "scene" in result
        assert "frame" in result
        assert result["frame"]["fps"] == 24
        assert "object_counts" in result
    finally:
        await client.close()
