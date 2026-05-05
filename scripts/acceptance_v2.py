"""v2.0 acceptance gate — studio scene end-to-end.

Per plan-v2 §8 "End-to-end smoke (replaces v1 studio scene)":
  1. Single create_objects(...) call rebuilds the full studio scene.
  2. scene_diff() baseline -> add_modifier on Pedestal -> scene_diff() shows
     exactly Pedestal modified.
  3. render_region returns a PNG of the ring closeup.

Exits 0 only if all three gates pass.
"""

import argparse
import asyncio
import base64
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_server"))

from blender_mcp.blender_client import BlenderError, BlenderWS  # noqa: E402


STUDIO_SPECS = [
    # Cyclorama: large ground plane
    {"kind": "plane", "name": "Cyclorama",
     "size": 12.0, "location": [0.0, 0.0, 0.0]},
    # Pedestal: short cylinder
    {"kind": "cylinder", "name": "Pedestal",
     "size": 0.6, "location": [0.0, 0.0, 0.15],
     "scale": [1.0, 1.0, 0.5]},
    # Subject: sphere on top of pedestal
    {"kind": "sphere", "name": "HeroSphere",
     "size": 0.35, "location": [0.0, 0.0, 0.6]},
    # Three rings around the sphere (toruses)
    {"kind": "torus", "name": "Ring_Inner",
     "size": 0.55, "minor_ratio": 0.04, "location": [0.0, 0.0, 0.6]},
    {"kind": "torus", "name": "Ring_Mid",
     "size": 0.75, "minor_ratio": 0.04, "location": [0.0, 0.0, 0.6],
     "rotation": [0.4, 0.0, 0.0]},
    {"kind": "torus", "name": "Ring_Outer",
     "size": 1.00, "minor_ratio": 0.04, "location": [0.0, 0.0, 0.6],
     "rotation": [0.0, 0.4, 0.0]},
    # Seven lights: 1 key, 1 fill, 1 rim, 4 accent
    {"kind": "light", "name": "Key", "light_type": "AREA",
     "location": [3.0, -2.5, 3.5], "energy": 800.0,
     "area_size": 1.5, "color": [1.0, 0.96, 0.9]},
    {"kind": "light", "name": "Fill", "light_type": "AREA",
     "location": [-3.5, -1.5, 2.5], "energy": 300.0,
     "area_size": 2.0, "color": [0.85, 0.92, 1.0]},
    {"kind": "light", "name": "Rim", "light_type": "SPOT",
     "location": [0.0, 3.5, 2.0], "energy": 500.0,
     "spot_size": 1.2, "color": [1.0, 1.0, 1.0]},
    {"kind": "light", "name": "Accent_NE", "light_type": "POINT",
     "location": [2.0, 2.0, 1.2], "energy": 80.0},
    {"kind": "light", "name": "Accent_NW", "light_type": "POINT",
     "location": [-2.0, 2.0, 1.2], "energy": 80.0},
    {"kind": "light", "name": "Accent_SE", "light_type": "POINT",
     "location": [2.0, -2.0, 1.2], "energy": 80.0},
    {"kind": "light", "name": "Accent_SW", "light_type": "POINT",
     "location": [-2.0, -2.0, 1.2], "energy": 80.0},
    # Camera
    {"kind": "camera", "name": "ShotCam",
     "location": [3.5, -3.5, 2.0], "rotation": [1.1, 0.0, 0.78],
     "lens": 50.0, "set_active": True},
]


