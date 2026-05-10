# 2. Pick a Python interpreter for the MCP server

The MCP server is a small Python program that translates AI tool calls into
WebSocket commands sent to Blender. It needs a Python interpreter that has
the `blender_mcp` package installed.

Click below — the extension will scan:

- `${workspaceFolder}/mcp_server/.venv/`
- `${workspaceFolder}/.venv/`
- every `python` / `python3` / `py` on `PATH`

…and check which ones have `blender_mcp` importable. If exactly one is
found, it's set automatically; otherwise you'll get a quick-pick.

If nothing is found, install the server first:

```pwsh
cd mcp_server
python -m venv .venv
.\.venv\Scripts\pip install -e .
```

…then run this step again.
