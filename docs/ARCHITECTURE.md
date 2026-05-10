# Architecture — Blender MCP Bridge

## Overview

The Blender MCP Bridge is a three-component system that lets MCP-compatible AI
assistants (Copilot Chat, Claude Desktop, Cursor, Cline, Continue) inspect and
modify a running Blender scene.

## Components

```
┌──────────────────────────┐       MCP (stdio/JSON-RPC)      ┌───────────────────────────┐
│  AI Client               │ ──────────────────────────────► │   mcp_server/             │
│  (Copilot / Claude /     │ ◄────────────────────────────── │   blender_mcp/server.py   │
│   Cursor / Cline)        │                                  │   - tool registry          │
└──────────┬───────────────┘                                  │   - schema validation      │
           │ optional vscode ext                              │   - permission gate        │
           ▼                                                  │   - WS client to Blender   │
┌──────────────────────────┐                                  └─────────────┬─────────────┘
│ vscode_extension/        │                                                │
│  - approval webview      │                                                │ WebSocket
│  - viewport preview tab  │                                                │ ws://127.0.0.1:9876
│  - output channel        │                                                │ (loopback only, token auth)
└──────────────────────────┘                                                │
                                                               ┌────────────▼──────────────┐
                                                               │  blender_addon/            │
                                                               │  __init__.py               │
                                                               │  ┌─ server/ws_server.py    │
                                                               │  │  (asyncio, daemon thrd) │
                                                               │  ├─ server/dispatcher.py   │
                                                               │  ├─ server/main_thread.py  │
                                                               │  │  (bpy.app.timers pump)  │
                                                               │  ├─ capabilities/*.py      │
                                                               │  └─ safety/*.py            │
                                                               └───────────────────────────┘
```

## Data flow (single tool call)

```
1. AI model decides to call tool, e.g. create_primitive(kind="cube")
2. MCP client sends JSON-RPC "tools/call" over stdio to mcp_server
3. mcp_server/blender_mcp/server.py:
   a. Validates args against shared/schemas/command.schema.json
   b. Checks policy (blender_mcp/policy.py)
   c. Calls blender_mcp/blender_client.py.call("mesh.create_primitive", {...})
4. blender_client.py sends WebSocket JSON frame to Blender add-on:
   {"id":"ulid","op":"mesh.create_primitive","args":{...},"auth":"tok_..."}
5. blender_addon/server/ws_server.py receives frame in daemon thread
6. ws_server.py validates auth token, pushes (cmd, future) onto queue.Queue
7. blender_addon/server/main_thread.py pump (bpy.app.timers, 10ms interval):
   a. Dequeues (cmd, future)
   b. Calls bpy.ops.ed.undo_push(message="AI:mesh.create_primitive:ulid")
   c. Routes via server/dispatcher.py → capabilities/mesh.py
   d. mesh.py calls bpy.ops.mesh.primitive_cube_add(...)
   e. Returns result dict {"name":"Cube","polys":6,"vertices":8}
   f. Resolves future with result
8. ws_server.py sends response JSON frame back over WebSocket
9. blender_client.py returns result to server.py
10. server.py returns MCP tool result to AI client
11. AI model sees result, decides next action
```

## Threading model

### Blender main thread
- **Owner of:** all `bpy.*` calls, UI rendering, scene graph
- **Rule:** NEVER call bpy from any other thread
- **Mechanism:** `bpy.app.timers.register(pump_fn, persistent=True)`
- **Pump behavior:** drain `queue.Queue`, yield after 8ms wall-time

### WebSocket daemon thread
- Runs `asyncio.new_event_loop()` in a Python `threading.Thread(daemon=True)`
- Handles WS connections, auth, framing
- Pushes commands onto the shared `queue.Queue`
- Resolves futures via `loop.call_soon_threadsafe`
- NEVER touches bpy

### MCP server (separate process)
- Runs as its own Python process, communicates over stdio with AI client
- Connects to Blender via WebSocket as a client
- Handles tool registration, policy, schema validation
- No bpy dependency

## Thread synchronization

