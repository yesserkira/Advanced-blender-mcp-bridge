"""Main-thread command pump.

Drains a thread-safe queue via bpy.app.timers so all bpy calls
execute on Blender's main thread.  Yields after 8 ms wall-time
to avoid UI freezes.
"""

import queue
import time
import traceback

import bpy

from ..safety import audit_log

# Bounded queue: protects Blender from a flood of commands faster than the
# 8 ms-per-tick pump can drain. Multi-MB payloads (import_asset, set_property
# image data) make an unbounded queue an OOM risk. Submitters that hit a full
# queue should surface a clear error to the client (see ws_server._handler).
_INBOX_MAXSIZE = 256
_inbox: "queue.Queue[tuple[dict, callable, object, bool]]" = queue.Queue(
    maxsize=_INBOX_MAXSIZE,
)


class QueueFullError(RuntimeError):
    """Raised by submit() when the main-thread inbox is at capacity."""


_running = False


def submit(cmd: dict, resolve, progress_callback=None, dry_run: bool = False):
    """Enqueue a command to be executed on the main thread.

    Args:
        cmd: Command dict with at least 'id' and 'op' keys.
        resolve: Callable(response_dict) to deliver the result.
        progress_callback: Optional callable(percent, message) for progress.
        dry_run: If True, mutating ops short-circuit and return their planned
                 effect without actually applying it (v2.2).

    Raises:
        QueueFullError: when the inbox already holds ``_INBOX_MAXSIZE`` items.
            The WS handler should reject the frame with a BACKPRESSURE error.
    """
    try:
        _inbox.put_nowait((cmd, resolve, progress_callback, bool(dry_run)))
    except queue.Full as e:
        raise QueueFullError(
            f"Main-thread queue full ({_INBOX_MAXSIZE} pending commands)",
        ) from e


def _pump():
    """Timer callback: drain queue, yield after 8 ms."""
    if not _running:
        return None  # unregister

    deadline = time.perf_counter() + 0.008  # 8 ms
    try:
        while time.perf_counter() < deadline:
            try:
                cmd, resolve, progress_cb, dry_run = _inbox.get_nowait()
            except queue.Empty:
                break

            from .dispatcher import dispatch

            op = cmd.get("op") or "?"
            args = cmd.get("args") or {}
            t0 = time.perf_counter()
            try:
                result = dispatch(
                    cmd, progress_callback=progress_cb, dry_run=dry_run,
                )
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                resolve({
                    "id": cmd.get("id"),
                    "ok": True,
                    "result": result,
                })
                # Audit successful command (best-effort; never raises).
                try:
                    audit_log.log_command(
                        op, args if isinstance(args, dict) else {},
                        ok=True, elapsed_ms=elapsed_ms,
                        undo_id=str(cmd.get("id") or ""),
                    )
                except Exception:
                    pass
            except Exception as e:
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                resolve({
                    "id": cmd.get("id"),
                    "ok": False,
                    "error": {
                        "code": "BLENDER_ERROR",
                        "message": str(e),
                        "traceback": traceback.format_exc(),
                    },
                })
                try:
                    audit_log.log_command(
                        op, args if isinstance(args, dict) else {},
                        ok=False, elapsed_ms=elapsed_ms,
                        undo_id=str(cmd.get("id") or ""),
                    )
                except Exception:
                    pass
    except Exception:
        traceback.print_exc()

    return 0.01  # re-arm in 10 ms


def start():
    global _running
    if _running:
        return
    _running = True
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, persistent=True)


def stop():
    global _running
    _running = False
    # Drain remaining items with error
    while True:
        try:
            cmd, resolve, _pc, _dr = _inbox.get_nowait()
            resolve({
                "id": cmd.get("id"),
                "ok": False,
                "error": {
                    "code": "SERVER_STOPPED",
                    "message": "Server is shutting down",
                },
            })
        except queue.Empty:
            break
