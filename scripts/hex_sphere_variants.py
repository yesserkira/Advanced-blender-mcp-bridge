"""Render 4 variants to prove parameter independence."""

import argparse
import asyncio
import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_server"))

from blender_mcp.blender_client import BlenderError, BlenderWS  # noqa: E402

# Variant params: (label, Sphere Radius, Hex Count, Hex Scale, Effector Radius)
VARIANTS = [
    ("a_baseline",       1.5, 400.0, 0.10, 0.0),    # no effector
    ("b_double_radius",  3.0, 400.0, 0.10, 0.0),    # only radius doubled
    ("c_high_count",     1.5, 900.0, 0.06, 0.0),    # more hexes, smaller (so they fit)
    ("d_with_effector",  1.5, 400.0, 0.10, 1.0),    # show proximity bump
]

SET_PARAMS_TPL = r'''
import bpy

def main():
    host = bpy.data.objects["HexSphere"]
    mod  = host.modifiers["HexField"]
    iface = mod.node_group.interface
    defs = {it.name: it for it in iface.items_tree
            if it.item_type == "SOCKET" and it.in_out == "INPUT"}

    def setp(name, value):
        mod[defs[name].identifier] = value

    setp("Sphere Radius",      __SR__)
    setp("Hex Count",          __HC__)
    setp("Hex Scale",          __HS__)
    setp("Hex Margin",         0.02)
    setp("Random Scale",       0.4)
    setp("Effector Radius",    __ER__)
    setp("Effector Max Scale", 3.0)

    eff = bpy.data.objects["HexEffector"]
    eff.location = (__SR__ * 1.05, 0.0, 0.4)

    # adjust camera to keep host framed even when radius doubles
    cam = bpy.data.objects["HexCam"]
    d = max(__SR__ * 3.0, 4.5)
    cam.location = (d, -d, d * 0.7)

    bpy.context.view_layer.update()
    return {"sr": __SR__, "hc": __HC__, "hs": __HS__, "er": __ER__}

result = main()
'''


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--token", default=os.environ.get("BLENDER_MCP_TOKEN", ""))
    p.add_argument("--url",   default=os.environ.get(
        "BLENDER_MCP_URL", "ws://127.0.0.1:9876"))
    p.add_argument("--outdir", default=str(ROOT / "scripts" / "hex_variants"))
    args = p.parse_args()

    Path(args.outdir).mkdir(parents=True, exist_ok=True)

    cli = BlenderWS(url=args.url, token=args.token)
    try:
        for label, sr, hc, hs, er in VARIANTS:
            code = (SET_PARAMS_TPL
                    .replace("__SR__", str(sr))
                    .replace("__HC__", str(hc))
                    .replace("__HS__", str(hs))
                    .replace("__ER__", str(er)))
            try:
                ok = await cli.call("exec.python",
                                    {"code": code, "mode": "trusted"},
                                    timeout=20.0)
                print(f"[{label}] params:", ok.get("result_preview", {}).get("repr"))
            except BlenderError as e:
                print(f"[{label}] PARAM-FAIL: {e}")
                continue

            try:
                img = await cli.call(
                    "render.region",
                    {"x": 0, "y": 0, "w": 600, "h": 600,
                     "samples": 24, "engine": "BLENDER_EEVEE_NEXT",
                     "camera": "HexCam"},
                    timeout=300.0,
                )
            except BlenderError as e:
                print(f"[{label}] RENDER-FAIL: {e}")
                continue

            out_path = Path(args.outdir) / f"{label}.png"
            out_path.write_bytes(base64.b64decode(img["image_base64"]))
            print(f"[{label}] -> {out_path}")
    finally:
        await cli.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
