# Changelog

## [1.2.0] - 2026-05-07

### Added — installer & resilience

- Aligned with `blender-mcp` server v1.2.x: stale-token recovery via
  one-shot reauth against live `~/.blender_mcp/connection.json`.
- Companion installer CLI (`blender-mcp-install`) registers the
  MCP server with all detected AI clients (Claude, Cursor, Cline,
  VS Code MCP, Windsurf, Continue) idempotently.

### Fixed

- Persistent `AUTH: Invalid auth token` errors on every new session
  caused by a stale `BLENDER_MCP_TOKEN` user env var. The server now
  prefers the live connection.json over env (unless env explicitly
  targets a different endpoint).

## [1.1.0] - 2026-05-07

### Added — performance & observability

- **MCP server**: new `perf_stats` tool exposing per-tool latency
  percentiles (p50/p95/p99) plus `describe_api_cache` and
  `snapshot_cache` hit/miss/invalidation counters.
- **MCP server**: persistent on-disk cache for `describe_api`
  (`%LOCALAPPDATA%\BlenderMCP\api_cache\<blender_version>.json`).
  Repeated lookups across sessions now skip the round-trip to Blender.
- **MCP server**: 200 ms TTL snapshot cache for read-only ops
  (`scene.context`, `ping`, `query`, `list`, `bbox_info`,
  `list_collections`, `list_constraints`, `list_vertex_groups`,
  `list_shape_keys`). Cache is invalidated on mutating ops and on
  `scene.changed` notifications. TTL configurable via
  `BLENDER_MCP_SNAPSHOT_TTL_MS`.
- **Render transport**: `viewport_screenshot`, `render_region`, and
  `bake_preview` accept `transport: "file"` to write the PNG to
  `%LOCALAPPDATA%\BlenderMCP\renders\<sha256>.png` and return a path
  instead of a base64 blob (large screenshots no longer balloon the
  MCP message stream). Defaults to `"base64"` for backward compat.
- **Extension**: viewport preview webview now uses `transport: "file"`
  with a base64 fallback.
- **Tests**: `pytest-xdist` added to dev deps. `FakeBlenderServer` binds
  to an OS-assigned port (`port=0`) so parallel workers don't collide.
  Suite drops from ~10s to ~6.5s with `-n 4` (~37%).
- **Test count**: 311 passing (was 280).

### Audit fixes (carried forward from earlier work)

- **MCP server**: `asyncio.TimeoutError` now caught in `_call()` — returns
  `{error: "TIMEOUT", message: ...}` instead of propagating a raw exception
  when Blender hangs.
- **MCP server**: 31 new tests covering all 19 previously untested tools
  (v2.4 spatial: `place_above`, `align_to`, `array_around`, `distribute`,
  `look_at`, `bbox_info`; v2.5 selection: `select`, `deselect_all`,
  `set_active`, `select_all`; v2.5 object ops: `duplicate_object`,
  `set_visibility`, `set_parent`, `clear_parent`; v2.5 collections:
  `create_collection`, `delete_collection`, `move_to_collection`,
  `list_collections`; `rename`).
- **Blender addon**: removed dead `ping` handler (addon registered
  `ping → "pong"` but MCP server calls `scene.context` instead).
- **Extension**: esbuild target updated from `node18` to `node20`
  (matches VS Code 1.99+ runtime).

## [2.3.0] - 2026-05-06

### Added — server-initiated change notifications (deferred from v2.2)

- New add-on module [server/notify.py](../blender_addon/server/notify.py)
  installs a `depsgraph_update_post` handler with 750 ms debounce. When
  the scene's snapshot hash changes it broadcasts a notification frame
  to every connected WS client:
  `{"type": "notification", "event": "scene.changed", "uri":
  "blender://scene/current", "hash": "..."}`.
- `BlenderWS` refactored to demux frames via a background reader task —
  responses route by `id` to in-flight futures; notifications go to a
  pluggable handler. Concurrency-safe sends via per-instance lock.
- MCP server registers `subscribe_resource` / `unsubscribe_resource`
  handlers and forwards `scene.changed` to subscribed clients via
  `session.send_resource_updated(uri)` (the standard MCP
  `notifications/resources/updated` method).

### Added — `geonodes_apply_preset` (deferred from v2.2)

- New tool builds a Geometry-Nodes group end-to-end from a preset JSON
  (interface + nodes + links + per-node `properties`), and optionally
  attaches it as a NODES modifier on a target object.
- Honours dry-run; supports `replace=True` to overwrite an existing
  group of the same name.
- 4 new server-side tests + 4 headless integration tests cover the
  three bundled presets.

### Tests / CI

- 166 → 169 server-side tests (3 notifications + 4 apply_preset offset
  by some renames).
- Headless integration suite gains `test_apply_preset_*` cases.
- Tool count 38 → 39; resource count unchanged at 2.

