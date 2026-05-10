"""Pytest fixtures for headless Blender integration tests."""

from __future__ import annotations

import bpy
import pytest


@pytest.fixture(autouse=True)
def fresh_scene():
    """Reset to factory startup before each test for isolation."""
    bpy.ops.wm.read_factory_settings(use_empty=False)
    yield
    # No teardown needed; next test resets again.


def call(op: str, args: dict | None = None, dry_run: bool = False) -> dict:
    """Invoke a capability via the dispatcher (bypassing the WS layer)."""
    from blender_addon.server.dispatcher import dispatch
    return dispatch(
        {"id": "test", "op": op, "args": args or {}},
        dry_run=dry_run,
    )
