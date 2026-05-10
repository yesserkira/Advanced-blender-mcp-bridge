"""Shared test fixtures for v2.0."""

import json

import pytest
import websockets


@pytest.fixture(autouse=True)
def _reset_snapshot_cache():
    """Phase 3: the per-process snapshot cache is module-global, so it would
    otherwise leak cached responses (and a non-zero epoch) across tests.
    Cheap to reset; runs for every test."""
    from blender_mcp import server as _server
    _server._snapshot_cache.clear()
    yield
    _server._snapshot_cache.clear()


class FakeBlenderServer:
    """Minimal fake Blender WS server returning canned responses by op name."""

    def __init__(self, host="127.0.0.1", port=0):
        # port=0 lets the OS pick a free ephemeral port. Required for
        # ``pytest-xdist`` parallel workers, which would otherwise collide
        # on a fixed port and fail with EADDRINUSE.
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
                **(
                    {"image_path": "/tmp/fake/abc.png", "image_sha256": "abc"}
                    if args.get("transport") == "file"
                    else {"image_base64": "iVBORw0KGgo="}
                ),
                "mime": "image/png",
                "width": args.get("w", 1024), "height": args.get("h", 1024), "size_bytes": 0,
            },
            "render.region": lambda args: {
                **(
                    {"image_path": "/tmp/fake/abc.png", "image_sha256": "abc"}
                    if args.get("transport") == "file"
                    else {"image_base64": "iVBORw0KGgo="}
                ),
                "mime": "image/png",
                "x": args["x"], "y": args["y"], "w": args["w"], "h": args["h"],
                "samples": args.get("samples", 32), "engine": args.get("engine") or "CYCLES",
                "size_bytes": 0,
            },
            "render.bake_preview": lambda args: {
                **(
                    {"image_path": "/tmp/fake/abc.png", "image_sha256": "abc"}
                    if args.get("transport") == "file"
                    else {"image_base64": "iVBORw0KGgo="}
                ),
                "mime": "image/png",
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

            # v2.2: scene snapshot (resource backend)
            "scene.snapshot": lambda args: ({
                "version": 1, "scene": "Scene", "frame": 1,
                "frame_range": [1, 250], "active_camera": "Camera",
                "active_object": "Cube", "selection": ["Cube"],
                "render": {"engine": "CYCLES", "resolution": [1920, 1080],
                           "resolution_percentage": 100, "fps": 24,
                           "samples": 128},
                "counts": {"objects": 3, "materials": 1, "meshes": 1,
                           "lights": 1, "cameras": 1, "collections": 1,
                           "node_groups": 0},
                "hash": "deadbeefcafebabe",
            } if args.get("summary") else {
                "version": 1, "scene": "Scene", "frame": 1,
                "frame_range": [1, 250], "active_camera": "Camera",
                "active_object": "Cube", "selection": ["Cube"],
                "render": {"engine": "CYCLES", "resolution": [1920, 1080],
                           "resolution_percentage": 100, "fps": 24,
                           "samples": 128},
                "counts": {"objects": 3, "materials": 1, "meshes": 1,
                           "lights": 1, "cameras": 1, "collections": 1,
                           "node_groups": 0},
                "objects": [
                    {"name": "Cube", "type": "MESH", "visible": True,
                     "location": [0, 0, 0], "rotation_euler": [0, 0, 0],
                     "scale": [1, 1, 1], "polys": 6},
                    {"name": "Light", "type": "LIGHT", "visible": True,
                     "location": [4, 1, 6], "rotation_euler": [0, 0, 0],
                     "scale": [1, 1, 1], "light_type": "POINT", "energy": 1000.0},
                    {"name": "Camera", "type": "CAMERA", "visible": True,
                     "location": [7, -7, 5], "rotation_euler": [1.1, 0, 0.8],
                     "scale": [1, 1, 1], "lens": 50.0},
                ],
                "collections": {"name": "Scene Collection",
                                "objects": ["Cube", "Light", "Camera"],
                                "children": []},
                "materials": [{"name": "Material", "users": 1}],
                "hash": "deadbeefcafebabe",
            }),

            # v2.2: geonodes ops (return shapes mirror the real capability)
            "geonodes.create_modifier": lambda args: {
                "object": args["object"],
                "modifier": args.get("name") or "GeometryNodes",
                "group": args.get("group") or f"{args['object']}_GN",
                "created_group": args.get("group") is None,
            },
            "geonodes.describe_group": lambda args: {
                "name": args["name"],
                "inputs": [
                    {"name": "Geometry", "identifier": "Input_0",
                     "socket_type": "NodeSocketGeometry", "in_out": "INPUT"},
                    {"name": "Density", "identifier": "Input_1",
                     "socket_type": "NodeSocketFloat", "in_out": "INPUT",
                     "default_value": 10.0},
                ],
                "outputs": [
                    {"name": "Geometry", "identifier": "Output_0",
                     "socket_type": "NodeSocketGeometry", "in_out": "OUTPUT"},
                ],
                "node_count": 4, "link_count": 3,
            },
            "geonodes.set_input": lambda args: {
                "object": args["object"],
                "modifier": args.get("modifier") or "GeometryNodes",
                "input": args["input"], "identifier": "Input_1",
                "value": args.get("value"),
            },
            "geonodes.animate_input": lambda args: {
                "object": args["object"],
                "modifier": args.get("modifier") or "GeometryNodes",
                "identifier": "Input_1",
                "count": len(args.get("keyframes") or []),
            },
            "geonodes.create_group": lambda args: {
                "name": args["name"],
                "input_count": len(args.get("inputs") or []),
                "output_count": len(args.get("outputs") or []),
                "created": True,
            },
            "geonodes.realize": lambda args: {
                "object": args["object"],
                "applied": args.get("modifier") or "GeometryNodes",
            },
            "geonodes.list_presets": lambda args: {
                "presets": [
                    {"name": "scatter-on-surface", "title": "Scatter instances on surface",
                     "input_count": 6, "output_count": 1, "node_count": 8, "link_count": 14},
                    {"name": "array-along-curve", "title": "Array along curve",
                     "input_count": 5, "output_count": 1, "node_count": 9, "link_count": 12},
                    {"name": "displace-noise", "title": "Displace mesh by noise",
                     "input_count": 4, "output_count": 1, "node_count": 11, "link_count": 13},
                ],
                "count": 3,
            },
            "geonodes.get_preset": lambda args: {
                "name": args["name"],
                "title": "Stub preset",
                "group": {"name": "BMCP_X", "inputs": [], "outputs": []},
                "graph": {"nodes": [], "links": []},
            },
            "geonodes.apply_preset": lambda args: {
                "preset": args["preset"],
                "group": args.get("group") or "BMCP_Stub",
                "node_count": 5,
                "link_count": 7,
                **({"object": args["object"], "modifier": args.get("modifier") or "GeometryNodes"}
                   if args.get("object") else {}),
            },

            # v2.4: rename
            "rename": lambda args: {
                "kind": args["kind"],
                "from": args["from"],
                "to": args["to"],
                "final_name": args["to"],
            },

            # v2.4: spatial helpers
            "place_above": lambda args: {
                "object": args["object"],
                "target": args["target"],
                "gap": args.get("gap", 0.0),
                "location": [0.0, 0.0, 2.0],
            },
            "align_to": lambda args: {
                "object": args["object"],
                "target": args["target"],
                "mode": args.get("mode", "center"),
                "axes": args.get("axes", ["x", "y", "z"]),
                "location": [0.0, 0.0, 0.0],
            },
            "array_around": lambda args: {
                "object": args["object"],
                "count": args.get("count", 6),
                "radius": args.get("radius", 2.0),
                "created": [f"{args['object']}_arr_{i}" for i in range(args.get("count", 6))],
            },
            "distribute": lambda args: {
                "objects": args["objects"],
                "count": len(args["objects"]),
                "start": args.get("start", [0, 0, 0]),
                "end": args.get("end", [10, 0, 0]),
            },
            "look_at": lambda args: {
                "object": args["object"],
                "target": args.get("target"),
                "point": args.get("point"),
                "rotation_euler": [0.0, 0.0, 0.0],
            },
            "bbox_info": lambda args: {
                "object": args["object"],
                "min": [-1, -1, -1],
                "max": [1, 1, 1],
                "size": [2, 2, 2],
                "center": [0, 0, 0],
            },

            # v2.5: selection
            "select": lambda args: {
                "selected": args["objects"],
                "active": args.get("active") or args["objects"][-1],
                "count": len(args["objects"]),
            },
            "deselect_all": lambda args: {
                "deselected_count": 3,
            },
            "set_active": lambda args: {
                "object": args["object"],
                "selected": args.get("select", True),
            },
            "select_all": lambda args: {
                "count": 5,
                "type": args.get("type"),
            },

            # v2.5: object ops
            "duplicate_object": lambda args: {
                "original": args["object"],
                "new_name": args.get("name") or f"{args['object']}.copy",
                "linked": args.get("linked", False),
            },
            "set_visibility": lambda args: {
                "objects": [args["object"]] if args.get("object") else args.get("objects", []),
                "viewport": args.get("viewport"),
                "render": args.get("render"),
            },
            "set_parent": lambda args: {
                "parent": args["parent"],
                "children": args.get("children") or ([args["child"]] if args.get("child") else []),
                "keep_transform": args.get("keep_transform", True),
            },
            "clear_parent": lambda args: {
                "objects": [args["object"]] if args.get("object") else args.get("objects", []),
                "keep_transform": args.get("keep_transform", True),
            },

            # v2.5: collections
            "create_collection": lambda args: {
                "name": args["name"],
                "parent": args.get("parent", "Scene Collection"),
            },
            "delete_collection": lambda args: {
                "name": args["name"],
                "unlink_objects": args.get("unlink_objects", False),
            },
            "move_to_collection": lambda args: {
                "collection": args["collection"],
                "objects": [args["object"]] if args.get("object") else args.get("objects", []),
                "unlink_others": args.get("unlink_others", True),
            },
            "list_collections": lambda args: {
                "collections": [
                    {"name": "Scene Collection", "object_count": 3, "children": ["Lamps"]},
                    {"name": "Lamps", "object_count": 1, "children": []},
                ],
                "count": 2,
            },

            # ---- v3.0 Tier-1 capability batch ---------------------------
            "create_light": lambda args: {
                "name": args.get("name") or args["kind"].capitalize(),
                "data": args.get("name") or args["kind"].capitalize(),
                "kind": args["kind"],
                "type": args["kind"].upper(),
                "location": args.get("location") or [0.0, 0.0, 0.0],
                "energy": args.get("energy", 1000.0),
                "color": (args.get("color") or [1.0, 1.0, 1.0])[:3],
            },
            "create_camera": lambda args: {
                "name": args.get("name") or "Camera",
                "data": args.get("name") or "Camera",
                "type": args.get("type") or "PERSP",
                "lens": args.get("lens", 50.0),
                "is_active": bool(args.get("set_active")),
            },
            "set_active_camera": lambda args: {
                "camera": args["name"], "scene": "Scene",
            },
            "create_empty": lambda args: {
                "name": args.get("name") or "Empty",
                "display": args.get("display") or "PLAIN_AXES",
                "location": args.get("location") or [0.0, 0.0, 0.0],
            },
            "create_text": lambda args: {
                "name": args.get("name") or "Text",
                "data": args.get("name") or "Text",
                "body": args.get("body", "Text"),
                "size": args.get("size", 1.0),
                "location": args.get("location") or [0.0, 0.0, 0.0],
            },
            "create_curve": lambda args: {
                "name": args.get("name") or "Curve",
                "data": args.get("name") or "Curve",
                "kind": args.get("kind") or "bezier",
                "point_count": len(args.get("points") or []),
                "closed": bool(args.get("closed")),
                "location": args.get("location") or [0.0, 0.0, 0.0],
            },
            "create_armature": lambda args: {
                "name": args.get("name") or "Armature",
                "data": args.get("name") or "Armature",
                "bones_created": [b.get("name") for b in (args.get("bones") or []) if b.get("name")],
                "bone_count": len(args.get("bones") or []),
                "location": args.get("location") or [0.0, 0.0, 0.0],
            },
            "load_image": lambda args: {
                "name": args.get("name") or args["path"].split("/")[-1].split("\\")[-1],
                "filepath": args["path"],
                "size": [1024, 1024],
                "channels": 4,
                "is_packed": bool(args.get("pack")),
            },
            "create_image": lambda args: {
                "name": args["name"],
                "size": [args.get("width", 1024), args.get("height", 1024)],
                "channels": 4,
                "is_float": bool(args.get("float", False)),
            },

            # mode + mesh edit DSL + mesh read
            "set_mode": lambda args: {
                "ok": True,
                "mode": args["mode"].upper(),
                "object": args.get("object") or "Cube",
                "type": "MESH",
                "previous_mode": "OBJECT",
            },
            "mesh_edit": lambda args: {
                "object": args["object"],
                "vertices_before": 8, "vertices_after": 8,
                "edges_before": 12, "edges_after": 12,
                "faces_before": 6, "faces_after": 6,
                "results": [{"index": i, "op": op.get("op")}
                            for i, op in enumerate(args.get("ops") or [])],
                "errors": [],
                "ok_count": len(args.get("ops") or []),
                "error_count": 0,
            },
            "mesh_read": lambda args: {
                "object": args["object"],
                "counts": {"vertices": 8, "edges": 12, "faces": 6, "loops": 24},
                "start": args.get("start", 0),
                "limit": args.get("limit", 1000),
                "vertices": [[0, 0, 0], [1, 0, 0]] if "vertices" in (args.get("what") or ["vertices"]) else None,
            },

            # constraints
            "add_constraint": lambda args: {
                "owner": args["object"] + (
                    f".pose.bones['{args['bone']}']" if args.get("bone") else ""
                ),
                "owner_kind": "bone" if args.get("bone") else "object",
                "name": args.get("name") or args["type"].title().replace("_", " "),
                "type": args["type"],
                "index": 0,
                "properties_set": list((args.get("properties") or {}).keys()),
                "skipped": [],
            },
            "remove_constraint": lambda args: {
                "owner": args["object"],
                "owner_kind": "bone" if args.get("bone") else "object",
                "removed": args["name"],
            },
            "list_constraints": lambda args: {
                "owner": args["object"],
                "owner_kind": "bone" if args.get("bone") else "object",
                "constraints": [],
            },

            # vertex groups
            "create_vertex_group": lambda args: {
                "object": args["object"], "group": args["name"], "index": 0, "count": 1,
            },
            "remove_vertex_group": lambda args: {
                "object": args["object"], "removed": args["name"],
            },
            "list_vertex_groups": lambda args: {
                "object": args["object"], "groups": [],
            },
            "set_vertex_weights": lambda args: {
                "object": args["object"], "group": args["group"],
                "set_count": len(args.get("indices") or []),
                "out_of_range": [],
                "type": args.get("type", "REPLACE"),
            },

            # shape keys
            "add_shape_key": lambda args: {
                "object": args["object"],
                "name": args.get("name") or "Key",
                "value": args.get("value", 0.0),
                "count": 2,  # Basis + the new one
            },
            "set_shape_key_value": lambda args: {
                "object": args["object"], "name": args["name"], "value": args["value"],
            },
            "remove_shape_key": lambda args: {
                "object": args["object"],
                "removed": [args["name"]] if args.get("name") else [],
                "remaining": 1,
            },
            "list_shape_keys": lambda args: {
                "object": args["object"], "keys": [],
            },
        }

    def add_handler(self, op: str, fn):
        self._handlers[op] = fn

    async def _handle_one(self, websocket):
        async for raw in websocket:
            msg = json.loads(raw)
            op = msg.get("op", "")
            args = msg.get("args", {}) or {}
            # v2.2: when the client sets dry_run in the envelope, echo it
            # back so tests can verify the plumbing reaches the WS.
            dry_run = bool(msg.get("dry_run", False))

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
                                           "dry_run": dry_run,
                                           "count": len(items),
                                           "ok_count": len(results),
                                           "error_count": len(errors),
                                           "results": results, "errors": errors}}
            else:
                handler = self._handlers.get(op)
                if handler:
                    result = handler(args)
                    if dry_run and isinstance(result, dict):
                        result = {**result, "dry_run": True}
                    response = {"id": msg.get("id"), "ok": True, "result": result}
                else:
                    response = {"id": msg.get("id"), "ok": False,
                                "error": {"code": "NOT_FOUND",
                                          "message": f"Unknown op: {op}"}}
            await websocket.send(json.dumps(response))

    async def start(self):
        self._clients: set = set()  # v2.3
        self._server = await websockets.serve(self._wrap, self.host, self.port)
        # Capture the OS-assigned port back onto self.port so callers can
        # build the URL (``ws://host:port``) without a separate query.
        if self.port == 0:
            sock = next(iter(self._server.sockets))
            self.port = sock.getsockname()[1]

    async def _wrap(self, websocket):
        self._clients.add(websocket)
        try:
            await self._handle_one(websocket)
        finally:
            self._clients.discard(websocket)

    async def broadcast(self, payload: dict):
        """v2.3: push a notification frame to every connected client."""
        data = json.dumps(payload)
        for ws in list(self._clients):
            try:
                await ws.send(data)
            except Exception:
                pass

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
