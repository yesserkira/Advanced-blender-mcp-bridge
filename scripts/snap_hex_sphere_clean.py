"""Clean leftover test objects, frame the hex sphere, render closeup."""

import argparse
import asyncio
import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_server"))

from blender_mcp.blender_client import BlenderError, BlenderWS  # noqa: E402

PREP = r'''
import bpy
import math


def main():
    KEEP = {"HexSphere", "HexEffector"}
    # Wipe everything else (default cube/camera/light + smoke leftovers)
    for o in list(bpy.data.objects):
        if o.name not in KEEP:
            bpy.data.objects.remove(o, do_unlink=True)

    host = bpy.data.objects["HexSphere"]
    mod = host.modifiers["HexField"]
    iface = mod.node_group.interface
    defs = {it.name: it for it in iface.items_tree
            if it.item_type == "SOCKET" and it.in_out == "INPUT"}

    def setp(name, value):
        mod[defs[name].identifier] = value

    setp("Sphere Radius",      1.5)
    setp("Hex Count",          400.0)
    setp("Hex Scale",          0.12)
    setp("Hex Margin",         0.02)
    setp("Random Scale",       0.4)
    setp("Effector Radius",    0.7)
    setp("Effector Max Scale", 3.0)

    # Re-create effector (was wiped above)
    bpy.ops.object.empty_add(type="SPHERE", location=(1.6, 0.0, 0.4))
    eff = bpy.context.active_object
    eff.name = "HexEffector"
    eff.empty_display_size = 0.5
    mod[defs["Effector"].identifier] = eff

    # Camera
    cam_data = bpy.data.cameras.new("HexCam")
    cam_obj = bpy.data.objects.new("HexCam", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    cam_obj.location = (4.5, -4.5, 3.2)
    cam_obj.rotation_euler = (math.radians(63), 0.0, math.radians(45))
    cam_obj.data.lens = 50
    bpy.context.scene.camera = cam_obj
    bpy.context.scene.render.resolution_x = 700
    bpy.context.scene.render.resolution_y = 700

    # Sun
    sd = bpy.data.lights.new("HexSun", type="SUN")
    so = bpy.data.objects.new("HexSun", sd)
    bpy.context.scene.collection.objects.link(so)
    so.rotation_euler = (math.radians(50), math.radians(20), math.radians(-30))
    sd.energy = 4.0

    # World background
    w = bpy.context.scene.world
    w.use_nodes = True
    wt = w.node_tree
    for n in list(wt.nodes):
        wt.nodes.remove(n)
    bg  = wt.nodes.new("ShaderNodeBackground")
    out = wt.nodes.new("ShaderNodeOutputWorld")
    bg.inputs["Color"].default_value    = (0.05, 0.06, 0.08, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    wt.links.new(bg.outputs["Background"], out.inputs["Surface"])

    bpy.context.view_layer.update()
    return {"camera": cam_obj.name, "objects": [o.name for o in bpy.data.objects]}


result = main()
'''


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--token", default=os.environ.get("BLENDER_MCP_TOKEN", ""))
    p.add_argument("--url",   default=os.environ.get(
        "BLENDER_MCP_URL", "ws://127.0.0.1:9876"))
    p.add_argument("--out",   default=str(ROOT / "scripts" / "hex_sphere_clean.png"))
    args = p.parse_args()

    cli = BlenderWS(url=args.url, token=args.token)
    try:
        prep = await cli.call("exec.python",
                              {"code": PREP, "mode": "trusted"}, timeout=30.0)
        print("PREP:", prep.get("result_preview"))

        out = await cli.call(
            "render.region",
            {"x": 0, "y": 0, "w": 700, "h": 700,
             "samples": 32, "engine": "BLENDER_EEVEE_NEXT",
             "camera": "HexCam"},
            timeout=300.0,
        )
    except BlenderError as e:
        print(f"FAIL: {e.code}: {e}")
        return 1
    finally:
        await cli.close()

    Path(args.out).write_bytes(base64.b64decode(out["image_base64"]))
    print(f"Saved {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
