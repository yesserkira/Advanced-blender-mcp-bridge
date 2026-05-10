# Welcome to the Blender MCP Bridge

This extension connects **Blender** with **VS Code** (and AI assistants like
GitHub Copilot Chat) through the Model Context Protocol. From an AI chat you
can create primitives, edit materials, run geometry-node setups, and grab
viewport screenshots — all in real time.

## How the pieces fit

```
┌────────────┐  WebSocket  ┌──────────┐   stdio    ┌─────────────┐
│  Blender   │ ──────────▶ │ MCP host │ ◀───────── │ VS Code +   │
│ (add-on)   │             │ (Python) │            │ Copilot     │
└────────────┘             └──────────┘            └─────────────┘
```

The walkthrough below installs the add-on into Blender, picks a Python
interpreter for the MCP server, and verifies the connection.