```
                    WS daemon thread                 Main thread
                    ───────────────                  ───────────
                         │                                │
  WS frame received ──►  │                                │
  validate auth       ──►│                                │
  create future       ──►│                                │
  queue.put((cmd,fut))──►│─── queue.Queue ──────────────► │
                         │                                │◄── bpy.app.timers fires
                         │                                │    dequeue (cmd, fut)
                         │                                │    undo_push(...)
                         │                                │    dispatch → capability
                         │                                │    execute bpy calls
                         │                      result ──►│
                         │◄── loop.call_soon_threadsafe ──│    fut.set_result(result)
  await fut completes ──►│                                │
  ws.send(response)   ──►│                                │
                         │                                │
```

## Undo model

### Single operations
Every mutating capability call is wrapped:
```python
bpy.ops.ed.undo_push(message=f"AI:{op}:{cmd_id}")
# ... execute bpy calls ...
```
User can Ctrl-Z to revert the entire AI action in one step.

### Transactions
For multi-step AI plans:
```
begin_transaction(label="build red chair")
  → single undo_push
  create_primitive(kind="cube", name="Seat")
  create_primitive(kind="cube", name="Leg1")
  create_primitive(kind="cube", name="Leg2")
  ...
commit()
  → no additional undo_push; all ops share one checkpoint
```
`rollback()` reverts to the pre-transaction state.

### Checkpoint metadata
Each undo checkpoint is logged:
- `undo_id`: unique identifier
- `op`: operation name
- `timestamp`: ISO 8601
- `object_count_delta`: how many objects were added/removed

## Command format (wire protocol)

All messages are JSON, framed by WebSocket text messages.

### Request
```json
{
  "id": "01HZX...",
  "op": "mesh.create_primitive",
  "args": {"kind": "cube", "location": [0,0,0], "size": 2.0},
  "auth": "tok_...",
  "meta": {"client": "mcp-server/0.1", "user": "copilot"}
}
```

### Response (success)
```json
{
  "id": "01HZX...",
  "ok": true,
  "result": {"name": "Cube.003", "polys": 6, "vertices": 8},
  "elapsed_ms": 12,
  "undo_id": "ckpt_8821"
}
```

### Response (error)
```json
{
  "id": "01HZX...",
  "ok": false,
  "error": {"code": "POLICY_DENIED", "message": "exec_python not allowed"}
}
```

### Streaming event
```json
{"id": "01HZX...", "event": "progress", "pct": 42}
```

## Capability registry

Capabilities are registered in `blender_addon/capabilities/__init__.py`:

```python
OP_REGISTRY: dict[str, Callable] = {}

def register_capability(op: str, fn: Callable):
    OP_REGISTRY[op] = fn
```

Each capability module registers itself on import (see `blender_addon/capabilities/`):

| Module | Registered ops |
|---|---|
| `animation.py` | `animation.keyframe` |
| `assets.py` | `import_asset`, `link_blend`, `list_assets` |
| `checkpoint.py` | `checkpoint.create`, `checkpoint.list`, `checkpoint.restore` |
| `collections.py` | `create_collection`, `delete_collection`, `move_to_collection`, `list_collections` |
| `composer.py` | `create_objects`, `transaction`, `apply_to_selection` |
| `diff.py` | `scene_diff`, `scene_snapshot_clear` |
| `exec_python.py` | `exec.python` |
| `geonodes.py` | `geonodes.create_modifier`, `geonodes.describe_group`, `geonodes.set_input`, `geonodes.animate_input`, `geonodes.create_group`, `geonodes.realize` |
| `geonodes_presets.py` | `geonodes.list_presets`, `geonodes.get_preset`, `geonodes.apply_preset` |
| `mesh.py` | `mesh.create_primitive` |
| `modifier.py` | `modifier.add`, `modifier.remove` |
| `nodes.py` | `build_nodes`, `assign_material` (shader/world/compositor with surgical `remove_nodes`/`remove_links`) |
| `object_ops.py` | `duplicate_object`, `set_visibility`, `set_parent`, `clear_parent` |
| `operator.py` | `call_operator` (with built-in selection setup via `select`/`active`/`deselect_others` args) |
| `properties.py` | `set_property`, `get_property` |
| `query.py` | `query`, `list`, `describe_api`, `audit.read` |
| `render.py` | `render.viewport_screenshot`, `render.region`, `render.bake_preview` |
| `rename.py` | `rename` |
| `scene.py` | `object.transform`, `object.delete` |
| `scene_context.py` | `scene.context` (used by `ping`) |
| `selection.py` | `select`, `deselect_all`, `set_active`, `select_all` |
| `snapshot.py` | `scene.snapshot` |
| `spatial.py` | `place_above`, `align_to`, `array_around`, `distribute`, `look_at`, `bbox_info` |

