"""Blender MCP Server v2.0 — generic, batch-aware, introspection-driven.

Exposes a small set of LOAD-BEARING tools rather than many narrow wrappers.
Every mutator accepts a single args dict OR an "items" list for batched
execution under one undo step.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Awaitable, Callable, TypeVar, cast

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import perf, tool_meta
from .api_cache import DescribeApiCache
from .blender_client import BlenderError, BlenderWS
from .policy import Policy, PolicyDenied
from .snapshot_cache import SnapshotCache

logger = logging.getLogger("blender_mcp")

# Server-level instructions surfaced to the MCP client (Copilot Chat,
# Claude Desktop, etc.). This primes the model with how to use the tools
# correctly — most importantly: always call `ping` first so it has scene
# orientation before reasoning about the user's 3D request.
_SERVER_INSTRUCTIONS = """\
Blender bridge — call `ping` FIRST in every new conversation.

`ping` returns scene + selection + units + active camera in one shot, which
replaces 3-5 separate `query`/`list` calls and prevents you from creating
duplicate or misplaced objects.

Tool design notes:
- Mutators accept either a single args dict or an `items` list for batched
  execution under one undo step. Prefer batching when creating >1 object.
- Spatial helpers (`place_above`, `align_to`, `array_around`, `distribute`,
  `look_at`) are preferred over manual coordinate math — they read bbox and
  align correctly without selection juggling.
- Use `rename` (not `execute_python`) for renaming any datablock.
- Use `call_operator` with `select=[...]` / `active=...` to atomically set
  selection context for operators that need it; this fixes most CANCELLED
  errors without a separate `select` call.
- After visual changes, call `viewport_screenshot` so the user can see the
  result.
"""

mcp = FastMCP("blender", instructions=_SERVER_INSTRUCTIONS)

_bl: BlenderWS | None = None
_policy: Policy | None = None
_describe_api_cache: DescribeApiCache = DescribeApiCache()
# Phase 3: TTL-coalesce repeated read-only Blender ops within a turn.
_snapshot_cache: SnapshotCache = SnapshotCache()
# Read-only ops eligible for snapshot-cache coalescing. Sourced from
# tool_meta + the underlying Blender op names (since one tool can map to
# a different op name, e.g. tool ``ping`` -> op ``scene.context``).
_CACHEABLE_OPS: frozenset[str] = frozenset({
    "scene.context", "scene.snapshot", "ping",
    "query", "list", "bbox_info",
    "list_collections", "list_constraints",
    "list_vertex_groups", "list_shape_keys",
})


_F = TypeVar("_F", bound=Callable[..., Awaitable[Any]])


def _tool(name: str | None = None) -> Callable[[_F], _F]:
    """Wrap @_tool() and inject ToolAnnotations from tool_meta.

    Usage:
        @_tool()                     # tool name = function name
        async def query(...): ...

        @_tool(name="list")          # explicit override
        async def list_(...): ...
    """
    def decorator(fn: _F) -> _F:
        tool_name = name or fn.__name__
        meta = tool_meta.for_tool(tool_name)
        annotations = ToolAnnotations(**meta) if meta else None
        kwargs: dict[str, Any] = {}
        if name:
            kwargs["name"] = name
        if annotations is not None:
            kwargs["annotations"] = annotations
        # FastMCP returns the wrapped fn; cast to preserve the original sig
        # for downstream type-checkers (the decorator is transparent).
        return cast(_F, mcp.tool(**kwargs)(fn))
    return decorator


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def _resolve_credentials() -> tuple[str, str]:
    """Resolve (url, token) from connection.json / env / keyring.

    Selection rules (in order):
      1. If ``BLENDER_MCP_URL`` env is set and points to a *different*
         endpoint than ``~/.blender_mcp/connection.json``, env wins
         entirely. This preserves explicit overrides (and test isolation
         where fixtures spin a fake server on a different port).
      2. Otherwise, when ``connection.json`` exists, its token+url win.
         The token rotates every time the add-on restarts the WS server,
         and that file is the LIVE truth -- it must beat any stale
         ``BLENDER_MCP_TOKEN`` env injected at VS Code extension spawn
         time (which can't refresh after Blender restarts).
      3. Otherwise, fall back to env values.
      4. Keyring is consulted only if no token was found by the above.

    Re-reads on every call so a stale ``_bl`` can be replaced after the
    Blender add-on regenerates its token (e.g. on restart).
    """
    env_token = os.environ.get("BLENDER_MCP_TOKEN", "") or ""
    env_url = os.environ.get("BLENDER_MCP_URL")

    # Read connection.json if present.
    file_token = ""
    file_url: str | None = None
    try:
        import json as _json
        cf = os.path.join(
            os.path.expanduser("~"), ".blender_mcp", "connection.json"
        )
        if os.path.exists(cf):
            with open(cf, "r", encoding="utf-8") as f:
                data = _json.load(f)
            file_token = data.get("token", "") or ""
            host = data.get("host", "127.0.0.1")
            port = int(data.get("port", 9876))
            file_url = f"ws://{host}:{port}"
    except Exception:
        pass

    # Decide source. If env URL is set and differs from the connection
    # file's URL, the user/test is explicitly targeting a different
    # endpoint -- env wins entirely (this preserves test isolation and
    # honors explicit overrides). Otherwise the connection file is the
    # live truth (the token rotates every Blender restart, beating any
    # stale env value injected at extension spawn time).
    if env_url and file_url and env_url != file_url:
        url = env_url
        token = env_token
    elif file_token:
        url = file_url or env_url or "ws://127.0.0.1:9876"
        token = file_token
    else:
        url = env_url or "ws://127.0.0.1:9876"
        token = env_token

    # Keyring last-known-good fallback.
    if not token:
        try:
            import keyring
            token = keyring.get_password("blender-mcp", "default") or ""
        except Exception:
            pass

    return (url, token)


def _get_client() -> BlenderWS:
    global _bl
    if _bl is None:
        url, token = _resolve_credentials()
        # Phase 9: enforce connection-target policy (allowed_remote_hosts,
        # require_tls). Loopback URLs always pass; remote URLs must be
        # explicitly allowed by the active policy. Let PolicyDenied
        # propagate as-is so tool wrappers can format the structured
        # code/hint instead of a generic RuntimeError.
        _get_policy().validate_connection_url(url)
        _bl = BlenderWS(url=url, token=token)
        _bl.set_notification_handler(_on_blender_notification)
    return _bl


async def _reset_client_for_reauth() -> None:
    """Drop the cached client so the next call rebuilds with fresh creds.

    Called when Blender returns AUTH \u2014 typically because the add-on
    regenerated its token after a server restart and our in-memory token
    is now stale. Re-reading ``connection.json`` is enough to recover
    without requiring users to restart their AI client.
    """
    global _bl
    old = _bl
    _bl = None
    if old is not None:
        try:
            await old.close()
        except Exception:
            pass


def _get_policy() -> Policy:
    global _policy
    if _policy is None:
        _policy = Policy.load(os.environ.get("BLENDER_MCP_POLICY"))
    return _policy


async def _call(
    op: str,
    args: dict[str, Any] | None = None,
    timeout: float = 30.0,
    dry_run: bool = False,
) -> Any:
    """Call a Blender op and return either the raw result or a uniform error dict.

    Return shape depends on the op: most ops return ``dict[str, Any]``, but
    ``query`` / ``list`` legitimately return lists and ``ping`` returns a
    string. Errors are always ``{"error": code, "message": str, ...}``.

    Tool wrappers that promise a specific shape should call ``_call_dict``
    or ``_call_list`` instead of casting at every site.

    Every call here is recorded to the perf ring buffer (always-on, ~3µs).
    Payload sizes are measured only when ``BLENDER_MCP_PERF`` is set, since
    JSON-encoding twice for measurement isn't free for big results.

    Phase 3: read-only ops in ``_CACHEABLE_OPS`` go through the snapshot
    cache (TTL = ``BLENDER_MCP_SNAPSHOT_TTL_MS`` ms, default 200). Mutating
    ops (everything else, plus ``dry_run=False``) bump the cache epoch so
    the next read sees fresh data. Dry-run mutations don't bump — they
    didn't change the scene.
    """
    is_cacheable = (
        not dry_run and op in _CACHEABLE_OPS and not _is_mutating_op(op)
    )

    async def _do_call() -> Any:
        measure_payload = perf.is_verbose()
        payload_in_b = (
            len(json.dumps(args or {}, default=str)) if measure_payload else 0
        )
        t0 = time.perf_counter()
        ok = True
        result: Any
        try:
            bl = _get_client()
            try:
                result = await bl.call(op, args or {}, timeout=timeout, dry_run=dry_run)
            except BlenderError as e:
                # Stale-token recovery: when Blender restarts its WS server
                # it regenerates the auth token in connection.json. Our
                # cached client still holds the old one. Drop the cache,
                # re-read credentials, and retry exactly once.
                if e.code == "AUTH":
                    await _reset_client_for_reauth()
                    bl = _get_client()
                    result = await bl.call(
                        op, args or {}, timeout=timeout, dry_run=dry_run,
                    )
                else:
                    raise
        except BlenderError as e:
            ok = False
            result = {"error": e.code, "message": str(e)}
        except PolicyDenied as e:
            ok = False
            result = {"error": getattr(e, "code", "POLICY_DENIED"), "message": str(e), "hint": e.hint}
        except asyncio.TimeoutError:
            ok = False
            result = {"error": "TIMEOUT", "message": f"Blender did not respond to '{op}' within {timeout}s"}
        finally:
            wall_ms = (time.perf_counter() - t0) * 1000.0
            payload_out_b = 0
            if measure_payload:
                try:
                    payload_out_b = len(json.dumps(result, default=str))
                except (TypeError, ValueError):
                    # Non-serialisable result (e.g. raw bytes from a binary op).
                    # Don't crash perf measurement on it.
                    payload_out_b = 0
            perf.record(op, wall_ms, ok, payload_in_b, payload_out_b)
        return result

    if is_cacheable:
        return await _snapshot_cache.get_or_call(op, args, _do_call)

    result = await _do_call()
    # Bump cache epoch on a real mutation (not dry-run, not an error).
    if not dry_run and _is_mutating_op(op) and not (
        isinstance(result, dict) and "error" in result
    ):
        _snapshot_cache.bump_epoch()
    return result


def _is_mutating_op(op: str) -> bool:
    """Heuristic: an op is mutating unless it's in the cacheable read-only set
    or has a name pattern that's clearly read-only.

    The Blender op namespace doesn't carry a formal mutating flag, but the
    tool-level ``readOnlyHint`` covers most of it. We additionally include
    ``describe_api`` (introspection only) and any op whose dotted prefix is
    a known read-only namespace.
    """
    if op in _CACHEABLE_OPS:
        return False
    if op == "describe_api":
        return False
    if op.startswith(("audit.", "checkpoint.list", "render.viewport_screenshot", "render.region", "render.bake_preview")):
        return False
    return True


async def _call_dict(
    op: str,
    args: dict[str, Any] | None = None,
    timeout: float = 30.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """`_call` for ops that always return a dict (the common case).

    The cast is honest: every Blender op except ``query`` / ``list`` /
    ``ping`` returns a dict, and the error envelope is always a dict too.
    """
    # Forward dry_run only when set, so test fakes that don't accept the
    # kwarg keep working (matches the call-site convention of the wrappers).
    if dry_run:
        result = await _call(op, args, timeout=timeout, dry_run=True)
    else:
        result = await _call(op, args, timeout=timeout)
    return cast("dict[str, Any]", result)


async def _call_list(
    op: str,
    args: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """`_call` for ops that always return a list (``list``, parts of ``query``)."""
    return cast("list[dict[str, Any]]", await _call(op, args, timeout=timeout))


# ===========================================================================
# Tool wrapper factory + path-jail registry
# ---------------------------------------------------------------------------
# Most tool wrappers were five identical lines:
#   _get_policy().require("foo")
#   args: dict[str, Any] = {...}
#   if optional is not None: args["optional"] = optional
#   return await _call_dict("foo", args)
#
# For tools that take filesystem paths the same five lines plus a
# `policy.validate_path(...)` call had to be hand-written, and any new
# tool that forgot the validate_path call became a directory-traversal bug
# (this is exactly how `load_image` shipped insecure in v3.0).
#
# `_proxy()` turns the common shape into a single decorator and, by giving
# `paths=` first-class status, makes the path-jail step structurally
# enforceable: the contract test in `tests/test_path_jail_contract.py`
# walks every FastMCP-registered tool and asserts that any parameter whose
# name looks like a filesystem path is registered in `_PATH_ARG_REGISTRY`.
# ===========================================================================


import functools as _functools  # noqa: E402
import inspect as _inspect  # noqa: E402

# tool_name -> tuple of parameter names that are filesystem paths and must
# be validated through `policy.validate_path()` before dispatch. Populated
# by `_proxy(paths=...)` and the explicit `_register_path_args()` helper
# (used by manual wrappers that can't use _proxy).
_PATH_ARG_REGISTRY: dict[str, tuple[str, ...]] = {}


def _register_path_args(tool: str, *params: str) -> None:
    """Declare that <tool> takes <params> as filesystem paths.

    Use this from manual wrappers that can't sit under `@_proxy()` (because
    they have batching, approval, or other custom logic) so the contract
    test still sees them as path-jailed.
    """
    _PATH_ARG_REGISTRY[tool] = params


def _jail_paths(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Validate every registered path arg in `args` (in-place) and return it.

    Imperative companion to `_proxy(paths=...)`. Manual wrappers should
    call this before dispatching to `_call_dict`.
    """
    policy = _get_policy()
    for p in _PATH_ARG_REGISTRY.get(tool_name, ()):
        v = args.get(p)
        if v is not None:
            args[p] = str(policy.validate_path(v))
    return args


