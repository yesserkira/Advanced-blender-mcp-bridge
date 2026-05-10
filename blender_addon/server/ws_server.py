"""WebSocket server running in a daemon thread.

Accepts JSON commands, validates auth, pushes to main_thread queue,
and returns results over the same WebSocket connection.
"""

import asyncio
import datetime
import json
import logging
import os
import sys
import threading
import time

from . import main_thread
from .progress import ProgressReporter

# Per-websocket asyncio.Lock — serialises overlapped sends so the Windows
# IOCP proactor never has more than one in-flight WSASend per socket. This
# avoids a CPython 3.11 use-after-free in `_OverlappedFuture` that crashed
# Blender (EXCEPTION_ACCESS_VIOLATION in python311.dll) when progress frames
# and broadcasts raced on the same connection.
_send_locks: "dict[object, asyncio.Lock]" = {}


def _get_send_lock(ws) -> asyncio.Lock:
    lock = _send_locks.get(ws)
    if lock is None:
        lock = asyncio.Lock()
        _send_locks[ws] = lock
    return lock


async def _safe_ws_send(ws, data: str) -> None:
    """Send ``data`` on ``ws`` under its per-connection lock."""
    async with _get_send_lock(ws):
        await ws.send(data)

logger = logging.getLogger("blendermcp.ws")

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_server = None
_stopped: asyncio.Event | None = None  # set after _server.wait_closed()
_connection_count = 0
_MAX_CONNECTIONS = 4

# v2.3: track active client websockets so notify.py can broadcast
# scene-change frames out-of-band (no request/response).
_clients: set = set()


def _get_token():
    from ..preferences import get_token
    return get_token()