## Safety layers

### Layer 1: Add-on allowlist (Blender Preferences)
Checkboxes per capability group. Disabled = not registered, AI cannot see it.

### Layer 2: Workspace policy (.blendermcp.json)
```json
{
  "allowed_tools": ["get_scene_info", "create_primitive", "viewport_screenshot"],
  "denied_tools": ["execute_python"],
  "allowed_roots": ["C:/Projects/MyScene"],
  "max_polys": 1000000,
  "max_resolution": 4096,
  "snapshot_threshold": 5,
  "confirm_required": ["execute_python", "delete_object"]
}
```

### Layer 3: Per-call confirmation
For tools in `confirm_required`, the MCP server requests user approval via
the VS Code extension's approval webview before forwarding to Blender.

### Layer 4: AST validation (execute_python only)
`safety/validator.py` parses incoming Python code, walks the AST, and rejects
dangerous patterns (imports of os/sys/subprocess, dunder access, eval/exec).

### Layer 5: Audit log
Every command logged to `%LOCALAPPDATA%\BlenderMCP\audit-YYYY-MM-DD.log`
as append-only JSONL. Fields: ts, op, args_sha256, ok, elapsed_ms, undo_id.

## Performance instrumentation

The MCP server keeps a lightweight, always-on **ring buffer** of recent
calls (capacity 2000) populated by `mcp_server/blender_mcp/perf.py`. Each
`_call(...)` records `op`, wall-clock `ms`, and `ok` flag — exceptions
(BlenderError, PolicyDenied, asyncio.TimeoutError) all count toward the
error-rate. Per-record overhead is ≲1µs and the path is lock-free for
readers, so leaving it on in production is safe.

**Verbose mode** is opt-in via the env flag `BLENDER_MCP_PERF=1`
(also accepts `true|yes|on`, case-insensitive). When verbose, the server
also measures request/response payload sizes (a small JSON encode cost,
hence the gate) and surfaces them through `bytes_in_total` /
`bytes_out_total` in `perf_stats`. Without the flag those fields are 0.

**Reading the stats**: call the `perf_stats` MCP tool from any client.
Optional args: `window_seconds` (only count records newer than N seconds)
and `op` (filter to a single op name). Returns p50 / p95 / p99 / max /
mean ms, count, and error count per op. Use it to spot regressions
before they hit users — e.g. `perf_stats(window_seconds=60, op="viewport_screenshot")`
during a session shows whether screenshots are trending slower.

**Local benchmarks** live in `mcp_server/tests/perf/test_hotpath_bench.py`
and are skipped by default (`-m 'not bench'` in `pyproject.toml`). They
stub the WS layer to isolate server-side cost (proxy plumbing, JSON
shaping, policy gates, perf recording) from network latency. Run with:

```
uv run pytest -m bench --benchmark-only
```

A baseline is saved under `tests/perf/.benchmarks/`. Compare a future
run against it with `--benchmark-compare=0001_baseline`.

### Parallel test runs (Phase 4)

`pytest-xdist` is in the dev extra. The `FakeBlenderServer` fixture binds
to an OS-assigned ephemeral port (`port=0`) so workers don't collide on
a fixed socket. Run the suite in parallel with:

```
uv run pytest -q -n auto      # one worker per CPU
uv run pytest -q -n 4         # explicit worker count
```

On a typical dev box the suite drops from ~10s sequential to ~6.5s with
4 workers (~35% reduction). Parallel runs are not the default — sequential
output is friendlier when debugging a single failure.