def _proxy(
    op: str | None = None,
    *,
    paths: tuple[str, ...] = (),
    timeout: float = 30.0,
    pass_dry_run: bool = False,
) -> Callable[[_F], _F]:
    """Decorator that builds a FastMCP tool wrapper from the function signature.

    The wrapped function's body is never executed — only its signature,
    type hints, and docstring matter (FastMCP introspects them to build
    the JSON schema visible to the model).

    Behaviour at call-time:
      1. `_get_policy().require(<tool_name>)`
      2. Validate each parameter listed in `paths` via `policy.validate_path()`
      3. Drop kwargs whose value is None (matches the manual
         "if x is not None: args[k] = x" pattern)
      4. If `pass_dry_run=True`, pop `dry_run` and forward it to `_call_dict`
      5. `await _call_dict(op or fn.__name__, args, timeout=...)`

    For tools with batching, approval, polygon-budget, or custom result
    shaping, write the wrapper manually and call `_jail_paths(name, args)`
    yourself so the contract test still sees the registration.
    """
    def decorator(fn: _F) -> _F:
        tool_name = fn.__name__
        op_name = op or tool_name
        if paths:
            _PATH_ARG_REGISTRY[tool_name] = paths

        sig = _inspect.signature(fn)
        # Params that default to None: drop from the args dict when the
        # caller didn't supply them (matches the manual
        # "if x is not None: args[k] = x" pattern). Required params or
        # params with non-None defaults are always forwarded as-is, so
        # callers can pass None deliberately if they want.
        _optional_none_params = {
            name for name, p in sig.parameters.items()
            if p.default is None
        }

        @_functools.wraps(fn)
        async def wrapper(**kwargs: Any) -> dict[str, Any]:
            policy = _get_policy()
            policy.require(tool_name)
            for p in paths:
                v = kwargs.get(p)
                if v is not None:
                    kwargs[p] = str(policy.validate_path(v))
            dry = False
            if pass_dry_run:
                dry = bool(kwargs.pop("dry_run", False))
            args = {
                k: v for k, v in kwargs.items()
                if not (v is None and k in _optional_none_params)
            }
            if pass_dry_run:
                return await _call_dict(op_name, args, timeout=timeout, dry_run=dry)
            return await _call_dict(op_name, args, timeout=timeout)

        # Make sure FastMCP/pydantic see the original signature when they
        # introspect this wrapper to build the tool schema.
        wrapper.__signature__ = sig  # type: ignore[attr-defined]
        return cast(_F, _tool()(wrapper))

    return decorator


# ===========================================================================
# Resources (v2.2): expose live scene data so AI clients can read it as
# context every turn instead of issuing many `query` calls.
# ===========================================================================


@mcp.resource(
    "blender://scene/current",
    name="Current Blender Scene",
    description=(
        "Compact JSON snapshot of the active Blender scene: objects, "
        "materials, render settings, selection, hash. Designed to be read "
        "once per turn as cheap context. Capped at 500 objects by default; "
        "use the `list` tool with filters for full enumeration of larger "
        "scenes."
    ),
    mime_type="application/json",
)
async def resource_scene_current() -> str:
    import json as _json
    result = await _call_dict("scene.snapshot", {})
    if isinstance(result, dict) and result.get("error"):
        # Surface errors as JSON so the client sees them rather than a
        # broken resource.
        return _json.dumps(result)
    return _json.dumps(result)


