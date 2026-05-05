"""Tests for the approval client and end-to-end approval flow.

We spin up a tiny aiohttp-style HTTP listener (using stdlib http.server in a
thread) on loopback that mimics the VS Code extension's /approve endpoint, set
the BLENDER_MCP_APPROVAL_URL/CSRF env vars, and verify request_approval()
behaves correctly across approve / reject / no-endpoint / bad-csrf scenarios.
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from blender_mcp.approval import (
    ApprovalOutcome,
    discover_endpoint,
    request_approval,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


class _FakeApprovalHandler(BaseHTTPRequestHandler):
    """Replays a queue of decisions in FIFO order."""

    decisions: list[dict[str, Any]] = []
    expected_csrf: str = ""
    received: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        if self.path != "/approve":
            self.send_response(404)
            self.end_headers()
            return
        csrf = self.headers.get("X-CSRF", "")
        if csrf != self.expected_csrf:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'{"error":"bad csrf"}')
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except ValueError:
            payload = {}
        self.received.append(payload)
        if not self.decisions:
            decision = {"approved": False, "remember_session": False}
        else:
            decision = self.decisions.pop(0)
        body_out = json.dumps(decision).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_out)))
        self.end_headers()
        self.wfile.write(body_out)


@pytest.fixture
def fake_extension(monkeypatch: pytest.MonkeyPatch):
    """Spin up a fake extension HTTP server, return (url, csrf, handler)."""
    _FakeApprovalHandler.decisions = []
    _FakeApprovalHandler.received = []
    _FakeApprovalHandler.expected_csrf = "test-csrf-token"

    server = HTTPServer(("127.0.0.1", 0), _FakeApprovalHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("BLENDER_MCP_APPROVAL_URL", url)
    monkeypatch.setenv("BLENDER_MCP_APPROVAL_CSRF", "test-csrf-token")

    try:
        yield url, "test-csrf-token", _FakeApprovalHandler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_discover_endpoint_from_env(fake_extension):
    url, csrf, _ = fake_extension
    ep = discover_endpoint()
    assert ep is not None
    assert ep.url == url
    assert ep.csrf == csrf


def test_discover_endpoint_missing(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.delenv("BLENDER_MCP_APPROVAL_URL", raising=False)
    monkeypatch.delenv("BLENDER_MCP_APPROVAL_CSRF", raising=False)
    # Redirect discovery dir to empty tmp by overriding LOCALAPPDATA / HOME.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert discover_endpoint() is None


def test_request_approval_approved(fake_extension):
    _, _, handler = fake_extension
    handler.decisions.append({"approved": True, "remember_session": False})
    outcome = asyncio.run(
        request_approval("execute_python", {"x": 1}, code="print(1)", timeout=5.0)
    )
    assert outcome.available is True
    assert outcome.approved is True
    assert outcome.remember_session is False
    assert handler.received[0]["tool"] == "execute_python"
    assert handler.received[0]["code"] == "print(1)"
    assert handler.received[0]["args"] == {"x": 1}
    assert "request_id" in handler.received[0]


def test_request_approval_rejected(fake_extension):
    _, _, handler = fake_extension
    handler.decisions.append({"approved": False, "remember_session": False})
    outcome = asyncio.run(request_approval("delete_object", {"object": "Cube"}, timeout=5.0))
    assert outcome.available is True
    assert outcome.approved is False


def test_request_approval_remember_session(fake_extension):
    _, _, handler = fake_extension
    handler.decisions.append({"approved": True, "remember_session": True})
    outcome = asyncio.run(request_approval("execute_python", {}, code="pass", timeout=5.0))
    assert outcome.approved is True
    assert outcome.remember_session is True


def test_request_approval_no_endpoint(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.delenv("BLENDER_MCP_APPROVAL_URL", raising=False)
    monkeypatch.delenv("BLENDER_MCP_APPROVAL_CSRF", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    outcome = asyncio.run(request_approval("execute_python", {}, code="pass", timeout=2.0))
    assert outcome.available is False
    assert outcome.approved is False
    assert outcome.error == "no_endpoint"


def test_request_approval_bad_csrf(fake_extension, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BLENDER_MCP_APPROVAL_CSRF", "wrong-csrf")
    outcome = asyncio.run(request_approval("execute_python", {}, code="pass", timeout=5.0))
    assert outcome.available is False
    assert outcome.error is not None and outcome.error.startswith("http_403")


def test_request_approval_includes_request_id(fake_extension):
    _, _, handler = fake_extension
    handler.decisions.extend(
        [{"approved": True, "remember_session": False} for _ in range(2)]
    )

    async def _two() -> tuple[ApprovalOutcome, ApprovalOutcome]:
        a = await request_approval("execute_python", {}, code="a", timeout=5.0)
        b = await request_approval("execute_python", {}, code="b", timeout=5.0)
        return a, b

    a, b = asyncio.run(_two())
    assert a.approved and b.approved
    ids = {req["request_id"] for req in handler.received}
    assert len(ids) == 2  # each call gets a unique id
