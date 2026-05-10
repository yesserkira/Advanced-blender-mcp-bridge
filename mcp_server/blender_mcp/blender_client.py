"""WebSocket client that connects to the Blender add-on.

v2.3 — frame demux:
    A single background reader task owns ``websocket.recv()``. Every frame
    it reads is routed:
      * frames with ``id`` matching an in-flight call → resolve the future.
      * frames with ``type == "notification"`` → invoke the registered
        ``notification_handler`` (used by the MCP server to forward
        ``notifications/resources/updated`` to Copilot).
      * frames with ``type == "progress"`` → logged at DEBUG.
      * everything else → logged at WARNING.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

import websockets
from ulid import ULID

logger = logging.getLogger("blender_mcp.client")

NotificationHandler = Callable[[dict[str, Any]], Awaitable[None]]


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
        self._connect_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._backoff = 0.5
        self._max_backoff = 5.0

        # v2.3: frame demux state. Inflight futures resolve with the raw
        # response envelope ({id, ok, result|error}); `result` may be a
        # dict, list, or scalar depending on the op.
        self._inflight: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._notification_handler: NotificationHandler | None = None

    def set_notification_handler(self, fn: NotificationHandler | None) -> None:
        """Register a coroutine called for every notification frame."""
        self._notification_handler = fn

    async def _connect(self) -> None:
        if self._ws is not None and not self._ws.closed:
            return

        async with self._connect_lock:
            if self._ws is not None and not self._ws.closed:
                return

            # If a previous reader is still running (it hasn't yet reached
            # its `finally` after the old socket failed), give it a moment
            # to wind down so we don't end up with two readers — or, worse,
            # the new socket having no reader at all because we mistook
            # the still-running old reader for "current".
            old_reader = self._reader_task
            if old_reader is not None and not old_reader.done():
                try:
                    await asyncio.wait_for(asyncio.shield(old_reader), timeout=0.5)
                except (asyncio.TimeoutError, Exception):
                    old_reader.cancel()
                    try:
                        await old_reader
                    except (asyncio.CancelledError, Exception):
                        pass

            while True:
                try:
                    self._ws = await websockets.connect(
                        self.url,
                        max_size=64 * 1024 * 1024,
                        ping_interval=20,
                        ping_timeout=20,
                    )
                    self._backoff = 0.5
                    logger.info("Connected to Blender at %s", self.url)
                    break
                except Exception as e:
                    logger.warning(
                        "Connection to %s failed: %s (retry in %.1fs)",
                        self.url, e, self._backoff,
                    )
                    await asyncio.sleep(self._backoff)
                    self._backoff = min(self._backoff * 2, self._max_backoff)

            # Always start a fresh reader for the new socket.
            self._reader_task = asyncio.create_task(
                self._read_loop(), name="blender-ws-reader",
            )

    async def _read_loop(self) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Discarding non-JSON frame: %r", raw[:200])
                    continue

                # 1. notifications (no id)
                if msg.get("type") == "notification":
                    if self._notification_handler is not None:
                        try:
                            await self._notification_handler(msg)
                        except Exception:
                            logger.exception("notification handler raised")
                    else:
                        logger.debug("notification (no handler): %s",
                                     msg.get("event"))
                    continue

                # 2. progress
                if msg.get("type") == "progress":
                    logger.debug(
                        "progress %s%% %s",
                        (msg.get("progress") or {}).get("percent"),
                        (msg.get("progress") or {}).get("message"),
                    )
                    continue

                # 3. responses
                msg_id = msg.get("id")
                if msg_id and msg_id in self._inflight:
                    fut = self._inflight.pop(msg_id)
                    if not fut.done():
                        fut.set_result(msg)
                else:
                    logger.warning(
                        "Discarding stale frame id=%s (no in-flight match)",
                        msg_id,
                    )
        except (websockets.ConnectionClosed, OSError) as e:
            logger.info("WS read loop ended: %s", e)
        except Exception:
            logger.exception("WS read loop crashed")
        finally:
            for fut in list(self._inflight.values()):
                if not fut.done():
                    fut.set_exception(
                        BlenderError("CONNECTION_LOST",
                                     "WebSocket reader exited")
                    )
            self._inflight.clear()
            if self._ws is ws:
                self._ws = None

    async def call(
        self,
        op: str,
        args: dict[str, Any] | None = None,
        timeout: float = 30.0,
        dry_run: bool = False,
    ) -> Any:
        """Send a command to Blender and return the result.

        Returns whatever shape the op produces — usually `dict[str, Any]`,
        but `query` / `list` ops legitimately return lists, and `ping`
        returns a string. Callers should narrow as needed.
        """
        await self._connect()

        cmd_id = str(ULID())
        cmd: dict[str, Any] = {
            "id": cmd_id,
            "op": op,
            "args": args or {},
            "auth": self.token,
            "meta": {"client": "mcp-server/0.1", "timeout": timeout},
        }
        if dry_run:
            cmd["dry_run"] = True

        loop = asyncio.get_event_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._inflight[cmd_id] = fut

        ws = self._ws
        if ws is None:
            self._inflight.pop(cmd_id, None)
            raise BlenderError("CONNECTION_LOST", "No WebSocket after connect")

        try:
            async with self._send_lock:
                await ws.send(json.dumps(cmd))
        except (websockets.ConnectionClosed, OSError) as e:
            self._inflight.pop(cmd_id, None)
            self._ws = None
            raise BlenderError("CONNECTION_LOST", f"Send failed: {e}")

        try:
            response = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._inflight.pop(cmd_id, None)
            raise

        if not response.get("ok"):
            err = response.get("error", {})
            raise BlenderError(
                code=err.get("code", "UNKNOWN"),
                message=err.get("message", "Unknown error"),
                traceback=err.get("traceback"),
            )

        result = response.get("result")
        return result

    async def close(self) -> None:
        """Close the WebSocket connection and stop the reader."""
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
