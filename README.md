# Blender MCP Bridge

A local, secure bridge that lets AI chat agents inside VS Code (Copilot Chat, Claude Desktop, Cursor, Cline, Continue) inspect and modify a running Blender scene through MCP tool calls.

## Components

- **blender_addon/** — Blender add-on. Runs a WebSocket server on `127.0.0.1`, executes `bpy` ops on the main thread.
- **mcp_server/** — Python MCP server. Exposes typed tools to AI clients, validates, applies policy, forwards to add-on.
- **vscode_extension/** — Optional TypeScript extension. Approval webview, viewport preview, output channel.

## Requirements

- Blender 4.2 LTS or newer
- Python 3.11+
- VS Code 1.99+ (for built-in MCP support)
- `uv` or `pip` for MCP server dependencies

## Quick Start

1. Install the Blender add-on: copy `blender_addon/` to Blender's `scripts/addons/` or install via `.zip`.
2. Enable "Blender MCP Bridge" in Blender Preferences → Add-ons.
3. Copy the auth token from the MCP panel in Blender's N-panel.
4. Install the MCP server: `cd mcp_server && uv pip install -e .`
5. Configure VS Code: see `.vscode/mcp.json` or `examples/vscode_mcp.json`.

## License

MIT — see [LICENSE](LICENSE).
