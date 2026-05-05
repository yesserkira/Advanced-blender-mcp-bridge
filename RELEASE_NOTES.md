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
