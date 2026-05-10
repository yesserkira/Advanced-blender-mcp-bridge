"""Tests for stale-token recovery (Blender add-on regenerates token on restart)."""

from __future__ import annotations

import json
import os

import pytest

from blender_mcp import server as srv
from blender_mcp.blender_client import BlenderError


def test_resolve_credentials_prefers_env_when_no_file(monkeypatch, tmp_path):
    """Env wins when no connection.json is present (Blender not running)."""
    monkeypatch.setenv("BLENDER_MCP_TOKEN", "env-token")
    monkeypatch.setenv("BLENDER_MCP_URL", "ws://1.2.3.4:9999")
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)
    url, token = srv._resolve_credentials()
    assert url == "ws://1.2.3.4:9999"
    assert token == "env-token"


def test_resolve_credentials_file_wins_over_stale_env_token(monkeypatch, tmp_path):
    """Live connection.json beats a stale ``BLENDER_MCP_TOKEN`` env value
    that was injected at MCP-server spawn (e.g. by the VS Code extension)
    and is now out of date because Blender restarted.

    This is the exact scenario the user hit: env had only TOKEN (no URL),
    so the file's url+token are the live truth.
    """
    cf_dir = tmp_path / ".blender_mcp"
    cf_dir.mkdir()
    cf = cf_dir / "connection.json"
    cf.write_text(json.dumps({
        "host": "127.0.0.1", "port": 9876, "token": "fresh-token",
    }), encoding="utf-8")

    monkeypatch.setenv("BLENDER_MCP_TOKEN", "stale-env-token")
    monkeypatch.delenv("BLENDER_MCP_URL", raising=False)
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)

    url, token = srv._resolve_credentials()
    assert token == "fresh-token"
    assert url == "ws://127.0.0.1:9876"


def test_resolve_credentials_explicit_env_url_overrides_file(monkeypatch, tmp_path):
    """When env explicitly targets a *different* endpoint, env wins entirely.
    This preserves test isolation (fake servers on alt ports) and honors
    explicit user overrides."""
    cf_dir = tmp_path / ".blender_mcp"
    cf_dir.mkdir()
    cf = cf_dir / "connection.json"
    cf.write_text(json.dumps({
        "host": "127.0.0.1", "port": 9876, "token": "file-token",
    }), encoding="utf-8")

    monkeypatch.setenv("BLENDER_MCP_TOKEN", "explicit-env-token")
    monkeypatch.setenv("BLENDER_MCP_URL", "ws://1.2.3.4:9999")
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)

    url, token = srv._resolve_credentials()
    assert url == "ws://1.2.3.4:9999"
    assert token == "explicit-env-token"


def test_resolve_credentials_reads_connection_file(monkeypatch, tmp_path):
    cf_dir = tmp_path / ".blender_mcp"
    cf_dir.mkdir()
    cf = cf_dir / "connection.json"
    cf.write_text(json.dumps({
        "host": "127.0.0.1", "port": 9876, "token": "fresh-token-from-file",
    }), encoding="utf-8")

    monkeypatch.delenv("BLENDER_MCP_TOKEN", raising=False)
    monkeypatch.delenv("BLENDER_MCP_URL", raising=False)
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)

    # Disable keyring side-effects.
    import sys
    monkeypatch.setitem(sys.modules, "keyring", type("K", (), {
        "get_password": staticmethod(lambda *a, **k: None),
    })())

    url, token = srv._resolve_credentials()
    assert token == "fresh-token-from-file"
    assert url == "ws://127.0.0.1:9876"


def test_resolve_credentials_returns_default_url_when_nothing(monkeypatch):
    monkeypatch.delenv("BLENDER_MCP_TOKEN", raising=False)
    monkeypatch.delenv("BLENDER_MCP_URL", raising=False)
    # Point HOME at an empty dir so connection.json is missing.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr(os.path, "expanduser", lambda p: d if p == "~" else p)
        url, token = srv._resolve_credentials()
        assert url == "ws://127.0.0.1:9876"
        # token may come from keyring if installed; just assert it's a str
        assert isinstance(token, str)


@pytest.mark.asyncio
async def test_reset_client_for_reauth_drops_cached_client():
    class _Fake:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    fake = _Fake()
    srv._bl = fake  # type: ignore[assignment]
    try:
        await srv._reset_client_for_reauth()
        assert srv._bl is None
        assert fake.closed is True
    finally:
        srv._bl = None


@pytest.mark.asyncio
async def test_call_retries_once_on_auth_error(monkeypatch):
    """Regression: a stale cached token (Blender restarted) must trigger a
    one-shot retry with refreshed credentials, not surface AUTH to the user.
    """
    calls = {"n": 0}

    class _StubClient:
        async def call(self, op, args, timeout=30.0, dry_run=False):
            calls["n"] += 1
            if calls["n"] == 1:
                raise BlenderError("AUTH", "Invalid auth token")
            return {"ok": True, "n": calls["n"]}

        async def close(self):
            pass

    # First _get_client returns a stale stub; after reset, returns a fresh one.
    instances = [_StubClient(), _StubClient()]

    def _stub_get_client():
        if srv._bl is None:
            srv._bl = instances.pop(0)
        return srv._bl

    monkeypatch.setattr(srv, "_get_client", _stub_get_client)
    srv._bl = None

    try:
        result = await srv._call("ping", {})
        assert result == {"ok": True, "n": 2}
        # Two .call() invocations across two distinct client instances.
        assert calls["n"] == 2
    finally:
        srv._bl = None


@pytest.mark.asyncio
async def test_call_surfaces_auth_if_retry_also_fails(monkeypatch):
    """If the refreshed credentials are also bad, surface AUTH to the user
    instead of looping forever."""
    calls = {"n": 0}

    class _StubClient:
        async def call(self, op, args, timeout=30.0, dry_run=False):
            calls["n"] += 1
            raise BlenderError("AUTH", "still bad")

        async def close(self):
            pass

    def _stub_get_client():
        if srv._bl is None:
            srv._bl = _StubClient()
        return srv._bl

    monkeypatch.setattr(srv, "_get_client", _stub_get_client)
    srv._bl = None

    try:
        result = await srv._call("ping", {})
        assert isinstance(result, dict)
        assert result.get("error") == "AUTH"
        assert calls["n"] == 2  # initial + one retry, no more
    finally:
        srv._bl = None