## [2.2.0] - 2026-05-06

### Added — pillar 1: tool metadata

- Every MCP tool now carries `ToolAnnotations` (title, `readOnlyHint`,
  `destructiveHint`, `idempotentHint`, `openWorldHint`). Single source of truth
  in `mcp_server/blender_mcp/tool_meta.py`. 38/38 tools annotated; verified by
  `scripts/smoke_mcp_handshake.py` and `tests/test_tool_meta.py`.

### Added — pillar 2: dry-run

- New envelope field `dry_run: bool` plumbed end-to-end (MCP wrapper →
  `BlenderWS.call` → WS server → main thread → dispatcher → capability via
  `args["__dry_run"]`).
- Dry-run-aware capabilities return `{dry_run: true, would: [...]}` without
  mutating Blender state: `create_objects`, `object.transform`, `object.delete`,
  all 6 `geonodes.*` ops.
- Helpers in `blender_addon/capabilities/_dryrun.py` (poly estimation,
  modify/delete reports).

### Added — pillar 3: read resources

- New capability `scene.snapshot` (full or `summary=True`) with stable
  `sha256(canonical_json)[:16]` hash so clients can short-circuit identical
  reads.
- Two MCP resources advertised under `resources/list`:
  `blender://scene/current` and `blender://scene/summary`.

### Added — pillar 4: Geometry Nodes

- 6 new add-on capabilities + 6 MCP tool wrappers:
  `geonodes_create_modifier`, `geonodes_describe_group`, `geonodes_set_input`,
  `geonodes_animate_input`, `geonodes_create_group`, `geonodes_realize`
  (DESTRUCTIVE).
- 3 bundled JSON presets in `blender_addon/presets/geonodes/`:
  `scatter-on-surface`, `array-along-curve`, `simple-fracture`. Discoverable
  via 2 new tools `geonodes_list_presets` / `geonodes_get_preset`.

### Added — testing

- 14 new server-side tests (163 total, was 149).
- New headless Blender integration suite under `tests/integration/` covering
  create / snapshot / geonodes / dry-run, runnable as
  `blender --background --python tests/integration/run_in_blender.py`.
- New CI job `blender-integration` (matrix Blender 4.2.0 / 4.3.0 on
  ubuntu-latest, cached tarball).

### Deferred

- Pillar 3 server-initiated change notifications (`notifications/resources/
  updated`) deferred to v2.3 — needs Copilot-side validation.
- `geonodes_apply_preset` deferred — graph correctness can't be validated
  without real Blender; presets ship as readable templates instead.

## [2.1.0-rc2] - 2026-05-05

### Added

- **Programmatic MCP server registration** for Copilot Chat (Agent mode) via `vscode.lm.registerMcpServerDefinitionProvider`. Set `blenderMcp.pythonPath` to your venv's `python.exe` and the `blender` MCP server is auto-registered with no `.vscode/mcp.json` required.
- **End-to-end approval flow**: random per-session CSRF, discovery file at `%LOCALAPPDATA%\BlenderMCP\approval.json` so the spawned MCP server can find the extension. Session approvals now keyed by `tool:sha256(args)` so a different argument shape re-prompts.
- Activity bar tree view with Connection, Quick Actions, and Recent Activity groups (status bar + 5 commands: Show Output, Show Status, Reconnect, Refresh Audit Log, Take Viewport Screenshot).
- New settings `blenderMcp.pythonPath`, `blenderMcp.serverModule`.

### Changed

- Approval HTTP server now rejects non-loopback peers (defence in depth) and uses constant-time CSRF compare.
- `viewportPreview.ts` rewritten to use the shared `wsClient.ts` RFC 6455 client.

### Server-side companion (mcp_server v2.1.0)

- `execute_python` and `delete_object` now block on real user approval (CONFIRM_DENIED on reject; CONFIRM_REQUIRED only when extension is unreachable).
- Token-bucket rate limit on mutating tools (default 50 ops / 10 s).
- Polygon estimator rejects `create_objects` calls that would exceed `max_polys` *before* sending to Blender.
- New `create_checkpoint` / `list_checkpoints` / `restore_checkpoint` tools backed by full `.blend` snapshots in `%LOCALAPPDATA%\BlenderMCP\checkpoints\`.

## [1.0.0] - 2026-05-05

### Added

- Blender MCP Bridge output channel mirroring MCP server stderr.
- Approval webview with HTTP loopback server for tool confirmation (approve, reject, approve-and-remember-for-session).
- Viewport preview panel with raw WebSocket client for live Blender viewport screenshots.
- MCP configuration support for VS Code, Claude Desktop, Cursor, and Cline.
- Three contributed commands: Show Output, Approve Action, Show Viewport Preview.
- Settings for viewport auto-refresh interval and approval server port.
