"""WebSocket server running in a daemon thread.

Accepts JSON commands, validates auth, pushes to main_thread queue,
and returns results over the same WebSocket connection.
"""

import asyncio
import json
import logging
import threading
import time

from . import main_thread

logger = logging.getLogger("blendermcp.ws")

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_server = None
_connection_count = 0
_MAX_CONNECTIONS = 4


def _get_token():
    from ..preferences import get_token
    return get_token()


async def _handler(websocket):
    global _connection_count

    # Reject if Origin header present (DNS rebinding mitigation)
    origin = websocket.request.headers.get("Origin") if hasattr(websocket, "request") else None
    if origin:
        logger.warning("Rejected connection with Origin header: %s", origin)
        await websocket.close(4003, "Origin header not allowed")
        return

    if _connection_count >= _MAX_CONNECTIONS:
        logger.warning("Max connections reached, rejecting")
        await websocket.close(4004, "Too many connections")
        return

    _connection_count += 1
    logger.info("Client connected (%d active)", _connection_count)

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({
                    "id": None,
                    "ok": False,
                    "error": {"code": "BAD_FRAME", "message": "Invalid JSON"},
                }))
                continue

            # Validate required fields
            msg_id = msg.get("id")
            op = msg.get("op")
            auth = msg.get("auth")

            if not msg_id or not op or not auth:
                await websocket.send(json.dumps({
                    "id": msg_id,
                    "ok": False,
                    "error": {"code": "BAD_FRAME", "message": "Missing id, op, or auth"},
                }))
                continue

            # Validate auth token
            if auth != _get_token():
                await websocket.send(json.dumps({
                    "id": msg_id,
                    "ok": False,
                    "error": {"code": "AUTH", "message": "Invalid auth token"},
                }))
                continue

            # Submit to main thread and await result
            start = time.perf_counter()
            future = _loop.create_future()

            def _resolve(result, f=future):
                _loop.call_soon_threadsafe(f.set_result, result)

            main_thread.submit(msg, _resolve)

            try:
                result = await asyncio.wait_for(future, timeout=30.0)
            except asyncio.TimeoutError:
                result = {
                    "id": msg_id,
                    "ok": False,
                    "error": {"code": "MAIN_THREAD_TIMEOUT", "message": "Command timed out after 30s"},
                }

            elapsed = int((time.perf_counter() - start) * 1000)
            result["elapsed_ms"] = elapsed

            await websocket.send(json.dumps(result))

    except Exception as e:
        logger.error("Connection error: %s", e)
    finally:
        _connection_count -= 1
        logger.info("Client disconnected (%d active)", _connection_count)


async def _serve(host: str, port: int):
    global _server
    import websockets
    _server = await websockets.serve(_handler, host, port)
    logger.info("WebSocket server listening on ws://%s:%d", host, port)
    await _server.wait_closed()


def start(host: str = "127.0.0.1", port: int = 9876):
    global _loop, _thread

    if _thread is not None and _thread.is_alive():
        logger.warning("Server already running")
        return

    def _run():
        global _loop
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _loop.run_until_complete(_serve(host, port))

    _thread = threading.Thread(target=_run, daemon=True, name="blendermcp-ws")
    _thread.start()


def stop():
    global _server, _loop, _thread

    if _server and _loop:
        _loop.call_soon_threadsafe(_server.close)

    if _loop:
        _loop.call_soon_threadsafe(_loop.stop)

    _server = None
    _loop = None
    _thread = None


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()
