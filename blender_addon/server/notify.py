"""Scene-change notifier (v2.3).

Registers a depsgraph_update_post handler. When the scene changes, schedule
a debounced check that:

  1. Computes a fast snapshot hash via capabilities.snapshot.scene_snapshot
     in summary mode.
  2. If the hash differs from the last broadcast, emits a notification frame
     to every connected WS client:

         {"type": "notification",
          "event": "scene.changed",
          "uri":   "blender://scene/current",
          "hash":  "<sha256[:16]>"}

The MCP server's BlenderWS reader forwards this to subscribed clients via
``notifications/resources/updated``.

Debounce is implemented with bpy.app.timers — Blender fires depsgraph
callbacks frequently (every redraw with active animation), so we coalesce
to at most one broadcast per ``DEBOUNCE_S`` seconds.
"""

from __future__ import annotations

import logging

import bpy
from bpy.app.handlers import persistent

from . import ws_server

logger = logging.getLogger("blendermcp.notify")

DEBOUNCE_S = 0.75
RESOURCE_URI = "blender://scene/current"

_last_hash: str | None = None
_pending: bool = False
_handler_installed: bool = False


def _compute_hash() -> str | None:
    try:
        # Lazy import — avoids circular import at register-time and keeps
        # this module importable in environments without the full add-on.
        from ..capabilities.snapshot import scene_snapshot
    except Exception:
        return None
    try:
        snap = scene_snapshot({"summary": True})
        return snap.get("hash") if isinstance(snap, dict) else None
    except Exception:
        logger.exception("snapshot for change-hash failed")
        return None


def _flush() -> None:
    """Timer callback: emit broadcast if hash changed."""
    global _last_hash, _pending
    _pending = False
    h = _compute_hash()
    if h is None or h == _last_hash:
        return
    _last_hash = h
    try:
        n = ws_server.broadcast({
            "type": "notification",
            "event": "scene.changed",
            "uri": RESOURCE_URI,
            "hash": h,
        })
        if n:
            logger.debug("broadcast scene.changed hash=%s to %d clients", h, n)
    except Exception:
        logger.exception("broadcast failed")


def _on_depsgraph_update(scene, depsgraph) -> None:  # noqa: ARG001
    """Depsgraph handler — schedule a debounced flush."""
    global _pending
    if _pending:
        return
    _pending = True
    try:
        bpy.app.timers.register(
            _flush_timer, first_interval=DEBOUNCE_S, persistent=False,
        )
    except Exception:
        # Timer not registerable (rare); flush inline next handler call.
        _pending = False


# `@persistent` is required so the handler survives File > Open / Revert.
# Without it, depsgraph events stop firing after the first .blend load.
_on_depsgraph_update = persistent(_on_depsgraph_update)


def _flush_timer():
    """Trampoline: bpy.app.timers expects a callable returning ``None``
    (to deregister) or a float (to repeat). We always return None."""
    try:
        _flush()
    except Exception:
        logger.exception("flush failed")
    return None


def register() -> None:
    """Install the depsgraph handler. Idempotent."""
    global _handler_installed
    if _handler_installed:
        return
    handlers = bpy.app.handlers.depsgraph_update_post
    # Defend against hot-reload: any prior copy of this function (under the
    # same __name__) lingering in the handler list would fire on top of the
    # new one. Remove by qualified name first.
    target_name = _on_depsgraph_update.__qualname__
    for h in list(handlers):
        if getattr(h, "__qualname__", None) == target_name:
            try:
                handlers.remove(h)
            except Exception:
                pass
    handlers.append(_on_depsgraph_update)
    _handler_installed = True
    logger.info("Scene-change notifier installed")


def unregister() -> None:
    """Remove the depsgraph handler. Idempotent."""
    global _handler_installed, _last_hash, _pending
    handlers = bpy.app.handlers.depsgraph_update_post
    target_name = _on_depsgraph_update.__qualname__
    for h in list(handlers):
        if h is _on_depsgraph_update or getattr(h, "__qualname__", None) == target_name:
            try:
                handlers.remove(h)
            except Exception:
                pass
    _handler_installed = False
    _last_hash = None
    _pending = False
