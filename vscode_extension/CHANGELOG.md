# Changelog

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