@mcp.resource(
    "blender://scene/summary",
    name="Blender Scene Summary",
    description=(
        "Counts-only digest (~200 bytes) of the active scene: object/material/"
        "collection counts, frame range, render engine, hash. Cheap to poll."
    ),
    mime_type="application/json",
)
async def resource_scene_summary() -> str:
    import json as _json
    result = await _call_dict("scene.snapshot", {"summary": True})
    return _json.dumps(result)


# ===========================================================================
# v2.3: change notifications. The add-on broadcasts {"type": "notification",
# "event": "scene.changed", "uri": ..., "hash": ...} on a depsgraph update.
# We track which resources the MCP client has subscribed to and forward as
# notifications/resources/updated through the active session.
# ===========================================================================


_subscribed_uris: set[str] = set()
_active_session = None  # mcp.server.session.ServerSession (captured on first
                         # subscribe). For stdio there is exactly one session.


@mcp._mcp_server.subscribe_resource()  # type: ignore[no-untyped-call,untyped-decorator]
async def _on_subscribe(uri: Any) -> None:
    global _active_session
    _subscribed_uris.add(str(uri))
    try:
        _active_session = mcp._mcp_server.request_context.session
    except Exception:
        # request_context only exists inside a request — should always work
        # for a subscribe call but stay defensive.
        pass
    logger.info("Resource subscribed: %s", uri)


@mcp._mcp_server.unsubscribe_resource()  # type: ignore[no-untyped-call,untyped-decorator]
async def _on_unsubscribe(uri: Any) -> None:
    _subscribed_uris.discard(str(uri))
    logger.info("Resource unsubscribed: %s", uri)


async def _on_blender_notification(frame: dict[str, Any]) -> None:
    """Forward an add-on notification to subscribed MCP clients."""
    event = frame.get("event")
    uri = frame.get("uri")
    if event != "scene.changed" or not uri:
        return
    # Phase 3: an external Blender edit (user moves a cube in the UI)
    # invalidates the snapshot cache. Without this, a stale ``ping`` cached
    # 199ms ago would mask the change for the rest of the TTL window.
    _snapshot_cache.bump_epoch()
    if _active_session is None:
        logger.debug("notification dropped — no active session")
        return

    # blender://scene/current and blender://scene/summary share the same
    # underlying snapshot; notify both if either is subscribed.
    sibling = (
        "blender://scene/summary" if uri == "blender://scene/current"
        else "blender://scene/current" if uri == "blender://scene/summary"
        else None
    )
    targets = {uri}
    if sibling and sibling in _subscribed_uris:
        targets.add(sibling)
    targets &= _subscribed_uris
    if not targets:
        return

    from pydantic import AnyUrl
    for target in targets:
        try:
            await _active_session.send_resource_updated(AnyUrl(target))
        except Exception:
            logger.exception("send_resource_updated failed for %s", target)


# ===========================================================================
# Connectivity
# ===========================================================================


@_tool()
async def ping() -> dict[str, Any]:
    """Ping Blender + return scene context for orientation.

    Always call this at the start of a new chat session. Returns:
      - status: 'connected' | 'error'
      - blender_version
      - scene: name, frame, fps, render_engine
      - active_object: name + type if any
      - selection: list of selected object names
      - counts: {objects, materials, lights, cameras, collections}
      - units: {system, scale_length}

    This single call replaces several `query`/`list` calls and gives you
    enough context to plan the user's request intelligently.
    """
    try:
        _get_client()
    except PolicyDenied as e:
        return {"status": "error", "code": getattr(e, "code", "POLICY_DENIED"),
                "message": str(e), "hint": e.hint}
    # Phase 3: route through _call so the snapshot cache + perf ring see
    # this op (the most-called read-only op in the whole system).
    ctx = await _call("scene.context")
    if isinstance(ctx, dict) and "error" in ctx:
        # Fall back to plain ping if scene.context is unavailable.
        fallback = await _call("ping")
        if isinstance(fallback, dict) and "error" in fallback:
            return {"status": "error", **fallback}
        return {
            "status": "connected",
            "warning": f"scene.context unavailable: {ctx.get('error')}",
        }
    if isinstance(ctx, dict):
        # Phase 2: pin the describe_api disk cache to this Blender's
        # version. Idempotent — only does work the first time per
        # process (or after a version switch).
        v = ctx.get("blender_version")
        if isinstance(v, str):
            _describe_api_cache.bind_version(v)
        return {"status": "connected", **ctx}
    return {"status": "connected", "result": ctx}

# ===========================================================================
# P2: Smart awareness
# ===========================================================================


@_tool()
async def query(target: str, fields: list[str] | None = None) -> dict[str, Any] | list[Any]:
    """Granular read of any Blender datablock without downloading the whole scene.

    Target string syntax:
        scene
        scene.render | scene.cycles | scene.eevee
        render | world | view_layer
        object:Cube
        object:Cube.modifiers
        object:Cube.modifiers[0]
        object:Cube.modifiers["Bevel"]
        material:Gold.node_tree.nodes
        collection:Lights

    Args:
        target: dotted RNA path (see above).
        fields: optional list of attribute names to project. Omit for all.

    Returns:
        Dict of properties (or list when target is a collection).
    """
    _get_policy().require("query")
    # `query` returns dict for single targets, list for collection targets.
    return cast(
        "dict[str, Any] | list[Any]",
        await _call("query", {"target": target, "fields": fields}),
    )


@_tool(name="list")
async def list_(kind: str, filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Enumerate datablocks of a given kind.

    Args:
        kind: 'objects' | 'materials' | 'meshes' | 'lights' | 'cameras'
              | 'collections' | 'images' | 'node_groups' | 'actions' | 'scenes'.
        filter: optional dict, supports keys:
                {"type": "MESH"}, {"name_contains": "Ring"},
                {"name_prefix": "Light"}, {"in_collection": "Lights"}.
    """
    _get_policy().require("list")
    return await _call_list("list", {"kind": kind, "filter": filter})


@_tool()
async def describe_api(rna_path: str) -> dict[str, Any]:
    """Introspect a bpy.types class via its bl_rna.

    Returns its property table (name, type, enum items, soft min/max,
    default, description) and registered functions. Use this to discover
    parameters of any modifier, node, or RNA struct without hard-coded knowledge.

    Examples:
        describe_api("SubsurfModifier")
        describe_api("ShaderNodeBsdfPrincipled")
        describe_api("CyclesRenderSettings")
    """
    _get_policy().require("describe_api")
    cached = _describe_api_cache.get(rna_path)
    if cached is not None:
        return cached
    result = await _call_dict("describe_api", {"rna_path": rna_path})
    # Only cache successful responses (no error key).
    if "error" not in result:
        # Pin the cache to this Blender's version on first successful call,
        # so the on-disk file is keyed by version even if `ping` was skipped.
        if _describe_api_cache._version is None:
            try:
                ctx = await _get_client().call("scene.context")
                v = ctx.get("blender_version") if isinstance(ctx, dict) else None
                if isinstance(v, str):
                    _describe_api_cache.bind_version(v)
            except (BlenderError, PolicyDenied):
                pass
        _describe_api_cache.put(rna_path, result)
    return result


@_proxy(op="audit.read")
async def get_audit_log(limit: int = 50, since_ts: str | None = None) -> dict[str, Any]:
    """Tail the local audit log of recently executed commands."""


@_tool()
async def perf_stats(
    window_seconds: float | None = None,
    op: str | None = None,
) -> dict[str, Any]:
    """Read aggregated per-op performance stats from the server-side ring buffer.

    Every Blender op routed through the MCP server is timed and recorded
    (always-on, ~3µs overhead). This tool returns p50/p95/p99/count/error-rate
    aggregated by op name. Use it to spot regressions, slow ops, or hot tools
    a model is over-using.

    Args:
        window_seconds: only count calls in the last N seconds.
                        ``None`` (default) = every entry currently in the ring.
        op: filter to a single op name (default: all ops).

    Returns:
        {
          "window_seconds": <float|None>,
          "ring_capacity": 2000,
          "ring_used": <int>,
          "total_calls": <int>,
          "verbose": <bool>,        # True iff BLENDER_MCP_PERF env var is set
          "ops": {
            "<op>": {
              "count": int, "errors": int,
              "p50_ms": float, "p95_ms": float, "p99_ms": float,
              "max_ms": float, "mean_ms": float,
              "bytes_in_total": int, "bytes_out_total": int,
            }, ...
          }
        }

    Note: ``bytes_in_total`` / ``bytes_out_total`` are 0 unless
    ``BLENDER_MCP_PERF=1`` is set in the server's environment (computing
    JSON length on every result is too expensive for always-on use).
    """
    _get_policy().require("perf_stats")
    out = perf.aggregate(window_seconds=window_seconds, op=op)
    # Phase 2: surface describe_api cache stats so operators can see hit-rate
    # without spelunking the on-disk JSON files.
    out["describe_api_cache"] = _describe_api_cache.stats()
    # Phase 3: snapshot-cache stats (TTL hit-rate is the dial that tells
    # operators whether to bump BLENDER_MCP_SNAPSHOT_TTL_MS up or down).
    out["snapshot_cache"] = _snapshot_cache.stats()
    return out


# ===========================================================================
# P3: Generic pass-through
# ===========================================================================


@_tool()
async def add_modifier(
    object: str | list[dict[str, Any]] | None = None,
    type: str | None = None,
    name: str | None = None,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a modifier to an object (works with all 30+ Blender modifier types).

    Single form:
        add_modifier(object="Cube", type="BEVEL",
                     properties={"width": 0.05, "segments": 3})
    Batch form (one undo step for all):
        add_modifier(object=[
            {"object": "Cube",  "type": "SUBSURF", "properties": {"levels": 2}},
            {"object": "Plane", "type": "SOLIDIFY","properties": {"thickness": 0.1}},
        ])

    Use `describe_api("BevelModifier")` etc. to discover available properties.
    """
    _get_policy().require("add_modifier")
    if isinstance(object, list):
        return await _call_dict("add_modifier", {"items": object})
    args: dict[str, Any] = {"object": object, "type": type}
    if name is not None:
        args["name"] = name
    if properties is not None:
        args["properties"] = properties
    return await _call_dict("add_modifier", args)


