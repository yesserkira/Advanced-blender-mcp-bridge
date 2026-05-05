"""Progress reporter for streaming progress frames over WebSocket.

Capabilities run on Blender's main thread but the WebSocket lives on the
asyncio thread. This utility bridges the two safely.
"""

import asyncio
import json
import logging

logger = logging.getLogger("blendermcp.progress")


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

        try:
            self._loop.call_soon_threadsafe(
                asyncio.ensure_future,
                self._safe_send(frame),
            )
        except RuntimeError:
            # Loop is closed or shutting down
            logger.debug("Progress send skipped — loop closed")

    async def _safe_send(self, frame: str) -> None:
        """Send the frame, swallowing errors on disconnect."""
        try:
            await self._ws.send(frame)
        except Exception:
            logger.debug("Progress send failed — client likely disconnected")
