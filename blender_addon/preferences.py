"""Add-on preferences: host, port, token, capability toggles."""

import secrets

import bpy


def _generate_token():
    return secrets.token_urlsafe(32)


class BLENDERMCP_OT_regenerate_token(bpy.types.Operator):
    bl_idname = "blendermcp.regenerate_token"
    bl_label = "Regenerate Token"
    bl_description = "Generate a new auth token and restart the server"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        prefs.token = _generate_token()
        self.report({"INFO"}, "Token regenerated. Restart server to apply.")
        return {"FINISHED"}


class BLENDERMCP_OT_copy_token(bpy.types.Operator):
    bl_idname = "blendermcp.copy_token"
    bl_label = "Copy Token"
    bl_description = "Copy the auth token to clipboard"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        context.window_manager.clipboard = prefs.token
        self.report({"INFO"}, "Token copied to clipboard.")
        return {"FINISHED"}


class BlenderMCPPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    host: bpy.props.StringProperty(
        name="Host",
        description="WebSocket bind address (loopback only)",
        default="127.0.0.1",
        options={"HIDDEN"},
    )

    port: bpy.props.IntProperty(
        name="Port",
        description="WebSocket server port",
        default=9876,
        min=1024,
        max=65535,
    )

    token: bpy.props.StringProperty(
        name="Token",
        description="Auth token for WebSocket connections",
        default="",
        options={"HIDDEN"},
    )

    autostart: bpy.props.BoolProperty(
        name="Auto-start Server",
        description="Start the WebSocket server when the add-on is enabled",
        default=False,
    )

    require_confirm_exec_python: bpy.props.BoolProperty(
        name="Confirm execute_python",
        description="Require user confirmation before running arbitrary Python",
        default=True,
    )

    exec_mode: bpy.props.EnumProperty(
        name="Execute Python Mode",
        description=(
            "safe = AST validator + sandbox builtins (recommended). "
            "trusted = no validation, full builtins (auth token still required)."
        ),
        items=[
            ("safe", "Safe (sandboxed)", "AST-validated, restricted builtins"),
            ("trusted", "Trusted (full Python)", "No validation; full Python runtime"),
        ],
        default="safe",
    )

    # Capability toggles (cosmetic; enforcement is at MCP server policy layer)
    cap_scene: bpy.props.BoolProperty(name="Scene inspection", default=True)
    cap_mesh: bpy.props.BoolProperty(name="Mesh creation", default=True)
    cap_modifier: bpy.props.BoolProperty(name="Modifiers", default=True)
    cap_animation: bpy.props.BoolProperty(name="Animation", default=True)
    cap_render: bpy.props.BoolProperty(name="Render / Screenshot", default=True)
    cap_exec_python: bpy.props.BoolProperty(name="Execute Python", default=False)
    cap_nodes: bpy.props.BoolProperty(name="Node graphs (shader/geo/world)", default=True)
    cap_assets: bpy.props.BoolProperty(name="Asset import", default=True)

    def ensure_token(self):
        if not self.token:
            self.token = _generate_token()

    def draw(self, context):
        layout = self.layout

        layout.label(text="Server", icon="WORLD")
        row = layout.row()
        row.prop(self, "host")
        row.enabled = False  # read-only, loopback enforced
        layout.prop(self, "port")
        layout.prop(self, "autostart")

        layout.separator()
        layout.label(text="Auth Token", icon="LOCKED")
        row = layout.row(align=True)
        masked = f"tok_••••{self.token[-4:]}" if len(self.token) >= 4 else "not set"
        row.label(text=masked)
        row.operator("blendermcp.copy_token", text="", icon="COPYDOWN")
        row.operator("blendermcp.regenerate_token", text="", icon="FILE_REFRESH")

        layout.separator()
        layout.label(text="Capabilities", icon="TOOL_SETTINGS")
        col = layout.column(align=True)
        col.prop(self, "cap_scene")
        col.prop(self, "cap_mesh")
        col.prop(self, "cap_modifier")
        col.prop(self, "cap_animation")
        col.prop(self, "cap_render")
        col.prop(self, "cap_nodes")
        col.prop(self, "cap_assets")
        col.prop(self, "cap_exec_python")
        if self.cap_exec_python:
            layout.prop(self, "exec_mode")
            layout.prop(self, "require_confirm_exec_python")


def get_prefs():
    """Return the add-on preferences, or None if not available."""
    addon = bpy.context.preferences.addons.get(__package__)
    if addon:
        return addon.preferences
    return None


def get_token():
    """Return the current auth token."""
    prefs = get_prefs()
    if prefs:
        return prefs.token
    return ""


CLASSES = [
    BLENDERMCP_OT_regenerate_token,
    BLENDERMCP_OT_copy_token,
    BlenderMCPPreferences,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    # Ensure token is generated on first register
    prefs = get_prefs()
    if prefs:
        prefs.ensure_token()


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
