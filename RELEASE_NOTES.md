# Blender MCP Bridge v1.1.0

Release Date: 2026-05-07

## What's New — Performance, observability & Tier‑1 capability completeness

This release delivers measurable speedups across the hot path, adds end‑to‑end
performance instrumentation, and closes the remaining gaps that previously
forced agents to fall back to `execute_python`.

### Performance & observability (new in this session)

- **`perf_stats` MCP tool** — per‑tool latency percentiles (p50/p95/p99),
  call counts, and cache hit/miss/invalidation counters. Powered by a ring
  buffer in [`mcp_server/blender_mcp/perf.py`](mcp_server/blender_mcp/perf.py).
- **Persistent `describe_api` cache** — keyed by Blender version at
  `%LOCALAPPDATA%\BlenderMCP\api_cache\<version>.json`. Repeated lookups
  across sessions skip the round‑trip to Blender entirely.
- **Snapshot TTL cache** — 200 ms coalescer for read‑only ops
  (`scene.context`, `ping`, `query`, `list`, `bbox_info`, `list_collections`,
  `list_constraints`, `list_vertex_groups`, `list_shape_keys`). Invalidated
  on mutating ops and on `scene.changed` notifications. TTL configurable via
  `BLENDER_MCP_SNAPSHOT_TTL_MS`.
- **Render tempfile transport** — `viewport_screenshot`, `render_region`,
  and `bake_preview` accept `transport: "file"` to write the PNG to
  `%LOCALAPPDATA%\BlenderMCP\renders\<sha256>.png` and return a path.
  Eliminates base64 bloat in the MCP message stream for large captures.
  Defaults to `"base64"` for backward compat. The VS Code viewport preview
  uses `"file"` with a base64 fallback.
- **Parallel test runs** — `pytest-xdist` added to dev deps. The
  `FakeBlenderServer` now binds to an OS‑assigned ephemeral port so workers
  don't collide. Suite drops from ~10 s to ~6.5 s with `-n 4` (~37%).
  Sequential remains the default for easier debugging.

### Add‑on capability completeness (carried forward)

- **Data‑block creators**: `create_light`, `create_camera`, `set_active_camera`, `create_empty`, `create_text`, `create_curve`, `create_armature`, `load_image`, `create_image`. All apply props in one undo step.
- **Atomic mode switch**: `set_mode(object?, mode)` validates compatibility per object type (rejects e.g. EDIT on LIGHT) and crosses non‑OBJECT → non‑OBJECT via OBJECT.
- **Constraints**: `add_constraint` / `remove_constraint` / `list_constraints` for objects **and** pose bones (`bone="..."`). RNA‑introspecting; `target` / `subtarget` auto‑resolve.
- **Rigging primitives**: `create_vertex_group` / `remove_vertex_group` / `list_vertex_groups` / `set_vertex_weights` (REPLACE / ADD / SUBTRACT). Shape keys: `add_shape_key`, `set_shape_key_value`, `remove_shape_key` (single or `all=true`), `list_shape_keys`. Basis is auto‑created on first add.
- **Mesh editing without the EDIT‑mode dance**: new `mesh_edit(object, ops:[...])` declarative bmesh DSL covering extrude (faces/edges/verts), inset, bevel, subdivide, loop_cut, merge / remove_doubles, delete_*/dissolve_*, bridge_loops, fill, triangulate, recalc / flip normals, smooth, transform. All ops in a single bmesh transaction → one undo step. `mesh_read` adds bounded slicing for vertex/edge/face/normal/UV inspection (max 10 000 elements per call).
- **Operator diagnostic envelope (R‑1)**: when `call_operator` returns CANCELLED, the response now includes `code:"OP_CANCELLED"`, `current_mode`, `expected_mode`, `area_type`, `active_type`, and a one‑line `hint`. No more silent CANCELLEDs.

### Stats

- **Test count**: 311 passing (sequential 9.0 s, parallel `-n 4` 6.5 s).
- **Lint**: clean (`ruff check`).

---

# Blender MCP Bridge v1.0.0

Release Date: 2026-05-05

## What's New

First stable release of the AI-to-Blender bridge system.

### Blender Add-on
- WebSocket server with token authentication
- 15+ capabilities: scene inspection, mesh creation, materials, lights, cameras, modifiers, animation, Python execution
- Transaction system with undo/redo support
- AST-based Python code validator (security)
- Append-only audit logging
- Geometry Nodes declarative DSL
- Shader graph declarative DSL
- Asset import with path-jail security

### MCP Server
- 21+ MCP tools for AI assistants
- Policy engine with configurable restrictions
- Auto-reconnect WebSocket client
- Self-healing Python execution with suggest_fix
- Streaming progress on render operations

### VS Code Extension
- Approval webview with session auto-approve
- Viewport preview panel with live refresh
- Output channel for server logs

### Security
- Loopback-only binding (127.0.0.1)
- Token authentication on every frame
- AST validation for Python execution
- Path-jail for file operations
- Resource caps (polygons, resolution)

### Compatibility
- Blender 4.2 LTS
- VS Code 1.99+ (built-in MCP)
- Claude Desktop, Cursor, Cline
- Python 3.11+

## Installation

See docs/CONTRIBUTING.md for setup instructions.

## Known Limitations

- Single-user only (loopback transport)
- No marketplace publish yet (manual install)
- Streaming progress only over raw WebSocket (not MCP notifications)
