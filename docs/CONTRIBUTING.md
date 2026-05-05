# Contributing to Blender MCP Bridge

## Prerequisites

| Tool | Minimum Version | Notes |
|------|----------------|-------|
| Blender | 4.2 LTS | Must be on PATH or launched manually |
| Python | 3.11+ | For the MCP server |
| Node.js | 18+ | For the VS Code extension (optional) |
| VS Code | 1.99+ | Built-in MCP support required |
| uv | latest | Python package manager (fallback: pip) |

## Setup

### 1. Install the Blender Add-on

1. Open Blender → Edit → Preferences → Add-ons → Install.
2. Select the `blender_addon/` folder (or a packaged `.zip`).
3. Enable **Blender MCP Bridge** in the add-on list.
4. The WebSocket server starts automatically on `127.0.0.1:9876`.
5. Copy the auth token from the N-panel → MCP tab.

### 2. Install the MCP Server

```bash
cd mcp_server
uv pip install -e ".[dev]"
```

### 3. Configure Your AI Client

Copy the appropriate config file from `examples/` into your project:

- **VS Code (Copilot Chat):** `.vscode/mcp.json` — see [examples/vscode_mcp.json](../examples/vscode_mcp.json)
- **Claude Desktop:** `claude_desktop_config.json` — see [examples/claude_desktop_config.json](../examples/claude_desktop_config.json)
- **Cursor:** `.cursor/mcp.json` — see [examples/cursor_mcp.json](../examples/cursor_mcp.json)
- **Cline / Continue:** `cline_mcp_settings.json` — see [examples/cline_mcp.json](../examples/cline_mcp.json)

Set your Blender MCP auth token in the config (or use the `${input:blender_token}` prompt in VS Code).

## Testing with Copilot Chat (T-601)

1. Open VS Code 1.99+ with the workspace containing `.vscode/mcp.json`.
2. Open Copilot Chat (Ctrl+Shift+I) and switch to **Agent** mode.
3. The Blender MCP tools should appear in the tool list.
4. Try these sample prompts:
   - `@workspace ping the Blender add-on`
   - `@workspace get the current scene info`
   - `@workspace create a red cube at position [1, 0, 0]`
   - `@workspace take a viewport screenshot`
5. Expected: each tool call round-trips to Blender and returns a result.
6. See `examples/prompts/build_red_chair.md` for a full scene-building prompt.

## Testing with Claude Desktop (T-602)

1. Copy `examples/claude_desktop_config.json` to your Claude Desktop config directory:
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
2. Replace `PASTE_YOUR_TOKEN_HERE` with your Blender MCP auth token.
3. Restart Claude Desktop.
4. The Blender MCP tools should appear in the tool list.
5. Test with the same prompts as above.

## Testing with Cursor (T-603)

1. Copy `examples/cursor_mcp.json` to `.cursor/mcp.json` in your project root.
2. Replace `PASTE_YOUR_TOKEN_HERE` with your Blender MCP auth token.
3. Open Cursor and use the Composer or Chat panel in Agent mode.
4. MCP tools should be available; test with sample prompts from `examples/prompts/`.

## Testing with Cline / Continue (T-603)

1. Copy `examples/cline_mcp.json` to your Cline MCP settings location.
2. Replace `PASTE_YOUR_TOKEN_HERE` with your Blender MCP auth token.
3. Cline will auto-discover the MCP server on next conversation.
4. Test with sample prompts from `examples/prompts/`.

## Running Tests

### MCP Server Tests

```bash
cd mcp_server
uv run pytest -q
```

### Blender Add-on Tests (headless)

```bash
blender -b -P blender_addon/tests/run.py
```

### VS Code Extension

```bash
cd vscode_extension
npm run compile
# Press F5 in VS Code to launch Extension Development Host
```

## Code Style

- **Python:** formatted and linted with `ruff`. Run `ruff check blender_addon mcp_server`.
- **TypeScript:** linted with `eslint`. Run `npm run lint` in `vscode_extension/`.
- **JSON Schemas:** stored in `shared/schemas/`, used as source of truth for validation.

## Pull Request Guidelines

1. One PR per task (T-XXX). Reference the task ID in the PR title.
2. All tests must pass before merge.
3. Do not push to `main` directly — use feature branches.
4. Do not publish to PyPI, npm, or VS Code Marketplace without explicit maintainer approval.
5. Keep commits atomic: one logical change per commit.
