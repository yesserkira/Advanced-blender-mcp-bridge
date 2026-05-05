"""Main-thread command pump.

Drains a thread-safe queue via bpy.app.timers so all bpy calls
execute on Blender's main thread.  Yields after 8 ms wall-time
to avoid UI freezes.
"""

import queue
import time
import traceback

import bpy

_inbox: "queue.Queue[tuple[dict, callable, object]]" = queue.Queue()

_running = False


def submit(cmd: dict, resolve, progress_callback=None):
    """Enqueue a command to be executed on the main thread.

    Args:
        cmd: Command dict with at least 'id' and 'op' keys.
        resolve: Callable(response_dict) to deliver the result.
        progress_callback: Optional callable(percent, message) for progress.
    """
    _inbox.put((cmd, resolve, progress_callback))


def _pump():
    """Timer callback: drain queue, yield after 8 ms."""
    if not _running:
        return None  # unregister

    deadline = time.perf_counter() + 0.008  # 8 ms
    try:
        while time.perf_counter() < deadline:
            try:
                cmd, resolve, progress_cb = _inbox.get_nowait()
            except queue.Empty:
                break

            from .dispatcher import dispatch

            try:
                result = dispatch(cmd, progress_callback=progress_cb)
                resolve({
                    "id": cmd.get("id"),
                    "ok": True,
                    "result": result,
                })
            except Exception as e:
                resolve({
                    "id": cmd.get("id"),
                    "ok": False,
                    "error": {
                        "code": "BLENDER_ERROR",
                        "message": str(e),
                        "traceback": traceback.format_exc(),
                    },
                })
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
            cmd, resolve, _pc = _inbox.get_nowait()
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
