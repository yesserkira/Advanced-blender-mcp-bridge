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


class BLENDERMCP_OT_confirm_remote_warning(bpy.types.Operator):
    bl_idname = "blendermcp.confirm_remote_warning"
    bl_label = "Confirm remote bind risk"
    bl_description = (
        "Acknowledge the risks of binding the WebSocket server beyond loopback. "
        "After confirming, the server may bind to the selected non-loopback host."
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        prefs.confirmed_remote_warning = True
        # Token rotation: a token that previously lived in a loopback-only
        # connection.json is now about to ride over the network. Treat the
        # old token as compromised and issue a fresh one. The user must
        # restart the server for the new token to take effect.
        prefs.token = _generate_token()
        self.report({"INFO"}, "Remote bind enabled; token rotated. Restart the server.")
        return {"FINISHED"}


class BLENDERMCP_OT_reset_to_loopback(bpy.types.Operator):
    bl_idname = "blendermcp.reset_to_loopback"
    bl_label = "Reset to loopback"
    bl_description = "Force the WebSocket server back to 127.0.0.1 and clear remote-bind flags"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        prefs.bind_host = "127.0.0.1"
        prefs.allow_remote = False
        prefs.confirmed_remote_warning = False
        # Trigger a restart so the change takes effect immediately if
        # the server is currently running.
        from .server import ws_server  # local import to avoid cycle at import time
        from .server import main_thread
        if ws_server.is_running():
            ws_server.stop()
            main_thread.stop()
            prefs.ensure_token()
            main_thread.start()
            ws_server.start(host=prefs.effective_bind_host(), port=prefs.port)
        self.report({"INFO"}, "Reset to loopback.")
        return {"FINISHED"}


class BlenderMCPPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    host: bpy.props.StringProperty(
        name="Host",
        description="Resolved bind address (read-only). Use 'Bind Host' below to change it.",
        default="127.0.0.1",
        options={"HIDDEN"},
    )

    bind_host: bpy.props.EnumProperty(
        name="Bind Host",
        description=(
            "Which network interface the WebSocket server listens on. "
            "Loopback is the secure default — only the local machine can connect. "
            "All interfaces (0.0.0.0) exposes the server to anyone on your network "
            "who knows the auth token."
        ),
        items=[
            ("127.0.0.1", "Loopback (secure)", "Bind to 127.0.0.1 — local-only access"),
            ("0.0.0.0", "All interfaces (REMOTE)", "Bind to 0.0.0.0 — reachable from your network"),
        ],
        default="127.0.0.1",
    )

    allow_remote: bpy.props.BoolProperty(
        name="Allow remote bind",
        description=(
            "Required to bind beyond loopback. You acknowledge that the auth token "
            "will travel over your network. Use SSH port forwarding instead when possible."
        ),
        default=False,
    )

    confirmed_remote_warning: bpy.props.BoolProperty(
        name="Confirmed remote warning",
        description="Set after the user dismisses the remote-bind risk dialog",
        default=False,
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

    exec_mode: bpy.props.EnumProperty(
        name="Execute Python Mode",
        description=(
            "safe = AST validator + sandbox builtins (default; principle of least privilege). "
            "trusted = no validation, full builtins. Auth token is required either way."
        ),
        items=[
            ("safe", "Safe (sandboxed)", "AST-validated, restricted builtins"),
            ("trusted", "Trusted (full Python)", "No validation; full Python runtime"),
        ],
        default="safe",
    )

    def ensure_token(self):
        if not self.token:
            self.token = _generate_token()

    def effective_bind_host(self) -> str:
        """Return the host the server should bind to right now.

        Returns 127.0.0.1 unless the user has explicitly opted into remote
        bind AND acknowledged the risk dialog. Centralised so we can't
        accidentally bypass the gate.
        """
        if self.bind_host == "127.0.0.1":
            return "127.0.0.1"
        if self.allow_remote and self.confirmed_remote_warning:
            return self.bind_host
        return "127.0.0.1"

    def remote_bind_blocked_reason(self) -> str | None:
        """Return a human-readable explanation if remote bind is currently
        being silently downgraded to loopback, else None."""
        if self.bind_host == "127.0.0.1":
            return None
        if not self.allow_remote:
            return "Remote bind requires 'Allow remote bind' to be enabled."
        if not self.confirmed_remote_warning:
            return "Remote bind requires acknowledging the risk dialog."
        return None

    def draw(self, context):
        layout = self.layout

        layout.label(text="Server", icon="WORLD")
        layout.prop(self, "bind_host")
        layout.prop(self, "port")
        layout.prop(self, "autostart")

        if self.bind_host != "127.0.0.1":
            box = layout.box()
            box.label(text="⚠  Remote bind selected", icon="ERROR")
            box.label(text="The auth token will travel over your network.")
            box.label(text="Prefer SSH port forwarding when possible.")
            box.prop(self, "allow_remote")
            blocked = self.remote_bind_blocked_reason()
            if blocked:
                box.label(text=blocked, icon="INFO")
                if self.allow_remote and not self.confirmed_remote_warning:
                    box.operator(
                        "blendermcp.confirm_remote_warning",
                        text="I understand the risks",
                        icon="CHECKMARK",
                    )
            else:
                box.operator(
                    "blendermcp.reset_to_loopback",
                    text="Reset to loopback",
                    icon="LOOP_BACK",
                )

        layout.separator()
        layout.label(text="Auth Token", icon="LOCKED")
        row = layout.row(align=True)
        masked = f"tok_••••{self.token[-4:]}" if len(self.token) >= 4 else "not set"
        row.label(text=masked)
        row.operator("blendermcp.copy_token", text="", icon="COPYDOWN")
        row.operator("blendermcp.regenerate_token", text="", icon="FILE_REFRESH")

        layout.separator()
        layout.label(text="Execution", icon="TOOL_SETTINGS")
        layout.prop(self, "exec_mode")


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
    BLENDERMCP_OT_confirm_remote_warning,
    BLENDERMCP_OT_reset_to_loopback,
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
