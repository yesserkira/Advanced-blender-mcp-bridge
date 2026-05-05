"""WebSocket client that connects to the Blender add-on."""

import asyncio
import json
import logging

import websockets
from ulid import ULID

logger = logging.getLogger("blender_mcp.client")


class BlenderError(Exception):
    """Structured error from Blender add-on."""

    def __init__(self, code: str, message: str, traceback: str | None = None):
        super().__init__(message)
        self.code = code
        self.traceback = traceback


class BlenderWS:
    """WebSocket client to the Blender MCP Bridge add-on."""

    def __init__(self, url: str = "ws://127.0.0.1:9876", token: str = ""):
        self.url = url
        self.token = token
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._lock = asyncio.Lock()
        self._backoff = 0.5
        self._max_backoff = 5.0

    async def _connect(self):
        """Connect or reconnect with exponential backoff."""
        if self._ws is not None:
            try:
                await self._ws.ping()
                return
            except Exception:
                self._ws = None

        while True:
            try:
                self._ws = await websockets.connect(self.url)
                self._backoff = 0.5
                logger.info("Connected to Blender at %s", self.url)
                return
            except Exception as e:
                logger.warning(
                    "Connection to %s failed: %s (retry in %.1fs)",
                    self.url, e, self._backoff,
                )
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, self._max_backoff)

    async def call(self, op: str, args: dict | None = None, timeout: float = 30.0) -> dict:
        """Send a command to Blender and return the result.

        Args:
            op: Operation name (e.g. 'scene.get', 'mesh.create_primitive').
            args: Operation arguments.
            timeout: Timeout in seconds.

        Returns:
            Result dict from the capability.

        Raises:
            BlenderError: If Blender returns an error response.
            asyncio.TimeoutError: If the command times out.
        """
        async with self._lock:
            await self._connect()

            cmd_id = str(ULID())
            cmd = {
                "id": cmd_id,
                "op": op,
                "args": args or {},
                "auth": self.token,
                "meta": {"client": "mcp-server/0.1"},
            }

            try:
                await self._ws.send(json.dumps(cmd))
                raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
            except (websockets.ConnectionClosed, OSError) as e:
                self._ws = None
                raise BlenderError("CONNECTION_LOST", f"Lost connection: {e}")

            response = json.loads(raw)

            if not response.get("ok"):
                err = response.get("error", {})
                raise BlenderError(
                    code=err.get("code", "UNKNOWN"),
                    message=err.get("message", "Unknown error"),
                    traceback=err.get("traceback"),
                )

            return response.get("result")

    async def close(self):
        """Close the WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None
