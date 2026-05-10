"""Contract test: every tool with a filesystem-path parameter must be
registered for jail-checking.

This test exists because we keep shipping directory-traversal bugs by
hand (load_image v3.0, restore_checkpoint pre-refactor, ...). Catching
"author forgot to call ``policy.validate_path``" with a per-PR text review
is the wrong primitive — make it a CI failure instead.

How it works
------------
1. Walk every tool the FastMCP server actually exposes.
2. Resolve each tool to its underlying Python function (via the wrapper's
   ``__wrapped__`` chain) so we see the real type-annotated signature.
3. For every parameter whose name strongly suggests a filesystem path
   (``path``, ``directory``, ``blend_path``, ...), assert that the tool
   appears in ``server._PATH_ARG_REGISTRY`` AND that the parameter is
   listed in its registered tuple.
4. Known false positives — parameters that look path-shaped but aren't
   filesystem paths (``set_property.path`` is an RNA path, ``query.target``
   isn't even called ``path``) — go in ``_ALLOWED_NON_FS_PATHS``.

Failure messages name the offending tool + parameter and point to the fix:
either decorate with ``@_proxy(paths=("path",))`` or call
``_register_path_args("tool", "path")`` from the manual wrapper.
"""

from __future__ import annotations

import asyncio
import inspect


from blender_mcp import server


# Parameter names that, if seen on a tool, MUST be jail-checked.
# Keep this list deliberately conservative (only names that are very
# unlikely to mean anything except "filesystem path").
_FILESYSTEM_PATH_PARAM_NAMES = frozenset(
    {
        "path",
        "filepath",
        "file_path",
        "filename",
        "directory",
        "dir",
        "folder",
        "blend_path",
        "asset_path",
        "image_path",
        "output_path",
    }
)

# Opt-out: (tool_name, param_name) pairs where the parameter happens to
# match a filesystem-path name but is something else entirely. Be sparing
# here — every entry is a place where the contract test is silenced.
_ALLOWED_NON_FS_PATHS: frozenset[tuple[str, str]] = frozenset(
    {
        # set_property/get_property accept a Python-style RNA path, e.g.
        # "bpy.data.scenes['Scene'].cycles.samples". Not a filesystem path.
        ("set_property", "path"),
        ("get_property", "path"),
    }
)


def _registered_tools() -> dict[str, object]:
    """Return {tool_name: underlying_async_function} for every FastMCP tool."""
    tools = asyncio.run(server.mcp.list_tools())
    out: dict[str, object] = {}
    for t in tools:
        # FastMCP keeps the original (or @functools.wraps-preserved) callable
        # at server._tool_manager._tools[name].fn.
        info = server.mcp._tool_manager._tools.get(t.name)  # type: ignore[attr-defined]
        if info is None:
            continue
        fn = info.fn
        # Walk __wrapped__ once so we land on the developer-authored function
        # whose signature describes the parameter names we care about.
        out[t.name] = getattr(fn, "__wrapped__", fn)
    return out


def _path_like_params(fn: object) -> list[str]:
    """Return the parameter names of ``fn`` that look like filesystem paths."""
    try:
        sig = inspect.signature(fn)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return []
    return [
        name
        for name in sig.parameters.keys()
        if name in _FILESYSTEM_PATH_PARAM_NAMES
    ]


def test_every_path_taking_tool_is_registered_for_jail_checking():
    """Structural enforcement: any tool with a filesystem-path parameter
    must declare it in `server._PATH_ARG_REGISTRY`.

    Add the registration either by:
      * decorating with ``@_proxy(paths=("path",))``  (preferred), or
      * calling ``_register_path_args("tool", "path")`` from a manual wrapper.
    """
    tools = _registered_tools()
    failures: list[str] = []

    for tool_name, fn in tools.items():
        path_params = _path_like_params(fn)
        if not path_params:
            continue
        registered = set(server._PATH_ARG_REGISTRY.get(tool_name, ()))
        for param in path_params:
            if (tool_name, param) in _ALLOWED_NON_FS_PATHS:
                continue
            if param not in registered:
                failures.append(
                    f"  - {tool_name}({param}=...): looks like a filesystem "
                    f"path but is not jail-checked. Fix one of:\n"
                    f"        @_proxy(paths=({param!r},))   # preferred\n"
                    f"        _register_path_args({tool_name!r}, {param!r})\n"
                    f"    Or, if {param!r} is genuinely not a filesystem "
                    f"path, add ({tool_name!r}, {param!r}) to "
                    f"_ALLOWED_NON_FS_PATHS in this test."
                )

    assert not failures, (
        "Path-jail contract violations:\n" + "\n".join(failures)
    )


def test_path_arg_registry_only_references_real_tools():
    """No stale entries in `_PATH_ARG_REGISTRY` for renamed/removed tools."""
    real = set(_registered_tools())
    stale = set(server._PATH_ARG_REGISTRY) - real
    assert not stale, (
        f"_PATH_ARG_REGISTRY references non-existent tools: {sorted(stale)}"
    )


def test_path_arg_registry_only_references_real_params():
    """Each registered (tool, param) must actually exist on that tool."""
    tools = _registered_tools()
    bad: list[str] = []
    for tool_name, params in server._PATH_ARG_REGISTRY.items():
        fn = tools.get(tool_name)
        if fn is None:
            continue  # caught by the previous test
        try:
            sig = inspect.signature(fn)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        for p in params:
            if p not in sig.parameters:
                bad.append(f"{tool_name!r}: parameter {p!r} not in signature")
    assert not bad, "Stale path-arg registrations:\n  - " + "\n  - ".join(bad)


def test_known_path_taking_tools_are_registered():
    """Belt-and-suspenders: the four tools we know take filesystem paths
    must be registered. Catches the case where someone deletes the
    decorator + forgets the test would still pass because the param name
    happens to fall outside the heuristic set.
    """
    expected = {
        "import_asset": ("path",),
        "link_blend": ("path",),
        "list_assets": ("directory",),
        "load_image": ("path",),
        "restore_checkpoint": ("blend_path",),
    }
    for tool, params in expected.items():
        registered = server._PATH_ARG_REGISTRY.get(tool)
        assert registered is not None, (
            f"{tool} is missing from _PATH_ARG_REGISTRY"
        )
        for p in params:
            assert p in registered, (
                f"{tool}: parameter {p!r} not registered (got {registered})"
            )