@_proxy()
async def remove_modifier(object: str, name: str) -> dict[str, Any]:
    """Remove a modifier from an object by name."""


@_tool()
async def build_nodes(
    target: str,
    graph: dict[str, Any],
    clear: bool = True,
) -> dict[str, Any]:
    """Build any node graph (shader / geometry / world / compositor) declaratively.

    Target syntax:
        material:Gold        - existing material
        material:Gold!       - create if missing
        world                - active scene world (use_nodes auto-enabled)
        scene.compositor     - scene compositor tree
        object:X.modifiers.Y - geometry-nodes modifier (created if missing)

    Graph shape:
        {
          "nodes": [
            {"name":"bsdf","type":"ShaderNodeBsdfPrincipled","location":[0,0],
             "inputs":{"Base Color":[0.8,0.1,0.1,1.0],"Metallic":0.9,"Roughness":0.2}},
            {"name":"out","type":"ShaderNodeOutputMaterial","location":[400,0]}
          ],
          "links": [{"from":"bsdf.BSDF","to":"out.Surface"}]
        }

    Per-node extras (v2.4):
        "color_ramp": [{"position":0.0,"color":[1,0,0,1]}, {"position":1.0,"color":[0,0,1,1]}]
            Configure ShaderNodeValToRGB / similar. Can also be a dict with
            "interpolation" ("LINEAR"/"CONSTANT"/"EASE"/"B_SPLINE"/"CARDINAL")
            and "stops": [...].
        "curves": [{"points":[{"x":0,"y":0},{"x":1,"y":1}], "extend":"EXTRAPOLATED"}]
            Configure RGBCurves / FloatCurve / VectorCurves nodes (one entry
            per channel: R, G, B, Combined or X, Y, Z).

    Deprecated node types (e.g. ShaderNodeTexMusgrave in 4.1+) are auto-mapped
    to their replacement and reported in the response's `warnings` array.
    """
    _get_policy().require("build_nodes")
    return await _call_dict(
        "build_nodes",
        {"target": target, "graph": graph, "clear": clear},
        timeout=60.0,
    )


@_proxy()
async def assign_material(object: str, material: str, slot: int = 0) -> dict[str, Any]:
    """Assign an existing material to an object slot."""


@_tool()
async def rename(kind: str, from_name: str, to_name: str) -> dict[str, Any]:
    """Rename any datablock — object, material, mesh, light, camera, image, etc.

    Args:
        kind: 'object' | 'material' | 'mesh' | 'light' | 'camera' | 'collection' |
              'image' | 'node_group' | 'action' | 'scene' | 'world' | 'texture' |
              'armature' | 'curve'
        from_name: current name of the datablock
        to_name: new name (must not already exist for that kind)

    Returns dict with the actual final name (Blender may suffix on collision).
    """
    _get_policy().require("rename")
    return await _call_dict(
        "rename",
        {"kind": kind, "from": from_name, "to": to_name},
    )


# ===========================================================================
# v2.4: Spatial helpers — semantic positioning instead of raw coordinates
# ===========================================================================


@_proxy()
async def place_above(
    object: str,
    target: str,
    gap: float = 0.0,
    align_xy: str = "center",
) -> dict[str, Any]:
    """Place an object so it sits flush on top of a target.

    Args:
        object: name of object to move
        target: name of target object — OR "ground" to place on Z=0
        gap: optional vertical gap between them (default 0.0)
        align_xy: 'center' (default) — center over target XY
                  'keep'   — keep current XY, only adjust Z
    """


@_proxy()
async def align_to(
    object: str,
    target: str,
    axes: list[str] | None = None,
    mode: str = "center",
) -> dict[str, Any]:
    """Align object to target along one or more axes.

    Args:
        object: name of object to move
        target: name of target object
        axes: list from {'x','y','z'} — which axes to align (default all)
        mode: 'center' (default) | 'min' | 'max'
              center: bbox centers match
              min:    aligns lower bbox edges
              max:    aligns upper bbox edges
    """


@_proxy()
async def array_around(
    object: str,
    count: int = 6,
    radius: float = 2.0,
    center: list[float] | None = None,
    axis: str = "z",
    face_center: bool = True,
    name_prefix: str | None = None,
) -> dict[str, Any]:
    """Duplicate an object N times in a circle around a center.

    Useful for: chair legs, tree branches, columns, fence posts, planet rings.

    Args:
        object: name of object to duplicate
        count: number of copies including the original (default 6)
        radius: circle radius (default 2.0)
        center: [x, y, z] world center (default origin)
        axis: 'z' (default) | 'x' | 'y' — rotation axis
        face_center: rotate copies to face the center (default True)
        name_prefix: prefix for new objects (default '<original>_arr')
    """


@_proxy()
async def distribute(
    objects: list[str],
    start: list[float] | None = None,
    end: list[float] | None = None,
) -> dict[str, Any]:
    """Evenly distribute objects along a straight line between two points.

    Args:
        objects: list of object names (>=2). First stays at start, last at end.
        start: [x, y, z] start point (default first object's current position)
        end: [x, y, z] end point (default last object's current position)
    """


@_proxy()
async def look_at(
    object: str,
    target: str | None = None,
    point: list[float] | None = None,
    track_axis: str = "NEG_Z",
    up_axis: str = "Y",
) -> dict[str, Any]:
    """Rotate an object so it faces a target (or arbitrary point).

    Defaults match camera/light convention: -Z axis points at target, Y is up.

    Args:
        object: name of object to rotate (typically a camera or light)
        target: name of target object — provide either this OR `point`
        point: [x, y, z] world point to look at
        track_axis: 'NEG_Z' (default) | 'POS_Z' | 'NEG_X' | 'POS_X' | 'NEG_Y' | 'POS_Y'
        up_axis: 'Y' (default) | 'X' | 'Z'
    """


@_proxy()
async def bbox_info(object: str) -> dict[str, Any]:
    """Return world-space axis-aligned bounding box of an object.

    Returns: {min:[x,y,z], max:[x,y,z], size:[w,d,h], center:[x,y,z]}
    """


# ===========================================================================
# v2.5: selection / object lifecycle / collections
# ===========================================================================


@_proxy()
async def select(
    objects: list[str],
    additive: bool = False,
    active: str | None = None,
) -> dict[str, Any]:
    """Select one or more objects by name.

    Args:
        objects: list of object names to select
        additive: if False (default), deselects everything else first
        active: which one to make active (default: last in list)

    Use this BEFORE calling operators that depend on selection
    (object.duplicate, object.join, object.shade_smooth, uv.unwrap, ...).
    Or just pass `select=[...]` directly to `call_operator` to do it atomically.
    """


@_proxy()
async def deselect_all() -> dict[str, Any]:
    """Deselect every object."""


@_proxy()
async def set_active(object: str, select: bool = True) -> dict[str, Any]:
    """Make an object the active one (with or without selecting it)."""