def banner(msg: str) -> None:
    print()
    print("=" * 70)
    print(msg)
    print("=" * 70)


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--token", default=os.environ.get("BLENDER_MCP_TOKEN", ""))
    p.add_argument("--url",   default=os.environ.get(
        "BLENDER_MCP_URL", "ws://127.0.0.1:9876"))
    args = p.parse_args()

    cli = BlenderWS(url=args.url, token=args.token)
    gates: list[tuple[str, bool, str]] = []

    try:
        # ---------- 0. Wipe scene so the run is reproducible ----------
        banner("0. Reset scene")
        wipe_code = (
            "import bpy\n"
            "for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)\n"
            "for c in list(bpy.data.collections):\n"
            "    if c.name != 'Collection':\n"
            "        bpy.data.collections.remove(c)\n"
            "result = {'objects': len(bpy.data.objects)}\n"
        )
        await cli.call("exec.python",
                       {"code": wipe_code, "mode": "trusted"}, timeout=15.0)
        print("  scene reset")

        # ---------- 1. Build studio in ONE call ----------
        banner("1. Single create_objects call")
        t0 = time.perf_counter()
        out = await cli.call("create_objects", {"specs": STUDIO_SPECS},
                             timeout=30.0)
        dt = (time.perf_counter() - t0) * 1000
        n = out.get("count", 0)
        errs = out.get("errors", [])
        print(f"  created {n} objects in {dt:.0f} ms; errors={len(errs)}")
        if errs:
            for e in errs[:3]:
                print(f"    ! {e}")
        ok_build = (n == len(STUDIO_SPECS) and not errs)
        gates.append(("Gate 1: studio scene built in one call",
                      ok_build,
                      f"{n}/{len(STUDIO_SPECS)} objects, errors={len(errs)}"))

        # ---------- 2a. scene_diff baseline ----------
        banner("2a. scene_diff baseline")
        baseline = await cli.call("scene_diff", {}, timeout=10.0)
        snap = baseline.get("snapshot_id")
        print(f"  snapshot_id={snap}, baseline={baseline.get('baseline')}")
        ok_baseline = bool(snap)

        # ---------- 2b. add_modifier on Pedestal ----------
        banner("2b. add_modifier BEVEL on Pedestal")
        mod_out = await cli.call("add_modifier", {
            "object": "Pedestal",
            "type": "BEVEL",
            "name": "Bevel_Edge",
            "properties": {"width": 0.03, "segments": 4},
        }, timeout=10.0)
        print(f"  add_modifier result: {mod_out}")

        # ---------- 2c. diff again — must show ONLY Pedestal modified ----------
        banner("2c. scene_diff vs baseline")
        diff = await cli.call("scene_diff", {"snapshot_id": snap}, timeout=10.0)
        added = diff.get("added", [])
        removed = diff.get("removed", [])
        modified = diff.get("modified", [])
        print(f"  added={added}")
        print(f"  removed={removed}")
        print(f"  modified={modified}")
        modified_names = [m.get("name") for m in modified]
        pedestal_entry = next(
            (m for m in modified if m.get("name") == "Pedestal"), None)
        ok_diff = (
            ok_baseline
            and not added and not removed
            and modified_names == ["Pedestal"]
            and pedestal_entry is not None
            and "modifiers" in (pedestal_entry.get("fields") or [])
        )
        gates.append(("Gate 2: scene_diff isolates the Pedestal change",
                      ok_diff,
                      f"added={added}, removed={removed}, modified={modified_names}"))

        # ---------- 3. render_region ring closeup ----------
        banner("3. render_region")
        # Set a small render resolution so the region maths is sane.
        await cli.call("set_property", {
            "path": "bpy.context.scene.render.resolution_x", "value": 640,
        }, timeout=5.0)
        await cli.call("set_property", {
            "path": "bpy.context.scene.render.resolution_y", "value": 360,
        }, timeout=5.0)
        # Use EEVEE for speed; the gate is about the round-trip and PNG bytes.
        try:
            await cli.call("set_property", {
                "path": "bpy.context.scene.render.engine", "value": "BLENDER_EEVEE_NEXT",
            }, timeout=5.0)
        except BlenderError:
            await cli.call("set_property", {
                "path": "bpy.context.scene.render.engine", "value": "BLENDER_EEVEE",
            }, timeout=5.0)

        t0 = time.perf_counter()
        rr = await cli.call("render.region", {
            "x": 192, "y": 80, "w": 256, "h": 200,
            "samples": 16,
        }, timeout=120.0)
        dt = (time.perf_counter() - t0) * 1000
        b64 = rr.get("image_base64") or rr.get("png_b64") or ""
        nbytes = len(base64.b64decode(b64)) if b64 else 0
        print(f"  render_region returned {nbytes} bytes in {dt:.0f} ms")
        out_path = Path(__file__).resolve().parent / "studio_region.png"
        if b64:
            out_path.write_bytes(base64.b64decode(b64))
            print(f"  wrote {out_path}")
        ok_render = nbytes > 1000  # any non-trivial PNG
        gates.append(("Gate 3: render_region returns a PNG",
                      ok_render,
                      f"{nbytes} bytes in {dt:.0f} ms"))

        # ---------- Summary ----------
        banner("v2.0 ACCEPTANCE SUMMARY")
        passed = sum(1 for _, ok, _ in gates if ok)
        for name, ok, detail in gates:
            tag = "PASS" if ok else "FAIL"
            print(f"  [{tag}] {name}  -- {detail}")
        print()
        print(f"  Result: {passed}/{len(gates)} gates passed")
        return 0 if passed == len(gates) else 1

    except BlenderError as e:
        print(f"FAIL: {e.code}: {e}")
        if e.traceback:
            print(e.traceback)
        return 2
    finally:
        await cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
