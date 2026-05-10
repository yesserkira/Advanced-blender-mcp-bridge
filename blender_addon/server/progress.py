"""Progress reporter for streaming progress frames over WebSocket.

Capabilities run on Blender's main thread but the WebSocket lives on the
asyncio thread. This utility bridges the two safely.

Hardenings (Windows / CPython 3.11 IOCP crash mitigation):
  * Throttle: drop frames issued more frequently than ``_MIN_INTERVAL_S``
    so a chatty caller can't queue hundreds of overlapped sends.
  * Coalesce: at most ONE pending send per reporter — the latest frame
    overwrites any not-yet-flushed one (we only care about the freshest
    progress percentage).
  * Serialise: the actual ``ws.send`` runs under the connection's
    per-socket asyncio.Lock from ws_server, so only one in-flight WSASend
    exists per socket at any time.
"""

import asyncio
import json
import logging
import time

logger = logging.getLogger("blendermcp.progress")

# Minimum spacing between successive progress sends. 50 ms => max 20 fps,
# which is plenty for a UI progress bar and keeps the proactor calm.
_MIN_INTERVAL_S = 0.05


class ProgressReporter:
    """Send progress frames from the main thread to a WebSocket client.

    Args:
        websocket: The websockets connection object.
        loop: The asyncio event loop running the WS server.
        command_id: The command ID this progress relates to.
    """

    def __init__(self, websocket, loop: asyncio.AbstractEventLoop, command_id: str):
        self._ws = websocket
        self._loop = loop
        self._command_id = command_id
        self._last_sent_at = 0.0
        self._pending_frame: str | None = None
        self._flush_scheduled = False

    def send(self, percent: int, message: str) -> None:
        """Schedule a progress frame to be sent on the asyncio thread.

        Safe to call from the main thread (non-async).
        Silently ignores errors if the websocket has disconnected.
        """
        frame = json.dumps({
            "id": self._command_id,
            "type": "progress",
            "progress": {
                "percent": percent,
                "message": message,
            },
        })

        # Always update the latest pending frame (coalesce).
        self._pending_frame = frame

        if self._flush_scheduled:
            # A flush is already queued; it will pick up the freshest frame.
            return

        now = time.monotonic()
        delay = max(0.0, self._last_sent_at + _MIN_INTERVAL_S - now)
        self._flush_scheduled = True

        try:
            if delay <= 0.0:
                self._loop.call_soon_threadsafe(self._flush)
            else:
                self._loop.call_soon_threadsafe(
                    self._loop.call_later, delay, self._flush,
                )
        except RuntimeError:
            # Loop is closed or shutting down.
            self._flush_scheduled = False
            logger.debug("Progress send skipped — loop closed")

    def _flush(self) -> None:
        """Asyncio-thread callback: drain the pending frame, if any."""
        frame = self._pending_frame
        self._pending_frame = None
        self._flush_scheduled = False
        if frame is None:
            return
        self._last_sent_at = time.monotonic()
        asyncio.ensure_future(self._safe_send(frame))

    async def _safe_send(self, frame: str) -> None:
        """Send the frame under the connection's send-lock."""
        # Imported lazily to avoid a circular import at module load.
        from .ws_server import _safe_ws_send
        try:
            await _safe_ws_send(self._ws, frame)
        except Exception:
            logger.debug("Progress send failed — client likely disconnected")

