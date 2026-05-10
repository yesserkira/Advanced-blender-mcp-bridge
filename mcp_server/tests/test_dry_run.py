"""v2.2 dry-run plumbing tests.

Verify that:
1. ``BlenderWS.call(..., dry_run=True)`` puts the flag in the WS envelope.
2. The MCP tool wrappers (`create_objects`, `delete_object`, `set_transform`)
   propagate the `dry_run` parameter into the WS call.
3. The fake server's echo of `dry_run` is reflected in the tool's response —
   proving the round-trip without a real Blender.

Note: the real add-on enforces the dry-run short-circuit inside each
capability via `capabilities/_dryrun.py`. Here we only validate the
plumbing; capability-side behaviour is exercised by the headless Blender
integration suite added in Phase D.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("BLENDER_MCP_TOKEN", "test")
os.environ.setdefault("BLENDER_MCP_URL", "ws://127.0.0.1:19876")

from blender_mcp import server  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch, fake_blender):
    monkeypatch.setenv("BLENDER_MCP_TOKEN", "test")
    monkeypatch.setenv("BLENDER_MCP_URL", f"ws://{fake_blender.host}:{fake_blender.port}")
    server._bl = None
    server._policy = None
    yield
    if server._bl is not None:
        try:
            import asyncio
            asyncio.get_event_loop().run_until_complete(server._bl.close())
        except Exception:
            pass
        server._bl = None
    server._policy = None


@pytest.mark.asyncio
async def test_create_objects_dry_run_round_trips():
    out = await server.create_objects(
        specs=[{"kind": "cube", "name": "DryCube"}],
        dry_run=True,
    )
    assert out.get("dry_run") is True, out


@pytest.mark.asyncio
async def test_create_objects_default_is_not_dry_run():
    out = await server.create_objects(specs=[{"kind": "cube"}])
    assert "dry_run" not in out or out["dry_run"] is False


@pytest.mark.asyncio
async def test_delete_object_dry_run_round_trips():
    out = await server.delete_object(object="Cube", dry_run=True)
    assert out.get("dry_run") is True, out


@pytest.mark.asyncio
async def test_delete_object_dry_run_skips_approval(monkeypatch):
    """Even if confirm_required, dry_run must NOT call the approval flow."""
    server._policy = None
    pol = server._get_policy()
    pol.confirm_required = ["delete_object"]

    called = {"n": 0}

    async def boom(*a, **kw):
        called["n"] += 1
        raise RuntimeError("approval should not be called for dry_run")

    monkeypatch.setattr("blender_mcp.approval.request_approval", boom)
    out = await server.delete_object(object="Cube", dry_run=True)
    assert called["n"] == 0
    assert out.get("dry_run") is True


@pytest.mark.asyncio
async def test_set_transform_dry_run_round_trips():
    out = await server.set_transform(object="Cube", location=[1, 2, 3], dry_run=True)
    assert out.get("dry_run") is True, out


@pytest.mark.asyncio
async def test_dry_run_envelope_field():
    """Inspect the round-trip: BlenderWS.call must include `dry_run: true`
    in the WS envelope. We verify by relying on the fake server's echo: it
    only attaches `dry_run: True` to dict results when the envelope field
    is set, so `True` vs unset/`False` must differ.
    """
    bl = server._get_client()
    out_true = await bl.call(
        "create_objects", {"specs": [{"kind": "cube"}]}, dry_run=True,
    )
    out_false = await bl.call(
        "create_objects", {"specs": [{"kind": "cube"}]},
    )
    assert out_true.get("dry_run") is True
    assert out_false.get("dry_run") in (False, None)
