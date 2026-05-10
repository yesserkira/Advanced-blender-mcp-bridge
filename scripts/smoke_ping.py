"""End-to-end smoke: MCP server credential resolution + WS ping to Blender."""
import asyncio
from blender_mcp.blender_client import BlenderWS
from blender_mcp.server import _resolve_credentials


async def main():
    url, token = _resolve_credentials()
    print(f"URL: {url}")
    print(f"Token: {token[:8]}... (len={len(token)})")
    bl = BlenderWS(url=url, token=token)
    try:
        result = await bl.call("scene.context", {}, timeout=5.0)
        print(f"scene.context ok: keys={list(result.keys()) if isinstance(result, dict) else type(result).__name__}")
    except Exception as e:
        print(f"PING FAIL: {type(e).__name__}: {e}")
    finally:
        await bl.close()


if __name__ == "__main__":
    asyncio.run(main())
