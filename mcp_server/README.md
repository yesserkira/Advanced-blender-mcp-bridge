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

| Tool | Description |
|------|-------------|
| `ping` | Check connectivity to the Blender add-on |
| `get_scene_info` | Inspect the current scene (summary, standard, or full detail) |
| `create_primitive` | Create a mesh primitive (cube, sphere, cylinder, etc.) |
| `viewport_screenshot` | Capture the viewport as a base64 PNG |
| `set_transform` | Set location, rotation, and/or scale of an object |
| `delete_object` | Delete an object (with confirmation gate) |
| `select` | Set the object selection |
| `get_selection` | Get the current selection and active object |
| `create_material_pbr` | Create a Principled BSDF material |
| `assign_material` | Assign a material to an object |
| `create_light` | Create a light (Point, Sun, Spot, Area) |
| `create_camera` | Create a camera with lens/clip/sensor settings |
| `set_active_camera` | Set the active scene camera |
| `apply_modifier` | Add a modifier (subsurf, bevel, mirror, array, boolean) |
| `edit_mesh` | BMesh editing (extrude, bevel, loop cut, boolean) |
| `set_keyframe` | Insert animation keyframes |
| `begin_transaction` | Begin a grouped undo transaction |
| `commit_transaction` | Commit a transaction |
| `rollback_transaction` | Roll back a transaction |
| `execute_python` | Execute AST-validated Python in Blender (gated) |

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
