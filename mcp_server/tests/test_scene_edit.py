"""Test scene editing tools through BlenderWS client."""

import pytest

from blender_mcp.blender_client import BlenderWS, BlenderError


@pytest.mark.asyncio
async def test_object_transform(fake_blender):
    """object.transform should return updated transforms."""
    fake_blender._handlers["object.transform"] = lambda args: {
        "name": args["name"],
        "location": args.get("location", [0, 0, 0]),
        "rotation_euler": args.get("rotation_euler", [0, 0, 0]),
        "scale": args.get("scale", [1, 1, 1]),
    }
    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("object.transform", {
            "name": "Cube",
            "location": [1.0, 2.0, 3.0],
            "scale": [2.0, 2.0, 2.0],
        })
        assert result["name"] == "Cube"
        assert result["location"] == [1.0, 2.0, 3.0]
        assert result["scale"] == [2.0, 2.0, 2.0]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_object_transform_not_found(fake_blender):
    """object.transform on missing object should raise BlenderError."""
    fake_blender._handlers["object.transform"] = lambda args: (_ for _ in ()).throw(
        ValueError(f"Object not found: {args['name']}")
    )

    # Override handler to return error like real dispatcher would
    original_handler = fake_blender._handler

    async def error_handler(websocket):
        import json
        async for raw in websocket:
            msg = json.loads(raw)
            op = msg.get("op", "")
            if op == "object.transform":
                response = {
                    "id": msg.get("id"),
                    "ok": False,
                    "error": {
                        "code": "VALUE_ERROR",
                        "message": f"Object not found: {msg['args']['name']}",
                    },
                }
                await websocket.send(json.dumps(response))
            else:
                # fall back to normal handling
                handler = fake_blender._handlers.get(op)
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

    # Restart with the error handler
    await fake_blender.stop()
    import websockets
    fake_blender._server = await websockets.serve(
        error_handler, fake_blender.host, fake_blender.port
    )

    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        with pytest.raises(BlenderError) as exc_info:
            await client.call("object.transform", {"name": "Missing"})
        assert exc_info.value.code == "VALUE_ERROR"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_object_delete(fake_blender):
    """object.delete should return deleted name and remaining count."""
    fake_blender._handlers["object.delete"] = lambda args: {
        "deleted": args["name"],
        "remaining_count": 2,
    }
    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("object.delete", {
            "name": "Cube",
            "confirm": False,
        })
        assert result["deleted"] == "Cube"
        assert result["remaining_count"] == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_selection_set(fake_blender):
    """selection.set should return selected names and active."""
    fake_blender._handlers["selection.set"] = lambda args: {
        "selected": args.get("names", []),
        "active": args.get("active"),
    }
    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("selection.set", {
            "names": ["Cube", "Light"],
            "active": "Cube",
        })
        assert result["selected"] == ["Cube", "Light"]
        assert result["active"] == "Cube"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_selection_get(fake_blender):
    """selection.get should return current selection."""
    fake_blender._handlers["selection.get"] = lambda args: {
        "selected": ["Camera"],
        "active": "Camera",
    }
    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("selection.get", {})
        assert result["selected"] == ["Camera"]
        assert result["active"] == "Camera"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_selection_get_empty(fake_blender):
    """selection.get with nothing selected should return empty list."""
    fake_blender._handlers["selection.get"] = lambda args: {
        "selected": [],
        "active": None,
    }
    client = BlenderWS(
        url=f"ws://{fake_blender.host}:{fake_blender.port}",
        token="any-token",
    )
    try:
        result = await client.call("selection.get", {})
        assert result["selected"] == []
        assert result["active"] is None
    finally:
        await client.close()
