"""N-panel UI for Blender MCP Bridge."""

import bpy

from ..server import ws_server


class BLENDERMCP_OT_start_server(bpy.types.Operator):
    bl_idname = "blendermcp.start_server"
    bl_label = "Start Server"
    bl_description = "Start the MCP WebSocket server"

    def execute(self, context):
        from ..server import main_thread
        from ..preferences import get_prefs

        prefs = get_prefs()
        if not prefs:
            self.report({"ERROR"}, "Add-on preferences not found")
            return {"CANCELLED"}

        prefs.ensure_token()
        main_thread.start()
        ws_server.start(host=prefs.host, port=prefs.port)
        self.report({"INFO"}, f"Server started on ws://{prefs.host}:{prefs.port}")
        return {"FINISHED"}


class BLENDERMCP_OT_stop_server(bpy.types.Operator):
    bl_idname = "blendermcp.stop_server"
    bl_label = "Stop Server"
    bl_description = "Stop the MCP WebSocket server (kill switch)"

    def execute(self, context):
        from ..server import main_thread

        ws_server.stop()
        main_thread.stop()
        self.report({"INFO"}, "Server stopped")
        return {"FINISHED"}


class BLENDERMCP_OT_restart_server(bpy.types.Operator):
    bl_idname = "blendermcp.restart_server"
    bl_label = "Restart Server"
    bl_description = "Restart the MCP WebSocket server"

    def execute(self, context):
        from ..server import main_thread
        from ..preferences import get_prefs

        ws_server.stop()
        main_thread.stop()

        prefs = get_prefs()
        if not prefs:
            self.report({"ERROR"}, "Add-on preferences not found")
            return {"CANCELLED"}

        prefs.ensure_token()
        main_thread.start()
        ws_server.start(host=prefs.host, port=prefs.port)
        self.report({"INFO"}, "Server restarted")
        return {"FINISHED"}


class BLENDERMCP_PT_main_panel(bpy.types.Panel):
    bl_label = "MCP Bridge"
    bl_idname = "BLENDERMCP_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MCP"

    def draw(self, context):
        layout = self.layout
        from ..preferences import get_prefs

        prefs = get_prefs()
        running = ws_server.is_running()

        # Status
        status_icon = "PLAY" if running else "PAUSE"
        status_text = "● Running" if running else "○ Stopped"
        row = layout.row()
        row.label(text=status_text, icon=status_icon)

        if prefs:
            layout.label(text=f"{prefs.host}:{prefs.port}")

            # Masked token
            if prefs.token and len(prefs.token) >= 4:
                masked = f"tok_••••{prefs.token[-4:]}"
            else:
                masked = "not set"
            row = layout.row(align=True)
            row.label(text=masked)
            row.operator("blendermcp.copy_token", text="", icon="COPYDOWN")

        layout.separator()

        # Controls
        if running:
            layout.operator("blendermcp.stop_server", text="Kill Switch", icon="CANCEL")
            layout.operator("blendermcp.restart_server", text="Restart", icon="FILE_REFRESH")
        else:
            layout.operator("blendermcp.start_server", text="Start Server", icon="PLAY")


CLASSES = [
    BLENDERMCP_OT_start_server,
    BLENDERMCP_OT_stop_server,
    BLENDERMCP_OT_restart_server,
    BLENDERMCP_PT_main_panel,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