### `describe_api` cache (Phase 2)

The `describe_api` MCP tool introspects `bpy.types.X.bl_rna` on the main
Blender thread and is the slowest read-only op (40-200ms uncached). Results
don't change between runs of the same Blender version, so the server keeps
a **versioned on-disk cache** at `%LOCALAPPDATA%\BlenderMCP\api_cache\<version>.json`
(see `mcp_server/blender_mcp/api_cache.py`).

- **In-memory tier**: LRU dict capped at 2000 entries, populated on demand
  from the disk file the first time `ping` (or any `describe_api` call)
  reports the Blender version.
- **Write-through**: a dirty counter triggers a flush every 32 new entries;
  `atexit` flushes any remaining dirty entries on graceful shutdown. Writes
  are atomic (`tempfile` + `os.replace`) so a crash mid-write never leaves
  a half-written JSON.
- **Version-keyed**: switching Blender versions mid-process drops the
  in-memory dict and loads the new file; old version's file is left
  intact on disk.
- **Telemetry**: hit/miss/write counters surface through `perf_stats` under
  `describe_api_cache`.

### Snapshot TTL cache (Phase 3)

The model is instructed to call `ping` first every conversation, and most
turns then issue 1-3 more read-only `query`/`list`/`bbox_info` calls before
mutating the scene. Each used to round-trip to Blender independently. The
snapshot cache (`mcp_server/blender_mcp/snapshot_cache.py`) coalesces them.

- **Scope**: per-process, in-memory only. Each MCP client gets its own
  server, so no cross-client coherence is needed.
- **TTL**: default 200ms, override via `BLENDER_MCP_SNAPSHOT_TTL_MS`. Set
  to 0 to disable entirely.
- **Cacheable ops**: `scene.context`, `scene.snapshot`, `ping`, `query`,
  `list`, `bbox_info`, `list_collections`, `list_constraints`,
  `list_vertex_groups`, `list_shape_keys` — see `_CACHEABLE_OPS` in
  `server.py`.
- **Invalidation**: every mutating op call bumps a `scene_epoch` counter
  that's part of the cache key, so old entries miss without an explicit
  clear. `dry_run=True` mutations don't bump (they didn't change anything).
  `scene.changed` notifications from the add-on (user moves an object in
  the Blender UI) also bump the epoch.
- **Errors not cached**: an op that returns `{"error": ...}` or raises is
  NOT stored — the next caller deserves a fresh attempt.
- **Telemetry**: hit/miss/invalidation counters surface through `perf_stats`
  under `snapshot_cache`. Watch `hit_rate` to decide whether to tune TTL.

## File reference

| Path | Purpose |
|---|---|
| `blender_addon/__init__.py` | Add-on entry point, bl_info, register/unregister |
| `blender_addon/preferences.py` | AddonPreferences: host, port, token, allowlist |
| `blender_addon/ui/panel.py` | N-panel: status, controls, last commands |
| `blender_addon/server/ws_server.py` | WebSocket server (asyncio daemon thread) |
| `blender_addon/server/dispatcher.py` | Routes op → capability function |
| `blender_addon/server/main_thread.py` | bpy.app.timers queue pump |
| `blender_addon/capabilities/*.py` | Individual Blender capabilities |
| `blender_addon/safety/checkpoints.py` | Persistent .blend snapshots (create/list/restore + auto-prune) |
| `blender_addon/safety/validator.py` | AST validator for execute_python |
| `blender_addon/safety/audit_log.py` | JSONL audit logger |
| `blender_addon/vendor/` | Vendored websockets wheel |
| `mcp_server/blender_mcp/server.py` | MCP server entry point, tool definitions |
| `mcp_server/blender_mcp/blender_client.py` | WebSocket client to Blender |
| `mcp_server/blender_mcp/policy.py` | Policy engine (.blendermcp.json) |
| `mcp_server/blender_mcp/tools/*.py` | MCP tool implementations |
| `shared/schemas/*.json` | JSON Schemas (single source of truth) |
| `vscode_extension/src/extension.ts` | VS Code extension entry point |
| `vscode_extension/src/approval.ts` | Approval webview logic |
