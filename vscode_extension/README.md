# Blender MCP Bridge

Optional VS Code companion extension for the Blender MCP Bridge. Adds an output
channel, an approval webview for gated tool calls, and a live viewport preview
panel — all communicating with the Blender add-on over a local WebSocket.

## Features

- **Output Channel** — mirrors MCP server stderr for easy debugging.
- **Approval Webview** — prompts you to approve, reject, or session-approve
  dangerous tool calls such as `execute_python` and `delete_object`.
- **Viewport Preview** — shows a live image of the Blender viewport with
  manual or auto-refresh (configurable interval).

## Requirements

- **Blender 4.2 LTS** with the Blender MCP Bridge add-on enabled.
- **Blender MCP Server** running (installed via `pip install blender-mcp`).
- **VS Code 1.99+** (built-in MCP support).

## Quick Start

1. Install the Blender MCP Bridge add-on in Blender and enable it.
2. Copy the auth token from the Blender N-panel (View3D > Sidebar > MCP).
3. Configure `.vscode/mcp.json` in your project (see `examples/vscode_mcp.json`).
4. Open a Copilot Chat or other MCP-compatible agent and start issuing commands.
5. Use **Blender MCP: Show Viewport Preview** to open the live preview panel.

## Commands

| Command | Description |
|---------|-------------|
| `Blender MCP: Show Output` | Open the Blender MCP output channel |
| `Blender MCP: Approve Action` | Open the approval webview for a pending action |
| `Blender MCP: Show Viewport Preview` | Open the viewport preview panel |

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `blenderMcp.viewportPreview.enabled` | `false` | Enable automatic viewport refresh on panel open |
| `blenderMcp.viewportPreview.intervalSeconds` | `5` | Seconds between auto-refresh cycles |
| `blenderMcp.approvalServer.port` | `0` | Approval HTTP server port (0 = ephemeral) |

## License

MIT
