# Blender MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that
bridges AI assistants — VS Code Copilot Chat, Claude Desktop, Cursor, Cline — to
a running Blender instance. The server exposes typed tools over stdio JSON-RPC
and forwards commands to the Blender add-on via a local WebSocket connection.

## Installation

```bash
pip install blender-mcp
# or
uv add blender-mcp
```

## Quick Start

1. Install and enable the **Blender MCP Bridge** add-on in Blender 4.2+.
2. Copy the auth token from the Blender N-panel (View3D > Sidebar > MCP).
3. Set environment variables and run:

```bash
export BLENDER_MCP_TOKEN="<token-from-blender>"
export BLENDER_MCP_URL="ws://127.0.0.1:9876"  # optional, this is the default
blender-mcp
```

The server communicates with AI clients over stdio (launched automatically by
MCP-compatible editors) and with Blender over the local WebSocket.

## Configuration

Place a `.blendermcp.json` policy file in your project root to restrict tools,
set resource caps, or require confirmation for dangerous operations:

```json
{
  "denied_tools": ["execute_python"],
  "max_polys": 500000,
  "max_resolution": 2048,
  "confirm_required": ["delete_object", "execute_python"]
}
```

## Available Tools

The server exposes ~60 tools across these groups (see [server.py](blender_mcp/server.py) for the authoritative list):

### Connectivity & inspection (read-only)
| Tool | Description |
|------|-------------|
| `ping` | Connectivity + scene context (objects, selection, units, camera) |
| `query` | Inspect a single datablock (object, material, mesh, etc.) |
| `list` | Enumerate datablocks of a given kind |
| `describe_api` | Look up Blender Python API docs for an RNA path |
| `bbox_info` | World-space bounding box of an object |
| `get_property` | Read any RNA property by path |
| `get_audit_log` | Tail of the JSONL audit log |
| `list_collections` | Enumerate scene collections |
| `list_assets` | List importable files under a directory (jail-checked) |
| `list_checkpoints` | List saved scene snapshots |

### Selection
| Tool | Description |
|------|-------------|
| `select` / `deselect_all` / `set_active` / `select_all` | Selection state management |

### Object create / modify
| Tool | Description |
|------|-------------|
| `create_primitive` | Single mesh primitive (cube/sphere/cylinder/cone/plane/torus/monkey) |
| `create_objects` | Batch-create multiple objects |
| `set_transform` | Set location/rotation/scale |
| `delete_object` | Delete object (gated by `confirm_required`) |
| `duplicate_object` | Linked or full copy |
| `set_visibility` | Viewport / render / selectable / show flags |
| `set_parent` / `clear_parent` | Reparent with optional `keep_transform` |
| `rename` | Rename any datablock (object/material/mesh/light/etc.) |
| `apply_to_selection` | Run an op against the current selection |

### Spatial helpers
| Tool | Description |
|------|-------------|
| `place_above` | Sit object on top of another (or "ground") |
| `align_to` | Center/edge alignment along chosen axes |
| `array_around` | Circular array (chair legs, columns) |
| `distribute` | Even spacing along a line |
| `look_at` | Rotate object/camera to face a target |

### Materials & nodes
| Tool | Description |
|------|-------------|
| `assign_material` | Create + assign PBR material |
| `build_nodes` | DSL for shader/world/compositor node graphs (with surgical `remove_nodes`/`remove_links`) |

### Modifiers
| Tool | Description |
|------|-------------|
| `add_modifier` / `remove_modifier` | Subdivision, Bevel, Array, Mirror, Solidify, etc. |

### Geometry nodes
| Tool | Description |
|------|-------------|
| `geonodes_create_modifier` | Add a Geometry Nodes modifier with a new tree |
| `geonodes_create_group` / `geonodes_describe_group` | Create / inspect a node group |
| `geonodes_set_input` / `geonodes_animate_input` | Set or animate exposed inputs |
| `geonodes_realize` | Bake a geo-node result to mesh |
| `geonodes_list_presets` / `geonodes_get_preset` / `geonodes_apply_preset` | Preset library (scatter, bend, extrude_faces, etc.) |

### Collections
| Tool | Description |
|------|-------------|
| `create_collection` / `delete_collection` / `move_to_collection` | Collection management |

### Animation
| Tool | Description |
|------|-------------|
| `set_keyframe` | Insert keyframes on object properties |

### Rendering
| Tool | Description |
|------|-------------|
| `viewport_screenshot` | Capture viewport as base64 PNG |
| `render_region` | Render a region of the viewport |
| `bake_preview` | Quick material preview render |

### Assets
| Tool | Description |
|------|-------------|
| `import_asset` | Import FBX / OBJ / glTF / etc. (jail-checked) |
| `link_blend` | Link or append from a `.blend` file (jail-checked) |

### Advanced / escape hatches
| Tool | Description |
|------|-------------|
| `set_property` / `get_property` | Get/set any RNA property |
| `call_operator` | Call any `bpy.ops.*` (with built-in selection setup) |
| `execute_python` | AST-validated Python (gated, denied in `strict.json`) |
| `transaction` | Group multiple operations into one undo step |

### Safety & state
| Tool | Description |
|------|-------------|
| `scene_diff` | Diff current scene vs a previous snapshot |
| `create_checkpoint` / `list_checkpoints` / `restore_checkpoint` | Scene versioning (.blend snapshots) |

## MCP Client Configuration

### VS Code (`.vscode/mcp.json`)

```json
{
  "servers": {
    "blender": {
      "command": "blender-mcp",
      "env": { "BLENDER_MCP_TOKEN": "${input:blender_token}" }
    }
  }
}
```

### Claude Desktop

```json
{
  "mcpServers": {
    "blender": {
      "command": "blender-mcp",
      "env": { "BLENDER_MCP_TOKEN": "<your-token>" }
    }
  }
}
```

## Security

- Loopback-only WebSocket (127.0.0.1)
- Token authentication on every frame
- AST validation for `execute_python`
- Path-jail for file operations
- Configurable resource caps and rate limiting

See [SECURITY.md](../docs/SECURITY.md) for the full threat model.

## Development

```bash
cd mcp_server
uv sync --all-extras
uv run pytest -q
uv run ruff check blender_mcp tests
uv run mypy blender_mcp --ignore-missing-imports
```

## License

MIT
