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

Each capability module registers itself on import:
- `capabilities/scene.py` → `scene.get`
- `capabilities/mesh.py` → `mesh.create_primitive`
- `capabilities/material.py` → `material.create_pbr`, `material.assign`
- `capabilities/light_camera.py` → `light.create`, `camera.create`, `camera.set_active`
- `capabilities/modifier.py` → `modifier.add`
- `capabilities/animation.py` → `animation.keyframe`
- `capabilities/geonodes.py` → `geonodes.build`
- `capabilities/render.py` → `render.viewport_screenshot`, `render.image`
- `capabilities/exec_python.py` → `exec.python`

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
