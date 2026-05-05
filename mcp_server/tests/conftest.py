"""Shared test fixtures for v2.0."""

import json

import pytest
import websockets


class FakeBlenderServer:
    """Minimal fake Blender WS server returning canned responses by op name."""

    def __init__(self, host="127.0.0.1", port=19876):
        self.host = host
        self.port = port
        self._server = None
        self._handlers: dict[str, callable] = {
            "ping": lambda args: "pong",

            # P2 introspection
            "query": lambda args: {
                "$rna": "Object",
                "name": args["target"].split(":", 1)[-1].split(".")[0],
                "location": [0.0, 0.0, 0.0],
            },
            "list": lambda args: [{"name": "Cube", "type": "MESH"}],
            "describe_api": lambda args: {
                "rna": args["rna_path"],
                "description": "fake",
                "properties": [{"name": "levels", "type": "INT", "soft_min": 0, "soft_max": 6,
                                "default": 1, "description": "", "readonly": False}],
                "functions": [],
            },
            "audit.read": lambda args: {"entries": [], "log_dir": "/tmp"},

            # P3 generic
            "add_modifier": lambda args: {
                "object": args.get("object", "?"),
                "modifier": args.get("name") or args.get("type"),
                "type": args.get("type"),
                "index": 0,
                "properties_set": list((args.get("properties") or {}).keys()),
                "skipped": [],
            },
            "remove_modifier": lambda args: {"object": args["object"], "removed": args["name"]},
            "build_nodes": lambda args: {
                "target": args["target"],
                "tree": "fake_tree",
                "node_count": len((args.get("graph") or {}).get("nodes") or []),
                "link_count": len((args.get("graph") or {}).get("links") or []),
                "created": [n.get("name") or n.get("id") for n in (args.get("graph") or {}).get("nodes") or []],
                "skipped_properties": [],
                "links": [],
            },
            "assign_material": lambda args: {
                "object": args["object"], "material": args["material"], "slot": args.get("slot", 0),
            },
            "set_property": lambda args: {"path": args["path"], "value": args["value"]},
            "get_property": lambda args: {"path": args["path"], "value": "fake"},
            "call_operator": lambda args: {
                "operator": args["operator"], "result": ["FINISHED"], "active_object": "Cube",
            },

            # Mesh + scene basics
            "mesh.create_primitive": lambda args: {
                "name": args.get("name") or args["kind"].capitalize(),
                "kind": args["kind"], "polys": 6, "vertices": 8,
                "location": args.get("location") or [0, 0, 0],
            },
            "object.transform": lambda args: {
                "name": args.get("object") or args.get("name"),
                "location": args.get("location") or [0, 0, 0],
                "rotation_euler": args.get("rotation_euler") or [0, 0, 0],
                "scale": args.get("scale") or [1, 1, 1],
            },
            "object.delete": lambda args: {
                "deleted": args.get("object") or args.get("name"),
                "remaining_count": 0,
            },

            # P4 composition
            "create_objects": lambda args: {
                "created": [{"name": s.get("name") or s["kind"], "kind": s["kind"], "type": "MESH",
                             "location": s.get("location") or [0, 0, 0], "modifiers": [],
                             "collection": "Scene Collection"} for s in args["specs"]],
                "count": len(args["specs"]),
                "errors": [],
            },
            "transaction": lambda args: {
                "ok": True, "label": args.get("label", "tx"),
                "step_count": len(args["steps"]),
                "results": [{"tool": s["tool"], "result": {}} for s in args["steps"]],
            },
            "apply_to_selection": lambda args: {
                "tool": args["tool"], "count": 1,
                "results": [{"object": "Cube", "ok": True, "result": {}}],
            },

            # Animation
            "animation.keyframe": lambda args: {
                "object": args["object_name"], "data_path": args["data_path"],
                "frame": args["frame"], "value": args.get("value") or [0, 0, 0],
            },

            # Assets
            "import_asset": lambda args: {
                "format": args.get("format", "glb"), "path": args["path"],
                "imported_objects": ["Imported"], "count": 1,
            },
            "link_blend": lambda args: {
                "path": args["path"], "link": args["link"],
                "loaded": {db["type"]: [db["name"]] for db in args["datablocks"]},
            },
            "list_assets": lambda args: {
                "directory": args["directory"], "count": 1,
                "assets": [{"path": args["directory"] + "/x.glb", "format": "gltf", "name": "x.glb"}],
            },

            # Visual
            "render.viewport_screenshot": lambda args: {
                "image_base64": "iVBORw0KGgo=", "mime": "image/png",
                "width": args.get("w", 1024), "height": args.get("h", 1024), "size_bytes": 0,
            },
            "render.region": lambda args: {
                "image_base64": "iVBORw0KGgo=", "mime": "image/png",
                "x": args["x"], "y": args["y"], "w": args["w"], "h": args["h"],
                "samples": args.get("samples", 32), "engine": args.get("engine") or "CYCLES",
                "size_bytes": 0,
            },
            "render.bake_preview": lambda args: {
                "image_base64": "iVBORw0KGgo=", "mime": "image/png",
                "material": args["material"], "width": args.get("w", 256), "height": args.get("h", 256),
            },
            "scene_diff": lambda args: {
                "snapshot_id": args.get("snapshot_id") or "snap_xyz",
                "baseline": True, "object_count": 1,
            },

            # Exec
            "exec.python": lambda args: {
                "executed": True, "mode": args.get("mode", "safe"),
                "lines": len(args.get("code", "").splitlines()),
                "result_preview": None,
            },
        }

    def add_handler(self, op: str, fn):
        self._handlers[op] = fn

    async def _handle_one(self, websocket):
        async for raw in websocket:
            msg = json.loads(raw)
            op = msg.get("op", "")
            args = msg.get("args", {}) or {}

            items = args.get("items") if isinstance(args, dict) else None
            if isinstance(items, list):
                handler = self._handlers.get(op)
                if handler is None:
                    response = {"id": msg.get("id"), "ok": False,
                                "error": {"code": "NOT_FOUND",
                                          "message": f"Unknown op: {op}"}}
                else:
                    common = args.get("common") or {}
                    results, errors = [], []
                    for i, item in enumerate(items):
                        merged = dict(common)
                        merged.update(item if isinstance(item, dict) else {"value": item})
                        try:
                            results.append(handler(merged))
                        except Exception as e:
                            errors.append({"index": i, "error": str(e),
                                           "type": type(e).__name__})
                    response = {"id": msg.get("id"), "ok": True,
                                "result": {"batch": True, "op": op,
                                           "count": len(items),
                                           "ok_count": len(results),
                                           "error_count": len(errors),
                                           "results": results, "errors": errors}}
            else:
                handler = self._handlers.get(op)
                if handler:
                    result = handler(args)
                    response = {"id": msg.get("id"), "ok": True, "result": result}
                else:
                    response = {"id": msg.get("id"), "ok": False,
                                "error": {"code": "NOT_FOUND",
                                          "message": f"Unknown op: {op}"}}
            await websocket.send(json.dumps(response))

    async def start(self):
        self._server = await websockets.serve(self._handle_one, self.host, self.port)

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()


@pytest.fixture
async def fake_blender():
    server = FakeBlenderServer()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
def blender_token():
    return "test-token-for-testing"
