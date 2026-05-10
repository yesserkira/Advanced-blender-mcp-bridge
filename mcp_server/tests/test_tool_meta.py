"""Tests for tool_meta — every @mcp.tool() in server.py must have an entry."""

from __future__ import annotations

import asyncio

import pytest

from blender_mcp import server, tool_meta


def _real_tool_names() -> set[str]:
    """Enumerate FastMCP-registered tools at runtime.

    This is the source of truth — it sees tools whether they were
    registered via `@_tool()`, `@_proxy()`, or any other path.
    """
    tools = asyncio.run(server.mcp.list_tools())
    return {t.name for t in tools}


def test_tool_meta_covers_all_tools():
    real = _real_tool_names()
    missing = real - set(tool_meta.TOOL_META)
    assert not missing, (
        f"tool_meta.TOOL_META is missing entries for: {sorted(missing)}. "
        "Every @_tool() in server.py must have an annotations row."
    )


def test_tool_meta_has_no_ghost_entries():
    real = _real_tool_names()
    ghosts = set(tool_meta.TOOL_META) - real
    assert not ghosts, (
        f"tool_meta.TOOL_META has rows for non-existent tools: {sorted(ghosts)}"
    )


def test_read_only_tools_helper_subset_of_meta():
    ro = tool_meta.read_only_tools()
    for name in ro:
        assert tool_meta.for_tool(name).get("readOnlyHint") is True


def test_known_destructive_tools_marked():
    for name in ("delete_object", "execute_python", "restore_checkpoint",
                 "remove_modifier"):
        assert tool_meta.for_tool(name).get("destructiveHint") is True, (
            f"{name} must be marked destructiveHint=True"
        )


def test_known_introspection_tools_marked_read_only():
    for name in ("ping", "query", "list", "describe_api", "get_property",
                 "scene_diff", "list_checkpoints"):
        assert tool_meta.for_tool(name).get("readOnlyHint") is True, (
            f"{name} must be marked readOnlyHint=True"
        )


@pytest.mark.parametrize("name", [
    "import_asset", "link_blend", "list_assets",
    "create_checkpoint", "restore_checkpoint",
    "execute_python",
])
def test_open_world_tools_marked(name):
    assert tool_meta.for_tool(name).get("openWorldHint") is True
