"""Shared test fixtures."""

import asyncio
import json
import pytest
import websockets


class FakeBlenderServer:
    """Minimal fake Blender WS server for testing."""

    def __init__(self, host="127.0.0.1", port=19876):
        self.host = host
        self.port = port
        self._server = None
        self._handlers: dict[str, callable] = {
            "ping": lambda args: "pong",
            "scene.get": lambda args: {
                "scene": "Scene",
                "frame": {"current": 1, "start": 1, "end": 250, "fps": 24},
                "object_counts": {"MESH": 1, "LIGHT": 1, "CAMERA": 1},
                "active_camera": "Camera",
            },
            "object.transform": lambda args: {
                "name": args["name"],
                "location": args.get("location", [0, 0, 0]),
                "rotation_euler": args.get("rotation_euler", [0, 0, 0]),
                "scale": args.get("scale", [1, 1, 1]),
            },
            "object.delete": lambda args: {
                "deleted": args["name"],
                "remaining_count": 2,
            },
            "selection.set": lambda args: {
                "selected": args.get("names", []),
                "active": args.get("active"),
            },
            "selection.get": lambda args: {
                "selected": ["Cube"],
                "active": "Cube",
            },
            "material.create_pbr": lambda args: {
                "name": args.get("name", "Material"),
                "node_tree": "Principled BSDF",
                "inputs_set": ["Base Color", "Metallic", "Roughness"],
            },
            "material.assign": lambda args: {
                "object": args.get("object_name", ""),
                "material": args.get("material_name", ""),
                "slot": args.get("slot", 0),
            },
            "light.create": lambda args: {
                "name": args.get("name", args["type"].capitalize()),
                "type": args["type"],
                "location": args.get("location", [0, 0, 0]),
                "energy": args.get("energy", 1000.0),
            },
            "camera.create": lambda args: {
                "name": args.get("name", "Camera"),
                "lens": args.get("lens", 50.0),
                "location": args.get("location", [0, 0, 5]),
            },
            "camera.set_active": lambda args: {
                "active_camera": args["name"],
            },
            "modifier.add": lambda args: {
                "object": args["object_name"],
                "modifier_name": args.get("modifier_name") or args["modifier_type"],
                "modifier_type": args["modifier_type"],
                "index": 0,
            },
            "animation.keyframe": lambda args: {
                "object": args["object_name"],
                "data_path": args["data_path"],
                "frame": args["frame"],
                "value": args.get("value", [0, 0, 0]),
            },
            "mesh.edit": lambda args: {
                "object": args["object_name"],
                "operation": args["operation"],
                "vertices": 16,
                "polys": 10,
            },
            "transaction.begin": lambda args: {
                "transaction_id": args["transaction_id"],
                "status": "active",
            },
            "transaction.commit": lambda args: {
                "transaction_id": args["transaction_id"],
                "status": "committed",
                "op_count": 0,
            },
            "transaction.rollback": lambda args: {
                "transaction_id": args["transaction_id"],
                "status": "rolled_back",
            },
            "exec.python": lambda args: {
                "executed": True,
                "lines": len(args.get("code", "").splitlines()),
            },
            "asset.import": lambda args: {
                "imported_objects": ["ImportedMesh"],
                "format": ".glb",
                "path": args.get("path", ""),
            },
            "geonodes.build": lambda args: {
                "object": args.get("object_name", ""),
                "modifier": args.get("modifier_name", "AI_GeoNodes"),
                "node_count": len(args.get("nodes", [])) + 2,
                "link_count": len(args.get("links", [])),
            },
            "shader.set_graph": lambda args: {
                "material": args.get("material_name", ""),
                "node_count": len(args.get("nodes", [])) + 1,
                "link_count": len(args.get("links", [])),
                "nodes_created": [n["type"] for n in args.get("nodes", [])],
            },
        }

    async def _handler(self, websocket):
        async for raw in websocket:
            msg = json.loads(raw)
            op = msg.get("op", "")
            handler = self._handlers.get(op)
            if handler:
                result = handler(msg.get("args", {}))
                response = {"id": msg.get("id"), "ok": True, "result": result}
            else:
                response = {
                    "id": msg.get("id"),
                    "ok": False,
                    "error": {"code": "NOT_FOUND", "message": f"Unknown op: {op}"},
                }
            await websocket.send(json.dumps(response))

    async def start(self):
        self._server = await websockets.serve(self._handler, self.host, self.port)

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()


@pytest.fixture
async def fake_blender():
    """Start a fake Blender WS server for the duration of the test."""
    server = FakeBlenderServer()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
def blender_token():
    return "test-token-for-testing"
