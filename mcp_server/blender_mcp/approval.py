"""Approval client for the Blender MCP server.

The VS Code extension runs an HTTP approval server on loopback and writes a
discovery file containing its URL and a CSRF token. This module reads that
discovery file and POSTs approval requests, blocking until the user clicks
Approve / Reject (or the request times out).

Discovery file location:
  - Windows: %LOCALAPPDATA%\\BlenderMCP\\approval.json
  - macOS:   ~/Library/Application Support/BlenderMCP/approval.json
  - Linux:   $XDG_RUNTIME_DIR/blender-mcp/approval.json
            (fallback ~/.local/state/blender-mcp/approval.json)

If the discovery file is missing, the extension is not running, and any
"confirm-required" tool call must return CONFIRM_REQUIRED so the model can
explain to the user that approval is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApprovalEndpoint:
    url: str
    csrf: str
    pid: int


@dataclass(frozen=True)
class ApprovalOutcome:
    """Result of an approval round-trip.

    available: False  -> no extension found or HTTP failed; caller should
                        return CONFIRM_REQUIRED to the model.
    available: True, approved: True/False -> user decision (or session cache).
    """

    available: bool
    approved: bool = False
    remember_session: bool = False
    error: str | None = None


def _discovery_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "BlenderMCP"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "BlenderMCP"
    xdg = os.environ.get("XDG_RUNTIME_DIR") or str(Path.home() / ".local" / "state")
    return Path(xdg) / "blender-mcp"


def _discovery_file() -> Path:
    return _discovery_dir() / "approval.json"


def _pid_alive(pid: int) -> bool:
    try:
        if sys.platform == "win32":
            import ctypes  # local import: only on win32

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) == 0:
                    return False
                return code.value == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False
    except Exception:  # pragma: no cover - defensive
        return False


def discover_endpoint() -> ApprovalEndpoint | None:
    """Read the discovery file. Returns None if missing/stale/invalid."""
    # Env override (used by tests)
    url_override = os.environ.get("BLENDER_MCP_APPROVAL_URL")
    csrf_override = os.environ.get("BLENDER_MCP_APPROVAL_CSRF")
    if url_override and csrf_override:
        return ApprovalEndpoint(url=url_override, csrf=csrf_override, pid=0)

    f = _discovery_file()
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("approval discovery file unreadable: %s", exc)
        return None
    url = data.get("url")
    csrf = data.get("csrf")
    pid = data.get("pid")
    if not isinstance(url, str) or not isinstance(csrf, str):
        return None
    if isinstance(pid, int) and pid > 0 and not _pid_alive(pid):
        log.info("approval endpoint pid %s no longer alive; ignoring stale discovery", pid)
        return None
    return ApprovalEndpoint(url=url, csrf=csrf, pid=pid if isinstance(pid, int) else 0)


async def request_approval(
    tool: str,
    args: dict[str, Any] | None = None,
    code: str | None = None,
    timeout: float = 120.0,
) -> ApprovalOutcome:
    """Block until the user approves or rejects the tool call.

    Returns ApprovalOutcome with available=False if no endpoint is reachable.
    """
    endpoint = discover_endpoint()
    if endpoint is None:
        return ApprovalOutcome(available=False, error="no_endpoint")

    payload: dict[str, Any] = {
        "request_id": uuid.uuid4().hex,
        "tool": tool,
        "args": args or {},
    }
    if code is not None:
        payload["code"] = code

    try:
        import httpx  # type: ignore
    except ImportError:  # pragma: no cover
        return ApprovalOutcome(available=False, error="httpx_missing")

    url = endpoint.url.rstrip("/") + "/approve"
    headers = {"Content-Type": "application/json", "X-CSRF": endpoint.csrf}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except (httpx.HTTPError, asyncio.TimeoutError) as exc:
        log.warning("approval request failed: %s", exc)
        return ApprovalOutcome(available=False, error=f"http_error:{exc.__class__.__name__}")

    if resp.status_code != 200:
        log.warning("approval endpoint returned %s: %s", resp.status_code, resp.text[:200])
        return ApprovalOutcome(available=False, error=f"http_{resp.status_code}")

    try:
        body = resp.json()
    except ValueError:
        return ApprovalOutcome(available=False, error="invalid_json")

    return ApprovalOutcome(
        available=True,
        approved=bool(body.get("approved", False)),
        remember_session=bool(body.get("remember_session", False)),
    )
