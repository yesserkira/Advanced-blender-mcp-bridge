"""End-to-end smoke test against the running Blender add-on.

Usage:
    cd mcp_server
    .\.venv\Scripts\python.exe ..\scripts\smoke_v2.py

Requires the BLENDER_MCP_TOKEN env var (or pass --token).
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Make blender_mcp importable when run from repo root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_server"))

from blender_mcp.blender_client import BlenderError, BlenderWS  # noqa: E402


PASS = "[OK]  "
FAIL = "[FAIL]"
INFO = "[..]  "


class Runner:
    def __init__(self, client: BlenderWS):
        self.client = client
        self.passed = 0
        self.failed = 0
        self.failures: list[tuple[str, str]] = []

    async def step(self, name: str, op: str, args: dict | None = None,
                   timeout: float = 30.0, expect_keys: list[str] | None = None):
        print(f"{INFO} {name:<48s} -> {op}")
        try:
            result = await self.client.call(op, args or {}, timeout=timeout)
        except BlenderError as e:
            self.failed += 1
            self.failures.append((name, f"BlenderError {e.code}: {e}"))
            print(f"{FAIL} {name}: {e.code}: {e}")
            return None
        except Exception as e:
            self.failed += 1
            self.failures.append((name, f"{type(e).__name__}: {e}"))
            print(f"{FAIL} {name}: {type(e).__name__}: {e}")
            return None

        if expect_keys and isinstance(result, dict):
            missing = [k for k in expect_keys if k not in result]
            if missing:
                self.failed += 1
                self.failures.append((name, f"missing keys: {missing}; got {list(result)[:8]}"))
                print(f"{FAIL} {name}: missing keys {missing}")
                return result

        self.passed += 1
        preview = repr(result)
        if len(preview) > 100:
            preview = preview[:97] + "..."
        print(f"{PASS} {name}: {preview}")
        return result


async def run(token: str, url: str):
    client = BlenderWS(url=url, token=token)
    r = Runner(client)

    try:
        # --- 0. Connectivity --------------------------------------------
        print("\n=== 0. Connectivity ===")
        await r.step("ping", "ping")

        # --- P2. Awareness ----------------------------------------------
        print("\n=== P2. Awareness (query / list / describe_api) ===")
        await r.step("list objects", "list", {"kind": "objects"})
        await r.step("query scene", "query", {"target": "scene"})
        await r.step("query render settings", "query", {"target": "render"})
        await r.step("describe SubsurfModifier", "describe_api",
                     {"rna_path": "SubsurfModifier"},
                     expect_keys=["rna", "properties"])
        await r.step("describe ShaderNodeBsdfPrincipled", "describe_api",
                     {"rna_path": "ShaderNodeBsdfPrincipled"})
        await r.step("audit log tail", "audit.read", {"limit": 10})

        # --- Clean slate ------------------------------------------------
        print("\n=== Clean slate ===")
        # Best-effort delete any prior smoke objects (ignore failures)
        for name in ["Smoke_Cube", "Smoke_Sphere", "Smoke_Light", "Smoke_Cam",
                     "Smoke_Plane"]:
            try:
                await client.call("object.delete", {"object": name})
            except Exception:
                pass

        # --- P4. Composition --------------------------------------------
        print("\n=== P4. Composition (create_objects) ===")
        await r.step(
            "create_objects (cube + sphere + light + camera)",
            "create_objects",
            {"specs": [
                {"kind": "plane", "name": "Smoke_Plane", "size": 10,
                 "location": [0, 0, 0]},
                {"kind": "cube", "name": "Smoke_Cube",
                 "location": [-1.5, 0, 1]},
                {"kind": "sphere", "name": "Smoke_Sphere",
                 "location": [1.5, 0, 1]},
                {"kind": "light", "name": "Smoke_Light", "light_type": "AREA",
                 "location": [3, -3, 5], "energy": 500, "area_size": 2},
                {"kind": "camera", "name": "Smoke_Cam",
                 "location": [7, -7, 5], "rotation": [1.1, 0, 0.785],
                 "lens": 50, "set_active": True},
            ]},
            timeout=60.0,
            expect_keys=["created", "count"],
        )

        # --- Snapshot baseline ------------------------------------------
        print("\n=== P6. scene_diff (baseline) ===")
        snap = await r.step("scene_diff baseline", "scene_diff",
                            {"snapshot_id": None})
        snap_id = (snap or {}).get("snapshot_id")

        # --- P3. Generic modifier (batch) -------------------------------
        print("\n=== P3. add_modifier (batch) ===")
        await r.step(
            "add_modifier batch (subsurf+bevel)",
            "add_modifier",
            {"items": [
                {"object": "Smoke_Cube", "type": "SUBSURF",
                 "properties": {"levels": 2}},
                {"object": "Smoke_Cube", "type": "BEVEL",
                 "properties": {"width": 0.05, "segments": 3}},
                {"object": "Smoke_Sphere", "type": "SUBSURF",
                 "properties": {"levels": 2}},
            ]},
            expect_keys=["batch", "count", "ok_count"],
        )

        # --- P3. build_nodes (shader) -----------------------------------
        print("\n=== P3. build_nodes (shader graph) ===")
        await r.step(
            "build_nodes Gold material (create)",
            "build_nodes",
            {"target": "material:Smoke_Gold!", "graph": {
                "nodes": [
                    {"name": "bsdf", "type": "ShaderNodeBsdfPrincipled",
                     "location": [0, 0],
                     "inputs": {"Base Color": [1.0, 0.78, 0.34, 1.0],
                                "Metallic": 1.0, "Roughness": 0.18}},
                    {"name": "out", "type": "ShaderNodeOutputMaterial",
                     "location": [400, 0]},
                ],
                "links": [{"from": "bsdf.BSDF", "to": "out.Surface"}],
            }},
        )
        await r.step("assign_material Gold -> Sphere", "assign_material",
                     {"object": "Smoke_Sphere", "material": "Smoke_Gold"})

        # --- P3. set/get_property --------------------------------------
        print("\n=== P3. set_property / get_property ===")
        await r.step("set cycles samples=64", "set_property",
                     {"path": "bpy.context.scene.cycles.samples",
                      "value": 64})
        await r.step("get cycles samples", "get_property",
                     {"path": "bpy.context.scene.cycles.samples"})
        await r.step("set view_transform=AgX", "set_property",
                     {"path": "bpy.context.scene.view_settings.view_transform",
                      "value": "AgX"})

        # --- P3. call_operator -----------------------------------------
        print("\n=== P3. call_operator ===")
        await r.step("call_operator object.shade_smooth on selection",
                     "call_operator",
                     {"operator": "object.shade_smooth"})

        # --- Snapshot diff ----------------------------------------------
        if snap_id:
            print("\n=== P6. scene_diff (after edits) ===")
            await r.step("scene_diff vs baseline", "scene_diff",
                         {"snapshot_id": snap_id},
                         expect_keys=["snapshot_id"])

        # --- P6. Visual feedback ----------------------------------------
        print("\n=== P6. Visual feedback ===")
        await r.step("viewport_screenshot 512x512", "render.viewport_screenshot",
                     {"w": 512, "h": 512, "show_overlays": False},
                     timeout=60.0,
                     expect_keys=["image_base64", "mime"])
        await r.step("render_region 256x256 EEVEE", "render.region",
                     {"x": 0, "y": 0, "w": 256, "h": 256, "samples": 8,
                      "engine": "BLENDER_EEVEE_NEXT", "camera": "Smoke_Cam"},
                     timeout=120.0)
        await r.step("bake_preview Smoke_Gold", "render.bake_preview",
                     {"material": "Smoke_Gold", "w": 256, "h": 256},
                     timeout=120.0)

        # --- P4. Transaction (atomic) ----------------------------------
        print("\n=== P4. transaction (atomic) ===")
        await r.step(
            "transaction add modifier + assign material",
            "transaction",
            {"label": "smoke_tx", "steps": [
                {"tool": "add_modifier", "args": {
                    "object": "Smoke_Plane", "type": "SOLIDIFY",
                    "properties": {"thickness": 0.1}}},
                {"tool": "assign_material", "args": {
                    "object": "Smoke_Plane", "material": "Smoke_Gold"}},
            ]},
            timeout=60.0,
            expect_keys=["ok", "step_count"],
        )

        # --- exec.python ------------------------------------------------
        print("\n=== exec.python ===")
        await r.step("exec.python (safe)", "exec.python",
                     {"code": "import bpy\nresult = len(bpy.data.objects)",
                      "timeout": 5},
                     expect_keys=["executed"])

    finally:
        await client.close()

    print("\n" + "=" * 60)
    print(f"Result: {r.passed} passed, {r.failed} failed")
    if r.failures:
        print("\nFailures:")
        for name, err in r.failures:
            print(f"  - {name}: {err}")
    print("=" * 60)
    return 0 if r.failed == 0 else 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--token", default=os.environ.get("BLENDER_MCP_TOKEN", ""))
    p.add_argument("--url", default=os.environ.get(
        "BLENDER_MCP_URL", "ws://127.0.0.1:9876"))
    args = p.parse_args()
    if not args.token:
        print("ERROR: provide --token or set BLENDER_MCP_TOKEN env var.")
        print("Token is shown in Blender > Edit > Preferences > Add-ons > "
              "Blender MCP Bridge > preferences.")
        return 2
    return asyncio.run(run(args.token, args.url))


if __name__ == "__main__":
    sys.exit(main())
