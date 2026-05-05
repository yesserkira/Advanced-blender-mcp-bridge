# Blender MCP Server

MCP server that bridges AI assistants (Copilot, Claude, Cursor, Cline) to a running Blender instance.

## Install

```bash
cd mcp_server
uv pip install -e .
```

## Usage

The server is launched automatically by MCP-compatible clients via stdio.

```bash
# Manual test with MCP inspector
uv run mcp dev blender_mcp.server:mcp

# Or run directly
blender-mcp
```

## Configuration

Set the Blender auth token via environment variable:

```bash
BLENDER_MCP_TOKEN=<your-token-from-blender-n-panel>
```

Or store it in your OS keyring under service `blender-mcp`, username `default`.
