"""Blender MCP Bridge — Add-on entry point."""

import os
import sys

bl_info = {
    "name": "Blender MCP Bridge",
    "author": "BlenderVscode contributors",
    "version": (2, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > MCP",
    "description": "WebSocket bridge for AI assistants via MCP",
    "category": "System",
}

# Vendor path: add blender_addon/vendor/ to sys.path so vendored
# packages (websockets) can be imported without pip.
_vendor_dir = os.path.join(os.path.dirname(__file__), "vendor")
if _vendor_dir not in sys.path:
    sys.path.insert(0, _vendor_dir)


def register():
    from . import preferences
    from .ui import panel
    from .server import main_thread, ws_server
    from .capabilities import load_all

    preferences.register()
    panel.register()

    # Load all capability modules into the dispatcher registry
    load_all()

    # Ensure token exists
    prefs = preferences.get_prefs()
    if prefs:
        prefs.ensure_token()

        # Auto-start if configured
        if prefs.autostart:
            main_thread.start()
            ws_server.start(host=prefs.host, port=prefs.port)


def unregister():
    from .server import ws_server, main_thread
    from .ui import panel
    from . import preferences

    # Stop server first
    ws_server.stop()
    main_thread.stop()

    panel.unregister()
    preferences.unregister()
