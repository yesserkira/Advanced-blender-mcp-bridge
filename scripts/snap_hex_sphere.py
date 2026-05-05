"""Capture a render of the hex-sphere result and save it next to the script.

Usage:
    python scripts/snap_hex_sphere.py [--token TOKEN]
"""

import argparse
import asyncio
import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_server"))

from blender_mcp.blender_client import BlenderError, BlenderWS  # noqa: E402

# A tiny prep snippet: frame the host nicely and add a temp camera.
PREP = r'''
import bpy
import math

# Add a quick render camera if not present.
CAM_NAME = "_hex_snap_cam"
if CAM_NAME not in bpy.data.objects:
    cam_data = bpy.data.cameras.new(CAM_NAME)
    cam_obj = bpy.data.objects.new(CAM_NAME, cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
else:
    cam_obj = bpy.data.objects[CAM_NAME]

cam_obj.location = (3.5, -3.5, 2.5)
cam_obj.rotation_euler = (math.radians(65), 0.0, math.radians(45))
cam_obj.data.lens = 50

bpy.context.scene.camera = cam_obj
bpy.context.scene.render.resolution_x = 800
bpy.context.scene.render.resolution_y = 800

# Make sure there's a light
LIGHT_NAME = "_hex_snap_sun"
if LIGHT_NAME not in bpy.data.objects:
    sun_data = bpy.data.lights.new(LIGHT_NAME, type="SUN")
    sun_obj = bpy.data.objects.new(LIGHT_NAME, sun_data)
    bpy.context.scene.collection.objects.link(sun_obj)
    sun_obj.rotation_euler = (math.radians(45), math.radians(15), 0)
    sun_data.energy = 3.0

result = {"camera": cam_obj.name}
'''


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--token", default=os.environ.get("BLENDER_MCP_TOKEN", ""))
    p.add_argument("--url",   default=os.environ.get(
        "BLENDER_MCP_URL", "ws://127.0.0.1:9876"))
    p.add_argument("--out",   default=str(ROOT / "scripts" / "hex_sphere_snap.png"))
    args = p.parse_args()

    cli = BlenderWS(url=args.url, token=args.token)
    try:
        await cli.call("exec.python",
                       {"code": PREP, "mode": "trusted"}, timeout=20.0)

        out = await cli.call(
            "render.region",
            {"x": 0, "y": 0, "w": 800, "h": 800,
             "samples": 32, "engine": "BLENDER_EEVEE_NEXT",
             "camera": "_hex_snap_cam"},
            timeout=300.0,
        )
    except BlenderError as e:
        print(f"FAIL: {e.code}: {e}")
        return 1
    finally:
        await cli.close()

    b64 = out.get("image_base64")
    if not b64:
        print("No image returned:", out)
        return 2

    Path(args.out).write_bytes(base64.b64decode(b64))
    print(f"Saved {args.out} ({len(b64)//1000} KB base64, {out.get('w')}x{out.get('h')})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
