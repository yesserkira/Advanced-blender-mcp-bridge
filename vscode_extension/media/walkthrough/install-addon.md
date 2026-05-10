# 1. Install the add-on into Blender

Click the button below to copy the bundled `blender_mcp` add-on into your
Blender user-scripts directory.

The installer will:

- detect every Blender 4.2+ version on this machine
- ask you to pick one if there are several
- refuse to overwrite a **newer** add-on (so manual updates stay)
- prompt for confirmation if an older or equal version is installed

After the files are copied, open Blender → **Edit → Preferences → Add-ons**,
search for **"Blender MCP Bridge"**, and tick the checkbox to enable it.
The add-on starts a local-loopback WebSocket server and writes
`~/.blender_mcp/connection.json` so VS Code can find it automatically.