@_proxy()
async def select_all(type: str | None = None) -> dict[str, Any]:
    """Select all objects, optionally filtered by type.

    Args:
        type: 'MESH' | 'LIGHT' | 'CAMERA' | 'EMPTY' | 'CURVE' | 'ARMATURE' | ...
              (default: select everything)
    """


@_proxy()
async def duplicate_object(
    object: str,
    linked: bool = False,
    name: str | None = None,
    location_offset: list[float] | None = None,
    collection: str | None = None,
) -> dict[str, Any]:
    """Duplicate an object cleanly (no selection juggling required).

    Args:
        object: name of object to duplicate
        linked: share mesh/curve data with the original (default False)
        name: name for the new object (default '<orig>.copy')
        location_offset: [dx,dy,dz] from the original (default [0,0,0])
        collection: collection to link new object to (default: same as original)
    """


@_proxy()
async def set_visibility(
    object: str | None = None,
    objects: list[str] | None = None,
    viewport: bool | None = None,
    render: bool | None = None,
    selectable: bool | None = None,
    show_in_viewport: bool | None = None,
) -> dict[str, Any]:
    """Toggle visibility flags on object(s) without touching set_property.

    Pass either `object` (single) or `objects` (batch). Each flag is optional
    — pass only the ones you want to change (None = leave unchanged).

    Flags:
        viewport: bool — viewport visibility (monitor icon in outliner)
        render: bool — render visibility (camera icon)
        selectable: bool — can be selected (cursor icon)
        show_in_viewport: bool — temporary hide (eye icon)

    `True` means visible / selectable, `False` means hidden / not selectable.
    """


@_proxy()
async def set_parent(
    parent: str,
    child: str | None = None,
    children: list[str] | None = None,
    keep_transform: bool = True,
    type: str = "OBJECT",
    bone: str | None = None,
) -> dict[str, Any]:
    """Parent one or more objects to a target.

    Args:
        parent: name of parent object
        child: single child name — OR
        children: list of child names
        keep_transform: preserve world transform (default True)
        type: 'OBJECT' (default) | 'BONE' | 'VERTEX' | 'ARMATURE'
        bone: bone name (when type='BONE')
    """


@_proxy()
async def clear_parent(
    object: str | None = None,
    objects: list[str] | None = None,
    keep_transform: bool = True,
) -> dict[str, Any]:
    """Unparent one or more objects."""


@_proxy()
async def create_collection(
    name: str,
    parent: str | None = None,
) -> dict[str, Any]:
    """Create a new collection.

    Args:
        name: collection name (must be unique)
        parent: parent collection (default: scene root)
    """


@_proxy()
async def delete_collection(
    name: str,
    unlink_objects: bool = False,
) -> dict[str, Any]:
    """Delete a collection.

    Args:
        name: collection to delete
        unlink_objects: if True, also remove member objects (only if they have
                        no other collections). Default False (just unlinks).
    """


@_proxy()
async def move_to_collection(
    collection: str,
    object: str | None = None,
    objects: list[str] | None = None,
    unlink_others: bool = True,
) -> dict[str, Any]:
    """Move object(s) into a collection.

    Args:
        collection: destination collection name
        object: single object name — OR
        objects: list of object names
        unlink_others: remove from previous collections (default True)
    """


@_proxy()
async def list_collections() -> dict[str, Any]:
    """List all collections with member counts."""


@_proxy()
async def set_property(path: str, value: Any) -> dict[str, Any]:
    """Set any RNA property by Python-style path (parsed safely, no eval).

    Examples:
        set_property("bpy.data.scenes['Scene'].cycles.samples", 256)
        set_property("bpy.data.scenes['Scene'].render.resolution_x", 1920)
        set_property("bpy.data.objects['Cube'].location", [1, 0, 2])
        set_property("bpy.data.scenes['Scene'].view_settings.view_transform", "AgX")
    """


@_proxy()
async def get_property(path: str) -> dict[str, Any]:
    """Read any RNA property by Python-style path (read-only mirror of set_property)."""


@_tool()
async def call_operator(
    operator: str,
    kwargs: dict[str, Any] | None = None,
    execution_context: str | None = None,
    select: list[str] | None = None,
    active: str | None = None,
    deselect_others: bool = True,
) -> dict[str, Any]:
    """Invoke any allowed bpy.ops operator.

    Allowed prefixes (default policy): mesh.*, object.*, material.*, scene.*,
    render.*, image.*, node.*, transform.*, view3d.*, curve.*, armature.*,
    pose.*, uv.*, particle.*, collection.*, world.*, anim.*, action.*,
    graph.*, nla.*, modifier.*, geometry.*

    Always denied: wm.quit_blender, wm.read_factory_settings, wm.open_mainfile,
    wm.save_mainfile, preferences.*, etc.

    Many bpy.ops operators (object.duplicate, object.join, object.shade_smooth,
    uv.unwrap, ...) require a specific selection / active object to succeed.
    Pass `select=[names]` and/or `active=name` to set up the context atomically
    BEFORE the operator runs (no separate select call needed). With
    `deselect_others=True` (default), other objects are deselected first.

    Examples:
        call_operator("object.shade_smooth", select=["Cube"])
        call_operator("object.join", select=["A","B","C"], active="A")
        call_operator("object.modifier_apply", {"modifier": "Subdivision"}, active="Cube")
    """
    _get_policy().require("call_operator")
    args: dict[str, Any] = {"operator": operator, "kwargs": kwargs or {}}
    if execution_context:
        args["execution_context"] = execution_context
    if select is not None:
        args["select"] = select
    if active is not None:
        args["active"] = active
    args["deselect_others"] = bool(deselect_others)
    return await _call_dict("call_operator", args)


# ===========================================================================
# Mesh + scene basics (kept; batch-aware)
# ===========================================================================


@_tool()
async def create_primitive(
    kind: str | list[dict[str, Any]] | None = None,
    name: str | None = None,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
    size: float = 1.0,
) -> dict[str, Any]:
    """Create one or many mesh primitives.

    kind: 'cube'|'sphere'|'cylinder'|'plane'|'cone'|'torus'|'monkey'|
          'ico_sphere'|'circle'|'grid'.

    Pass kind as a list of spec dicts to batch-create primitives in one undo step.
    """
    _get_policy().require("create_primitive")
    if isinstance(kind, list):
        return await _call_dict("mesh.create_primitive", {"items": kind})
    args: dict[str, Any] = {"kind": kind, "size": size}
    if name is not None:
        args["name"] = name
    if location is not None:
        args["location"] = location
    if rotation is not None:
        args["rotation"] = rotation
    return await _call_dict("mesh.create_primitive", args)


