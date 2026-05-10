# 3. Start Blender and enable the add-on

Now actually launch Blender, then:

1. **Edit → Preferences → Add-ons**
2. Type **"Blender MCP Bridge"** in the search box
3. Tick the checkbox to enable it

When enabled, the add-on:

- starts a WebSocket server on `127.0.0.1:9876` (loopback only — never
  reachable from another machine)
- writes `~/.blender_mcp/connection.json` containing the host, port, and a
  fresh random auth token
- adds an **MCP** panel to the **N-sidebar** in any 3D viewport so you can
  start/stop the server manually

VS Code is already watching that file: as soon as it appears, the status bar
flips to **● Blender MCP**.
