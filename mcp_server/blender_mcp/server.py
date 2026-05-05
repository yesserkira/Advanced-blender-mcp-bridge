"""Blender MCP Server — exposes Blender capabilities as MCP tools."""

import logging
import os

from mcp.server.fastmcp import FastMCP

from .blender_client import BlenderWS, BlenderError
from .policy import Policy, PolicyDenied

logger = logging.getLogger("blender_mcp")

# Initialize MCP server
mcp = FastMCP("blender")

# Global client and policy — initialized in main()
_bl: BlenderWS | None = None
_policy: Policy | None = None


def _get_client() -> BlenderWS:
    global _bl
    if _bl is None:
        token = os.environ.get("BLENDER_MCP_TOKEN", "")
        if not token:
            try:
                import keyring
                token = keyring.get_password("blender-mcp", "default") or ""
            except Exception:
                pass
        url = os.environ.get("BLENDER_MCP_URL", "ws://127.0.0.1:9876")
        _bl = BlenderWS(url=url, token=token)
    return _bl


def _get_policy() -> Policy:
    global _policy
    if _policy is None:
        policy_path = os.environ.get("BLENDER_MCP_POLICY")
        _policy = Policy.load(policy_path)
    return _policy


@mcp.tool()
async def ping() -> str:
    """Ping the Blender add-on to check connectivity. Returns 'pong' if connected."""
    bl = _get_client()
    result = await bl.call("ping")
    return str(result)


@mcp.tool()
async def get_scene_info(detail: str = "standard") -> dict:
    """Get information about the current Blender scene.

    Args:
        detail: Level of detail - 'summary', 'standard', or 'full'.
            - summary: scene name, object counts, frame range
            - standard: + per-object transforms, collections, world
            - full: + mesh stats, materials, modifiers, animation

    Returns:
        Scene information dict. Object names are wrapped in <<UNTRUSTED>> markers
        since they originate from user content.

    Always call this before modifying the scene to understand its current state.
    """
    policy = _get_policy()
    policy.require("get_scene_info")

    bl = _get_client()
    try:
        result = await bl.call("scene.get", {"detail": detail})
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}

    # Wrap object names in UNTRUSTED markers (§14.9)
    if "objects" in result:
        for obj in result["objects"]:
            if "name" in obj:
                obj["name"] = f"<<UNTRUSTED>>{obj['name']}<</UNTRUSTED>>"

    return result


@mcp.tool()
async def create_primitive(
    kind: str,
    name: str | None = None,
    location: list[float] | None = None,
    size: float = 1.0,
) -> dict:
    """Create a mesh primitive in Blender.

    Args:
        kind: Type of primitive - 'cube', 'sphere', 'cylinder', 'plane', 'cone', or 'torus'.
        name: Optional name for the created object.
        location: [x, y, z] position. Defaults to [0, 0, 0].
        size: Size of the primitive. Defaults to 1.0.

    Returns:
        Dict with 'name', 'polys', and 'vertices' of the created object.

    Example:
        create_primitive(kind="cube", name="MyCube", location=[0, 0, 1], size=2.0)
    """
    policy = _get_policy()
    policy.require("create_primitive")

    bl = _get_client()
    args = {
        "kind": kind,
        "location": location or [0, 0, 0],
        "size": size,
    }
    if name is not None:
        args["name"] = name

    try:
        return await bl.call("mesh.create_primitive", args)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def viewport_screenshot(width: int = 1024, height: int = 1024) -> dict:
    """Capture a screenshot of the Blender viewport.

    Args:
        width: Image width in pixels (max 4096). Defaults to 1024.
        height: Image height in pixels (max 4096). Defaults to 1024.

    Returns:
        Dict with 'image_base64' (PNG encoded as base64), 'mime', 'width', 'height'.

    Call this after making changes to verify the result visually.
    """
    policy = _get_policy()
    policy.require("viewport_screenshot")
    policy.check_resolution(width, height)

    bl = _get_client()
    try:
        return await bl.call("render.viewport_screenshot", {"w": width, "h": height})
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


def main():
    """Entry point for the MCP server."""
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    mcp.run()


if __name__ == "__main__":
    main()
