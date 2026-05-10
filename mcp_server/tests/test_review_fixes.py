"""Post-review regression tests covering issues caught in the v2.1 deep review."""

from __future__ import annotations

import json
import os
import sys

import pytest

import blender_mcp.server as server
from blender_mcp.approval import discover_endpoint
from blender_mcp.policy import READ_ONLY_TOOLS
from blender_addon.safety import checkpoints as ck


# ---------------------------------------------------------------------------
# Issue #1: transaction must enforce poly cap on nested create_objects steps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transaction_blocks_huge_nested_create_objects(monkeypatch):
    """A transaction wrapping a giant create_objects must not bypass max_polys."""
    # Force a tiny cap on a fresh policy so the test is fast and isolated.
    server._policy = None
    monkeypatch.setenv("BLENDER_MCP_POLICY", "")

    from blender_mcp.policy import Policy

    tiny = Policy({"max_polys": 100})
    monkeypatch.setattr(server, "_policy", tiny)

    # 50 cubes with subsurf level 4 (~256x each = 76 800 polys) blows past 100.
    big_specs = [
        {"kind": "cube", "modifiers": [{"type": "SUBSURF", "properties": {"levels": 4}}]}
        for _ in range(50)
    ]
    out = await server.transaction(
        steps=[{"tool": "create_objects", "args": {"specs": big_specs}}]
    )
    assert out.get("error") == "POLICY_DENIED"
    assert out.get("code") == "POLY_BUDGET_EXCEEDED"
    assert out.get("estimated_polys", 0) > tiny.max_polys

    # Reset for other tests
    server._policy = None


@pytest.mark.asyncio
async def test_transaction_allows_small_nested_create_objects(monkeypatch):
    """Sanity: transactions under the cap still pass through to _call."""
    server._policy = None
    from blender_mcp.policy import Policy

    monkeypatch.setattr(server, "_policy", Policy({"max_polys": 1_000_000}))

    captured: dict = {}

    async def fake_call(op, args=None, timeout=30.0):
        captured["op"] = op
        captured["args"] = args
        return {"ok": True}

    monkeypatch.setattr(server, "_call", fake_call)
    out = await server.transaction(
        steps=[{"tool": "create_objects", "args": {"specs": [{"kind": "cube"}]}}]
    )
    assert out == {"ok": True}
    assert captured["op"] == "transaction"
    server._policy = None


# ---------------------------------------------------------------------------
# Issue #2: READ_ONLY_TOOLS must list real tools and exclude ghosts
# ---------------------------------------------------------------------------


def test_read_only_tools_match_real_tool_names():
    """Every name in READ_ONLY_TOOLS must correspond to a tool registered
    on the FastMCP server. Catches typos / dead entries.

    Uses the runtime tool registry (rather than text-scraping the source
    file) so it works for tools registered via `@_tool()`, `@_proxy()`,
    or any future decorator.
    """
    import asyncio
    tools = asyncio.run(server.mcp.list_tools())
    real_tools = {t.name for t in tools}
    ghosts = READ_ONLY_TOOLS - real_tools
    assert not ghosts, f"READ_ONLY_TOOLS contains tools that don't exist: {ghosts}"


def test_read_only_tools_includes_introspection():
    """Status panels poll these; they must NOT be rate-limited."""
    for required in ("query", "list", "describe_api", "get_property"):
        assert required in READ_ONLY_TOOLS, f"{required} should be read-only"


# ---------------------------------------------------------------------------
# Issue #4: Windows reserved names sanitised in checkpoint labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reserved", ["CON", "PRN", "NUL", "AUX", "COM1", "LPT9", "con", "Com3"])
def test_safe_label_handles_windows_reserved(reserved):
    out = ck._safe_label(reserved)
    assert out.upper() not in ck._WINDOWS_RESERVED


def test_safe_label_keeps_normal_names_unchanged():
    assert ck._safe_label("normal-label") == "normal-label"


# ---------------------------------------------------------------------------
# Issue #6: timestamp collisions don't overwrite previous checkpoints
# ---------------------------------------------------------------------------


def test_build_paths_no_collision_in_same_microsecond(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    # Pin _timestamp() to a constant so first call returns it; build_paths
    # must then produce a unique filename anyway.
    monkeypatch.setattr(ck, "_timestamp", lambda: "20260101T000000_000000Z")
    blend1, meta1, _, _ = ck.build_paths("/x.blend", "label")
    blend1.parent.mkdir(parents=True, exist_ok=True)
    blend1.write_bytes(b"x")
    meta1.write_text("{}", encoding="utf-8")

    blend2, meta2, _, _ = ck.build_paths("/x.blend", "label")
    assert blend1 != blend2
    assert meta1 != meta2
    assert not blend2.exists()


# ---------------------------------------------------------------------------
# Issue #7: discovery-file path is actually exercised
# ---------------------------------------------------------------------------


def test_discover_endpoint_reads_real_discovery_file(monkeypatch, tmp_path):
    """Round-trip the discovery file end-to-end without env overrides."""
    monkeypatch.delenv("BLENDER_MCP_APPROVAL_URL", raising=False)
    monkeypatch.delenv("BLENDER_MCP_APPROVAL_CSRF", raising=False)
    if sys.platform == "win32":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        ddir = tmp_path / "BlenderMCP"
    elif sys.platform == "darwin":
        monkeypatch.setenv("HOME", str(tmp_path))
        ddir = tmp_path / "Library" / "Application Support" / "BlenderMCP"
    else:
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        ddir = tmp_path / "blender-mcp"

    ddir.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": "http://127.0.0.1:54321",
        "csrf": "abc-123",
        "pid": os.getpid(),  # current pid is alive
    }
    (ddir / "approval.json").write_text(json.dumps(payload), encoding="utf-8")

    ep = discover_endpoint()
    assert ep is not None
    assert ep.url == "http://127.0.0.1:54321"
    assert ep.csrf == "abc-123"


def test_discover_endpoint_rejects_dead_pid(monkeypatch, tmp_path):
    monkeypatch.delenv("BLENDER_MCP_APPROVAL_URL", raising=False)
    monkeypatch.delenv("BLENDER_MCP_APPROVAL_CSRF", raising=False)
    if sys.platform == "win32":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        ddir = tmp_path / "BlenderMCP"
    elif sys.platform == "darwin":
        monkeypatch.setenv("HOME", str(tmp_path))
        ddir = tmp_path / "Library" / "Application Support" / "BlenderMCP"
    else:
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        ddir = tmp_path / "blender-mcp"

    ddir.mkdir(parents=True, exist_ok=True)
    # PID 1 exists on Unix (init) but not under our control; on Windows pid 0
    # is the System Idle Process which our liveness check treats as alive.
    # Use a very high pid that should not exist on a normal test box.
    dead_pid = 999_999
    (ddir / "approval.json").write_text(
        json.dumps({"url": "http://127.0.0.1:1", "csrf": "x", "pid": dead_pid}),
        encoding="utf-8",
    )
    assert discover_endpoint() is None