@_tool()
async def set_transform(
    object: str | list[dict[str, Any]] | None = None,
    location: list[float] | None = None,
    rotation_euler: list[float] | None = None,
    scale: list[float] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Set location/rotation/scale on one or many objects.

    Pass ``dry_run=True`` to preview the change without applying it.
    """
    _get_policy().require("set_transform")
    if isinstance(object, list):
        return await _call_dict("object.transform", {"items": object}, dry_run=dry_run)
    args: dict[str, Any] = {"object": object}
    if location is not None:
        args["location"] = location
    if rotation_euler is not None:
        args["rotation_euler"] = rotation_euler
    if scale is not None:
        args["scale"] = scale
    return await _call_dict("object.transform", args, dry_run=dry_run)


@_tool()
async def delete_object(
    object: str | list[dict[str, Any]] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete one or many objects.

    Pass ``dry_run=True`` to preview the deletion without applying it; the
    approval gate is also skipped in that case (no destructive action will
    occur).
    """
    policy = _get_policy()
    policy.require("delete_object")
    if not dry_run and policy.confirm_required_for("delete_object"):
        from .approval import request_approval

        outcome = await request_approval(
            tool="delete_object",
            args={"object": object},
        )
        if not outcome.available:
            return {
                "error": "CONFIRM_REQUIRED",
                "message": "delete_object requires user confirmation but no approval endpoint is available. Install/start the Blender MCP VS Code extension.",
                "detail": outcome.error,
            }
        if not outcome.approved:
            return {
                "error": "CONFIRM_DENIED",
                "message": "User rejected delete_object via approval prompt.",
            }
    if isinstance(object, list):
        return await _call_dict("object.delete", {"items": object}, dry_run=dry_run)
    return await _call_dict("object.delete", {"object": object}, dry_run=dry_run)


# ===========================================================================
# P4: Composition
# ===========================================================================


@_tool()
async def create_objects(specs: list[dict[str, Any]], dry_run: bool = False) -> dict[str, Any]:
    """Build many objects atomically (one undo step) from a spec list.

    Pass ``dry_run=True`` to preview the planned creations (with polygon
    estimates) without touching the scene. Polygon-budget enforcement still
    runs in dry-run mode so you see the same denials you'd see for real.

    Each spec:
      {
        "kind": "cube" | "sphere" | "cylinder" | ... | "light" | "camera" | "empty",
        "name": str?,
        "location": [x,y,z]?, "rotation": [x,y,z]?, "scale": [x,y,z]?,
        "size": float?,
        "material": str?,                 # mesh objects only
        "collection": str?,               # creates collection if missing
        "parent": str?,
        "modifiers": [{"type":"BEVEL","name":"B","properties":{...}}, ...]?,
        "properties": {rna_attr: value, ...}?,
        # light:    "light_type":"POINT|SUN|SPOT|AREA","energy":..,"color":..
        # camera:   "lens":..,"sensor_width":..,"dof":{...},"set_active":bool
        # empty:    "empty_type":"PLAIN_AXES|ARROWS|...","empty_display_size":..
      }
    """
    policy = _get_policy()
    policy.require("create_objects")
    from .policy import estimate_polys

    estimated = estimate_polys(specs)
    if estimated > policy.max_polys:
        return {
            "error": "POLICY_DENIED",
            "code": "POLY_BUDGET_EXCEEDED",
            "message": (
                f"Estimated {estimated} polygons exceeds max_polys "
                f"({policy.max_polys}). Reduce subdivision levels, array counts, "
                "or split into smaller transactions."
            ),
            "estimated_polys": estimated,
            "max_polys": policy.max_polys,
        }
    return await _call_dict(
        "create_objects", {"specs": specs}, timeout=60.0, dry_run=dry_run,
    )

@_tool()
async def transaction(steps: list[dict[str, Any]], label: str | None = None) -> dict[str, Any]:
    """Atomically run a list of {tool, args} steps under one undo checkpoint.

    On any step failure: undo once and return failure info. On success: keep
    a single combined undo entry.

    Example:
        transaction([
          {"tool": "create_objects", "args": {"specs": [...]}},
          {"tool": "build_nodes", "args": {"target": "material:Gold!", "graph": {...}}},
          {"tool": "assign_material", "args": {"object": "Sphere", "material": "Gold"}},
        ], label="setup-shot-A")
    """
    policy = _get_policy()
    policy.require("transaction")
    # Apply the same poly budget to nested create_objects steps so a model
    # can't bypass the cap by wrapping a huge spec in a transaction.
    from .policy import estimate_polys

    nested_specs: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("tool") == "create_objects":
            sargs = step.get("args") or {}
            specs = sargs.get("specs")
            if isinstance(specs, list):
                nested_specs.extend(specs)
    if nested_specs:
        estimated = estimate_polys(nested_specs)
        if estimated > policy.max_polys:
            return {
                "error": "POLICY_DENIED",
                "code": "POLY_BUDGET_EXCEEDED",
                "message": (
                    f"Transaction estimated {estimated} polygons across nested "
                    f"create_objects steps; exceeds max_polys ({policy.max_polys})."
                ),
                "estimated_polys": estimated,
                "max_polys": policy.max_polys,
            }
    args: dict[str, Any] = {"steps": steps}
    if label:
        args["label"] = label
    return await _call_dict("transaction", args, timeout=120.0)


@_tool()
async def apply_to_selection(
    tool: str,
    args: dict[str, Any] | None = None,
    name_key: str = "object",
) -> dict[str, Any]:
    """Run a tool against each currently selected object.

    Example:
        apply_to_selection("add_modifier",
                           {"type": "BEVEL", "properties": {"width": 0.02}})
    """
    _get_policy().require("apply_to_selection")
    return await _call_dict(
        "apply_to_selection",
        {"tool": tool, "args": args or {}, "name_key": name_key},
    )


# ===========================================================================
# Animation (kept)
# ===========================================================================


@_tool()
async def set_keyframe(
    object_name: str | list[dict[str, Any]] | None = None,
    data_path: str | None = None,
    frame: int | None = None,
    value: Any = None,
    index: int = -1,
) -> dict[str, Any]:
    """Insert a keyframe on an object property. Pass object_name as a list
    of spec dicts to batch-insert."""
    _get_policy().require("set_keyframe")
    if isinstance(object_name, list):
        return await _call_dict("animation.keyframe", {"items": object_name})
    args: dict[str, Any] = {"object_name": object_name, "data_path": data_path, "frame": frame}
    if value is not None:
        args["value"] = value
    if index != -1:
        args["index"] = index
    return await _call_dict("animation.keyframe", args)


# ===========================================================================
# P5: Asset library
# ===========================================================================


@_proxy(paths=("path",), timeout=120.0)
async def import_asset(
    path: str,
    format: str | None = None,
    collection: str | None = None,
) -> dict[str, Any]:
    """Import an asset file (.blend/.glb/.gltf/.fbx/.obj/.usd/.stl/.ply/
    .abc/.x3d/.dae/.svg). Path is jail-checked against policy.allowed_roots."""


@_proxy(paths=("path",), timeout=60.0)
async def link_blend(
    path: str,
    datablocks: list[dict[str, Any]],
    link: bool = True,
) -> dict[str, Any]:
    """Link or append datablocks from another .blend file.

    Args:
        path: .blend path (jail-checked).
        datablocks: [{"type":"Object","name":"Tree_01"}, ...]
        link: True to link (live), False to append (copy).
    """


@_proxy(paths=("directory",), timeout=60.0)
async def list_assets(directory: str, recursive: bool = False) -> dict[str, Any]:
    """Enumerate importable asset files in a directory (jail-checked)."""


# ===========================================================================
# P6: Visual feedback
# ===========================================================================


@_tool()
async def viewport_screenshot(
    width: int = 1024,
    height: int = 1024,
    view_camera: str | None = None,
    shading: str | None = None,
    show_overlays: bool = False,
    transport: str = "base64",
) -> dict[str, Any]:
    """Capture the viewport as a PNG.

    Args:
        width / height: 1..4096.
        view_camera: name of a camera object to render from (optional).
        shading: 'WIREFRAME'|'SOLID'|'MATERIAL'|'RENDERED' (optional).
        show_overlays: include grid/gizmos.
        transport: ``"base64"`` (default, inlined in the response) or
            ``"file"`` (PNG written to %LOCALAPPDATA%\\BlenderMCP\\renders\\
            and returned as ``image_path``). Use ``"file"`` for large or
            frequent renders to avoid double-encoding overhead — the VS Code
            extension prefers this. Stdio-only MCP clients (Claude Desktop)
            should stick with the default ``"base64"``.

    Returns:
        Always: ``{mime, size_bytes, image_sha256, width, height}``.
        ``transport="base64"`` adds ``image_base64``.
        ``transport="file"`` adds ``image_path``.
    """
    policy = _get_policy()
    policy.require("viewport_screenshot")
    policy.check_resolution(width, height)
    if transport not in ("base64", "file"):
        raise ValueError("transport must be 'base64' or 'file'")
    args: dict[str, Any] = {
        "w": width, "h": height, "show_overlays": show_overlays,
        "transport": transport,
    }
    if view_camera:
        args["view_camera"] = view_camera
    if shading:
        args["shading"] = shading
    return await _call_dict("render.viewport_screenshot", args, timeout=60.0)


@_tool()
async def render_region(
    x: int,
    y: int,
    w: int,
    h: int,
    samples: int = 32,
    engine: str | None = None,
    camera: str | None = None,
    transport: str = "base64",
) -> dict[str, Any]:
    """Render a focused region of the scene with the engine (Cycles/EEVEE).

    Use for cheap iterative feedback on a specific area without committing
    to a full-scene render. See ``viewport_screenshot`` for ``transport``
    semantics.
    """
    policy = _get_policy()
    policy.require("render_region")
    if transport not in ("base64", "file"):
        raise ValueError("transport must be 'base64' or 'file'")
    args: dict[str, Any] = {
        "x": x, "y": y, "w": w, "h": h, "samples": samples,
        "transport": transport,
    }
    if engine:
        args["engine"] = engine
    if camera:
        args["camera"] = camera
    return await _call_dict("render.region", args, timeout=300.0)


@_tool()
async def bake_preview(
    material: str,
    w: int = 256,
    h: int = 256,
    transport: str = "base64",
) -> dict[str, Any]:
    """Render a quick preview of a material on a temporary plane.

    See ``viewport_screenshot`` for ``transport`` semantics.
    """
    policy = _get_policy()
    policy.require("bake_preview")
    if transport not in ("base64", "file"):
        raise ValueError("transport must be 'base64' or 'file'")
    return await _call_dict(
        "render.bake_preview",
        {"material": material, "w": w, "h": h, "transport": transport},
        timeout=120.0,
    )


@_proxy()
async def scene_diff(snapshot_id: str | None = None) -> dict[str, Any]:
    """Snapshot/diff scene state.

    First call (no snapshot_id, or with a new id): returns baseline marker.
    Subsequent calls with the same snapshot_id: returns added/removed/modified.

    Tracks per-object: transform, modifier list, material assignments,
    visibility, parent, collection, mesh stats.
    """


# ===========================================================================
# Execute Python (loosened in v2; controlled by add-on exec_mode)
# ===========================================================================


@_tool()
async def execute_python(
    code: str,
    timeout: float = 10.0,
    mode: str | None = None,
) -> dict[str, Any]:
    """Execute Python in the Blender add-on sandbox.

    Modes (set via add-on prefs or per-call):
      - 'safe' (default): AST validator + restricted builtins. Allowed
         imports include bpy, mathutils, bmesh, math, pathlib, io, json,
         re, colorsys, random, itertools, functools, collections, ...
      - 'trusted': no validation, full Python (auth token still required).

    Returns {executed, mode, lines, result_preview} on success or
    {executed: False, error, error_type, traceback, failed_line, suggestion}.
    """
    policy = _get_policy()
    policy.require("execute_python")
    if policy.confirm_required_for("execute_python"):
        from .approval import request_approval

        outcome = await request_approval(
            tool="execute_python",
            args={"timeout": timeout, "mode": mode, "code_len": len(code)},
            code=code,
        )
        if not outcome.available:
            return {
                "error": "CONFIRM_REQUIRED",
                "message": "execute_python requires user confirmation but no approval endpoint is available. Install/start the Blender MCP VS Code extension.",
                "detail": outcome.error,
            }
        if not outcome.approved:
            return {
                "error": "CONFIRM_DENIED",
                "message": "User rejected execute_python via approval prompt.",
            }
    args: dict[str, Any] = {"code": code, "timeout": timeout}
    if mode:
        args["mode"] = mode
    return await _call_dict("exec.python", args, timeout=max(timeout + 5, 35))


# ===========================================================================
# Checkpoints (persistent .blend snapshots)
# ===========================================================================


@_proxy(op="checkpoint.create", timeout=60.0)
async def create_checkpoint(label: str | None = None, note: str | None = None) -> dict[str, Any]:
    """Save a copy of the current .blend as a recovery checkpoint.

    Stored under %LOCALAPPDATA%/BlenderMCP/checkpoints/<sha(filepath)>/...
    Old checkpoints beyond the keep-limit are pruned automatically.
    """


@_proxy(op="checkpoint.list")
async def list_checkpoints(source: str | None = None) -> dict[str, Any]:
    """List checkpoints (newest first) for the current .blend or a given path."""


@_tool()
async def restore_checkpoint(blend_path: str) -> dict[str, Any]:
    """Restore a previously saved checkpoint. Requires user approval.

    The checkpoint path is jail-checked against ``policy.allowed_roots``
    before approval is requested.
    """
    policy = _get_policy()
    policy.require("restore_checkpoint")
    resolved = str(policy.validate_path(blend_path))
    from .approval import request_approval

    outcome = await request_approval(
        tool="restore_checkpoint",
        args={"blend_path": resolved},
    )
    if not outcome.available:
        return {
            "error": "CONFIRM_REQUIRED",
            "message": "restore_checkpoint requires user confirmation but no approval endpoint is available.",
            "detail": outcome.error,
        }
    if not outcome.approved:
        return {
            "error": "CONFIRM_DENIED",
            "message": "User rejected restore_checkpoint via approval prompt.",
        }
    return await _call_dict("checkpoint.restore", {"blend_path": resolved}, timeout=60.0)


# Register all path-taking parameters of manual (non-_proxy) wrappers so
# the contract test in tests/test_path_jail_contract.py sees them.
_register_path_args("restore_checkpoint", "blend_path")


# ===========================================================================
# Geometry Nodes (v2.2)
# ===========================================================================


@_proxy(op="geonodes.create_modifier", pass_dry_run=True)
async def geonodes_create_modifier(
    object: str,
    group: str | None = None,
    name: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Add a Geometry Nodes modifier to ``object``.

    If ``group`` is given, link that existing GeometryNodeTree; otherwise a
    new empty group is created and assigned. Use ``geonodes_describe_group``
    to discover its interface, then ``geonodes_set_input`` to drive it.
    """


@_proxy(op="geonodes.describe_group")
async def geonodes_describe_group(name: str) -> dict[str, Any]:
    """Return the interface (inputs/outputs) of a Geometry Nodes group.

    Use the returned ``identifier`` field as the ``input`` argument to
    ``geonodes_set_input`` for unambiguous targeting.
    """


@_proxy(op="geonodes.set_input", pass_dry_run=True)
async def geonodes_set_input(
    object: str,
    input: str | int,
    value: Any,
    modifier: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Set a socket value on a Geometry Nodes modifier.

    ``input`` accepts the socket's name, identifier (e.g. ``"Input_2"``), or
    integer index. For object/material/collection/image/texture sockets,
    pass the datablock NAME as ``value`` (string).
    """


@_proxy(op="geonodes.animate_input", pass_dry_run=True)
async def geonodes_animate_input(
    object: str,
    input: str | int,
    keyframes: list[dict[str, Any]],
    modifier: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Insert keyframes on a Geometry Nodes modifier socket.

    ``keyframes`` is a list of ``{"frame": int, "value": ...}`` dicts.
    """


@_proxy(op="geonodes.create_group", pass_dry_run=True)
async def geonodes_create_group(
    name: str,
    inputs: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create an empty Geometry Nodes group with declared interface sockets.

    ``inputs`` / ``outputs`` are lists of ``{"name", "socket_type",
    "default_value"?}``. ``socket_type`` defaults to ``"NodeSocketGeometry"``.

    Build the actual node graph with the existing ``build_nodes`` tool using
    ``target="node_group:Name"``.
    """


@_proxy(op="geonodes.realize", pass_dry_run=True)
async def geonodes_realize(
    object: str,
    modifier: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply (realize) a Geometry Nodes modifier — DESTRUCTIVE.

    Bakes the procedural output into the mesh data; the modifier is removed.
    """


@_proxy(op="geonodes.list_presets")
async def geonodes_list_presets() -> dict[str, Any]:
    """List bundled Geometry Nodes presets (templates).

    Each preset is a JSON description of a node group: interface (inputs/
    outputs) plus a graph (nodes + links). To use one, fetch it with
    ``geonodes_get_preset``, then construct the group with
    ``geonodes_create_group`` + ``build_nodes`` (target=``node_group:Name``)
    and apply via ``geonodes_create_modifier`` + ``geonodes_set_input``.
    """


@_proxy(op="geonodes.get_preset")
async def geonodes_get_preset(name: str) -> dict[str, Any]:
    """Return the full JSON of a Geometry Nodes preset by name."""


@_proxy(op="geonodes.apply_preset", pass_dry_run=True)
async def geonodes_apply_preset(
    preset: str,
    object: str | None = None,
    group: str | None = None,
    modifier: str | None = None,
    replace: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Instantiate a Geometry Nodes preset as a real node group.

    Builds the node group described by ``preset`` (use ``geonodes_list_presets``
    to discover names) and optionally attaches it as a NODES modifier on
    ``object``. Honours dry-run.

    Args:
        preset:   preset name (required), e.g. "scatter-on-surface".
        object:   if provided, attach the new group as a modifier here.
        group:    override the default group name (suffixed if it already
                  exists in bpy.data.node_groups, unless ``replace=True``).
        modifier: modifier name on the target object (default GeometryNodes).
        replace:  when True, delete an existing group with the same name first.
    """


# ===========================================================================
# Entry point
# ===========================================================================


def main() -> None:
    """Entry point for the MCP server."""
    import atexit
    logging.basicConfig(
        level=logging.INFO, format="%(name)s %(levelname)s %(message)s"
    )
    # Phase 2: persist any pending describe_api entries on graceful shutdown
    # so a clean Ctrl-C doesn't drop the last <flush_threshold entries.
    atexit.register(_describe_api_cache.flush)
    mcp.run()


if __name__ == "__main__":
    main()

# ===========================================================================
# v3.0 Tier-1 capability batch
# ===========================================================================


# --- Data-block creators -----------------------------------------------------


@_proxy()
async def create_light(
    kind: str,
    name: str | None = None,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
    color: list[float] | None = None,
    energy: float | None = None,
    size: float | None = None,
    spot_size: float | None = None,
    spot_blend: float | None = None,
    shape: str | None = None,
) -> dict[str, Any]:
    """Create a light datablock.

    `kind`: "point" | "sun" | "spot" | "area".
    Energy units: Watts for POINT/SPOT/AREA; irradiance W/m^2 for SUN.
    `size`: radius (POINT/SPOT), side length (AREA), or angle in radians (SUN).
    """


@_proxy()
async def create_camera(
    name: str | None = None,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
    type: str | None = None,
    lens: float | None = None,
    ortho_scale: float | None = None,
    sensor_width: float | None = None,
    sensor_height: float | None = None,
    clip_start: float | None = None,
    clip_end: float | None = None,
    set_active: bool = False,
) -> dict[str, Any]:
    """Create a camera datablock; optionally make it the active scene camera."""


@_proxy()
async def set_active_camera(name: str) -> dict[str, Any]:
    """Make the named camera object the active scene camera."""


@_proxy()
async def create_empty(
    name: str | None = None,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
    scale: list[float] | None = None,
    display: str = "PLAIN_AXES",
    size: float = 1.0,
) -> dict[str, Any]:
    """Create an empty (controller / parent) object.

    `display`: PLAIN_AXES | ARROWS | SINGLE_ARROW | CIRCLE | CUBE | SPHERE | CONE | IMAGE.
    """


@_proxy()
async def create_text(
    body: str = "Text",
    name: str | None = None,
    size: float = 1.0,
    extrude: float = 0.0,
    bevel_depth: float = 0.0,
    align_x: str | None = None,
    align_y: str | None = None,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
) -> dict[str, Any]:
    """Create a 3D text object."""


@_proxy()
async def create_curve(
    points: list[list[float]],
    kind: str = "bezier",
    name: str | None = None,
    closed: bool = False,
    bevel_depth: float = 0.0,
    bevel_resolution: int = 4,
    fill_mode: str | None = None,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
) -> dict[str, Any]:
    """Create a curve from a list of [x,y,z] control points.

    `kind`: "bezier" | "nurbs" | "poly". Set `bevel_depth` > 0 to give thickness.
    """


@_proxy()
async def create_armature(
    name: str | None = None,
    location: list[float] | None = None,
    bones: list[dict[str, Any]] | None = None,
    display_type: str | None = None,
    show_in_front: bool | None = None,
) -> dict[str, Any]:
    """Create an armature with optional initial bones.

    Each bone dict: {name, head:[x,y,z], tail:[x,y,z], parent?, use_connect?, roll?}.
    Bones reference parents by name; parents must appear earlier in the list.
    """


@_proxy(paths=("path",))
async def load_image(
    path: str,
    name: str | None = None,
    check_existing: bool = True,
    pack: bool = False,
    alpha_mode: str | None = None,
    colorspace: str | None = None,
) -> dict[str, Any]:
    """Load an image from disk into bpy.data.images.

    Use `colorspace="Non-Color"` for normal/roughness/metallic data textures.
    Path is jail-checked against policy.allowed_roots.
    """


@_proxy()
async def create_image(
    name: str,
    width: int = 1024,
    height: int = 1024,
    color: list[float] | None = None,
    alpha: bool = True,
    float: bool = False,
    is_data: bool = False,
) -> dict[str, Any]:
    """Create a blank image datablock (e.g. for procedural baking)."""


# --- Mode + edit-mode mesh DSL + read-only mesh inspection -------------------


@_proxy()
async def set_mode(mode: str, object: str | None = None) -> dict[str, Any]:
    """Switch interaction mode atomically with compatibility validation.

    Valid modes depend on the object type. e.g. EDIT requires MESH/CURVE/...,
    POSE requires ARMATURE. Returns a structured error if the requested mode
    is not valid for the (current or specified) active object.
    """


@_proxy(timeout=60.0)
async def mesh_edit(
    object: str,
    ops: list[dict[str, Any]],
    validate: bool = True,
) -> dict[str, Any]:
    """Apply a sequence of bmesh edit operations to a mesh in one undo step.

    Each op is a dict like:
        {"op": "extrude_faces", "faces": [0,1,2], "offset": [0,0,1]}
        {"op": "inset_faces",   "faces": [3], "thickness": 0.1, "depth": 0.0}
        {"op": "bevel_edges",   "edges": [0,1], "offset": 0.05, "segments": 3}
        {"op": "subdivide",     "edges": [4,5,6], "cuts": 2}
        {"op": "merge_verts",   "verts": [0,1,2], "mode": "CENTER"}
        {"op": "remove_doubles","verts": [...], "distance": 0.0001}
        {"op": "delete_faces"|"delete_edges"|"delete_verts", "...": [...] }
        {"op": "dissolve_faces"|"dissolve_edges"|"dissolve_verts", ...}
        {"op": "bridge_loops",  "edges_a": [...], "edges_b": [...]}
        {"op": "fill",          "edges": [...]}
        {"op": "triangulate"}, {"op": "recalc_normals", "inside": false}
        {"op": "flip_normals"}, {"op": "smooth_verts", "verts":[...], "factor":0.5}
        {"op": "transform_verts", "verts":[...], "translate":[..]|"scale":[..] }
        {"op": "loop_cut", "edge": <index>, "cuts": 1}

    Bypasses edit-mode entirely — uses bmesh directly.
    Returns per-op results plus aggregate before/after counts.
    """


@_proxy()
async def mesh_read(
    object: str,
    what: list[str] | None = None,
    start: int = 0,
    limit: int = 1000,
    uv_layer: str | None = None,
) -> dict[str, Any]:
    """Read mesh geometry with bounded slicing (max 10000 elements per call).

    `what`: any subset of ["vertices", "edges", "faces", "normals", "loop_uvs"].
    """


# --- Constraints -------------------------------------------------------------


@_proxy()
async def add_constraint(
    object: str,
    type: str,
    name: str | None = None,
    bone: str | None = None,
    target: str | None = None,
    subtarget: str | None = None,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a constraint to an object or pose bone.

    Common types: COPY_LOCATION, COPY_ROTATION, COPY_SCALE, COPY_TRANSFORMS,
    LIMIT_LOCATION, LIMIT_ROTATION, LIMIT_SCALE, TRACK_TO, DAMPED_TRACK,
    LOCKED_TRACK, IK, FOLLOW_PATH, CHILD_OF, ARMATURE, SHRINKWRAP.

    Pass `bone` to add a pose-bone constraint instead of an object constraint.
    Use `describe_api("CopyLocationConstraint")` etc. for property names.
    """


@_proxy()
async def remove_constraint(
    object: str, name: str, bone: str | None = None,
) -> dict[str, Any]:
    """Remove a constraint by name from an object or pose bone."""


@_proxy()
async def list_constraints(
    object: str, bone: str | None = None,
) -> dict[str, Any]:
    """List constraints on an object or pose bone."""


# --- Vertex groups -----------------------------------------------------------


@_proxy()
async def create_vertex_group(object: str, name: str) -> dict[str, Any]:
    """Create a named vertex group on a mesh."""


@_proxy()
async def remove_vertex_group(object: str, name: str) -> dict[str, Any]:
    """Remove a vertex group by name."""


@_proxy()
async def list_vertex_groups(object: str) -> dict[str, Any]:
    """List vertex groups on a mesh."""


@_proxy()
async def set_vertex_weights(
    object: str,
    group: str,
    indices: list[int],
    weights: list[float] | float,
    type: str = "REPLACE",
) -> dict[str, Any]:
    """Set per-vertex weights on a vertex group.

    `weights` may be a parallel list (one per index) or a single float
    applied to every index. `type` is REPLACE (default), ADD, or SUBTRACT.
    """


# --- Shape keys --------------------------------------------------------------


@_proxy()
async def add_shape_key(
    object: str,
    name: str = "Key",
    from_mix: bool = False,
    value: float = 0.0,
    slider_min: float | None = None,
    slider_max: float | None = None,
) -> dict[str, Any]:
    """Add a shape key (the Basis is auto-created on first call)."""


@_proxy()
async def set_shape_key_value(
    object: str, name: str, value: float,
) -> dict[str, Any]:
    """Set the influence value of an existing shape key."""


@_proxy()
async def remove_shape_key(
    object: str, name: str | None = None, all: bool = False,
) -> dict[str, Any]:
    """Remove a shape key by name (or all=True to clear every key)."""


@_proxy()
async def list_shape_keys(object: str) -> dict[str, Any]:
    """List shape keys on an object."""