def broadcast(payload: dict) -> int:
    """Send ``payload`` as JSON to every connected client.

    Safe to call from any thread (typically the Blender main thread, from a
    depsgraph handler). Returns the number of clients the frame was queued
    to. Drops silently if the WS server isn't running.
    """
    if _loop is None or not _clients:
        return 0
    try:
        data = json.dumps(payload)
    except (TypeError, ValueError) as e:
        logger.warning("broadcast: failed to serialise payload: %s", e)
        return 0

    targets = list(_clients)

    async def _fan_out():
        for ws in targets:
            try:
                await _safe_ws_send(ws, data)
            except Exception as e:  # noqa: BLE001 — best-effort
                logger.debug("broadcast: client send failed: %s", e)

    _loop.call_soon_threadsafe(asyncio.create_task, _fan_out())
    return len(targets)


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
    _clients.add(websocket)
    logger.info("Client connected (%d active)", _connection_count)

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _safe_ws_send(websocket, json.dumps({
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
                await _safe_ws_send(websocket, json.dumps({
                    "id": msg_id,
                    "ok": False,
                    "error": {"code": "BAD_FRAME", "message": "Missing id, op, or auth"},
                }))
                continue

            # Validate auth token
            if auth != _get_token():
                await _safe_ws_send(websocket, json.dumps({
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

            # Create progress callback for ops that support it
            progress_cb = None
            if op == "render.viewport_screenshot":
                reporter = ProgressReporter(websocket, _loop, msg_id)
                progress_cb = reporter.send

            # v2.2: dry-run flag in envelope short-circuits mutating ops to
            # return their planned effect (`would_*`) without executing.
            dry_run = bool(msg.get("dry_run", False))
            try:
                main_thread.submit(
                    msg, _resolve, progress_callback=progress_cb, dry_run=dry_run,
                )
            except main_thread.QueueFullError as e:
                # P0-2: backpressure — refuse rather than OOM Blender.
                await _safe_ws_send(websocket, json.dumps({
                    "id": msg_id,
                    "ok": False,
                    "error": {
                        "code": "BACKPRESSURE",
                        "message": str(e),
                        "hint": "Slow down command rate; queue is at capacity.",
                    },
                }))
                continue

            # Per-op timeout: client may pass meta.timeout (seconds). Default 30s.
            op_timeout = 30.0
            try:
                meta_to = (msg.get("meta") or {}).get("timeout")
                if meta_to is not None:
                    op_timeout = float(meta_to)
            except (TypeError, ValueError):
                pass
            # Long-running visual ops get a generous default ceiling so they
            # don't get cut off when the client did not pass meta.timeout.
            if op in ("render.region", "render.bake_preview",
                      "render.viewport_screenshot") and op_timeout < 300.0:
                op_timeout = max(op_timeout, 300.0)

            try:
                result = await asyncio.wait_for(future, timeout=op_timeout)
            except asyncio.TimeoutError:
                result = {
                    "id": msg_id,
                    "ok": False,
                    "error": {"code": "MAIN_THREAD_TIMEOUT",
                              "message": f"Command timed out after {op_timeout:.0f}s"},
                }

            elapsed = int((time.perf_counter() - start) * 1000)
            result["elapsed_ms"] = elapsed

            await _safe_ws_send(websocket, json.dumps(result))

    except Exception as e:
        logger.error("Connection error: %s", e)
    finally:
        _connection_count -= 1
        _clients.discard(websocket)
        _send_locks.pop(websocket, None)
        logger.info("Client disconnected (%d active)", _connection_count)


async def _serve(host: str, port: int):
    global _server, _stopped
    import websockets
    _stopped = asyncio.Event()
    _server = await websockets.serve(
        _handler, host, port,
        max_size=64 * 1024 * 1024,   # 64 MiB — allow large image payloads
        ping_interval=30,            # P2-5: detect dead clients
        ping_timeout=20,
    )
    logger.info("WebSocket server listening on ws://%s:%d", host, port)
    try:
        await _server.wait_closed()
    finally:
        _stopped.set()


def _connection_file() -> str:
    """Return path to ``~/.blender_mcp/connection.json``."""
    return os.path.join(os.path.expanduser("~"), ".blender_mcp", "connection.json")


def _write_connection_file(host: str, port: int, token: str) -> None:
    """Write host/port/token so VS Code can auto-discover the server.

    v2.6: also writes ``pid`` and ``started_at`` so clients can detect a
    stale file left behind after Blender crashes (the on-disk file is only
    removed on a graceful shutdown via ``_remove_connection_file()``).
    """
    path = _connection_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "host": host,
        "port": port,
        "token": token,
        "pid": os.getpid(),
        "started_at": datetime.datetime.now(datetime.timezone.utc)
            .isoformat(timespec="seconds"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    # Restrict permissions (owner-only) on platforms that support it
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    logger.info("Connection file written to %s", path)


def _remove_connection_file() -> None:
    """Remove the connection file on server stop."""
    path = _connection_file()
    try:
        os.remove(path)
        logger.info("Connection file removed")
    except FileNotFoundError:
        pass


def start(host: str = "127.0.0.1", port: int = 9876):
    global _loop, _thread

    if _thread is not None and _thread.is_alive():
        logger.warning("Server already running")
        return

    # Defence in depth: even if a caller bypassed the prefs gate, never
    # silently bind to a non-loopback host without the explicit opt-in
    # flags being set on the add-on preferences.
    if host not in ("127.0.0.1", "::1", "localhost"):
        prefs = None
        try:
            from .. import preferences  # local import — avoids cycle at module load
            prefs = preferences.get_prefs()
        except Exception:
            prefs = None
        allowed = bool(
            prefs
            and getattr(prefs, "allow_remote", False)
            and getattr(prefs, "confirmed_remote_warning", False)
        )
        if not allowed:
            logger.error(
                "Refusing to bind WebSocket server to %s: remote bind not "
                "approved in add-on preferences. Falling back to 127.0.0.1.",
                host,
            )
            host = "127.0.0.1"

    # Write connection file so VS Code can auto-discover the token
    _write_connection_file(host, port, _get_token())

    def _run():
        global _loop
        # On Windows, force the SelectorEventLoop instead of the default
        # ProactorEventLoop. The proactor (IOCP) implementation in CPython
        # 3.11 — which Blender 4.5 ships — has a known use-after-free in
        # `_OverlappedFuture` finalisation that AVs python311.dll under
        # concurrent send pressure. The selector loop avoids that path
        # entirely; tradeoff is irrelevant for our 1-client local socket.
        if sys.platform == "win32":
            _loop = asyncio.SelectorEventLoop()
        else:
            _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _loop.run_until_complete(_serve(host, port))

    _thread = threading.Thread(target=_run, daemon=True, name="blendermcp-ws")
    _thread.start()


def stop():
    """Stop the WS server and wait for the daemon thread to drain.

    P0-1: previous version was fire-and-forget — `_server.close()` was queued
    but `stop()` returned immediately, leaving the port in TIME_WAIT and the
    daemon thread still running. Now waits up to 5 s for `wait_closed()` and
    then joins the thread.
    """
    global _server, _loop, _thread, _stopped

    loop = _loop
    server = _server
    thread = _thread
    stopped = _stopped

    if loop and server:
        # Schedule close on the loop thread.
        loop.call_soon_threadsafe(server.close)
        # Wait (cross-thread) for wait_closed() to complete via _stopped event.
        if stopped is not None:
            async def _await_stopped():
                await stopped.wait()

            try:
                fut = asyncio.run_coroutine_threadsafe(_await_stopped(), loop)
                fut.result(timeout=5.0)
            except Exception as e:  # noqa: BLE001
                logger.warning("stop(): timed out waiting for server close: %s", e)

    # Stop the loop so the thread can exit run_until_complete.
    if loop:
        loop.call_soon_threadsafe(loop.stop)

    if thread is not None:
        thread.join(timeout=5.0)
        if thread.is_alive():
            logger.warning("stop(): WS thread did not exit within 5 s")

    _server = None
    _loop = None
    _thread = None
    _stopped = None
    _remove_connection_file()


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()
