"""Generic bpy.ops operator caller with allowlist.

Lets the AI invoke any safe bpy.ops operator without us having to wrap
each one. Dangerous operators (file I/O at the WM level, factory reset,
quit, etc.) are denied by default.
"""

from __future__ import annotations

import bpy

from . import register_capability


# Default deny-list — these operators must never be exposed to AI.
DEFAULT_DENIED = frozenset({
    "wm.quit_blender",
    "wm.read_factory_settings",
    "wm.read_factory_userpref",
    "wm.read_homefile",
    "wm.recover_last_session",
    "wm.recover_auto_save",
    "wm.open_mainfile",
    "wm.save_mainfile",
    "wm.save_as_mainfile",
    "wm.save_userpref",
    "wm.url_open",
    "wm.console_toggle",
    "preferences.addon_install",
    "preferences.addon_remove",
    "preferences.addon_enable",
    "preferences.addon_disable",
    "preferences.app_template_install",
    "preferences.copy_prev",
    "preferences.studiolight_install",
    "preferences.theme_install",
    "preferences.reset_default_theme",
    "preferences.keyconfig_import",
    "preferences.keyconfig_export",
    "script.execute_preset",
    "script.python_file_run",
    "script.reload",
    "screen.userpref_show",
})

# Allowed module prefixes (operators outside these are denied).
DEFAULT_ALLOWED_PREFIXES = (
    "mesh.", "object.", "material.", "scene.", "render.", "image.",
    "node.", "transform.", "view3d.", "curve.", "armature.", "pose.",
    "uv.", "particle.", "rigidbody.", "ptcache.", "anim.", "action.",
    "graph.", "nla.", "outliner.", "collection.", "world.", "lamp.",
    "camera.", "constraint.", "modifier.", "shader.", "texture.",
    "fluid.", "cloth.", "geometry.",
)


def _is_allowed(op: str, allowed_prefixes: tuple[str, ...]) -> bool:
    if op in DEFAULT_DENIED:
        return False
    return any(op.startswith(p) for p in allowed_prefixes)


def call_operator(args: dict) -> dict:
    """Call a bpy.ops operator with the given keyword args.

    Args:
        args: {
            "operator": str  (e.g. "object.shade_smooth", "mesh.primitive_uv_sphere_add"),
            "kwargs": dict (default {}),
            "execution_context": str | None ("INVOKE_DEFAULT", "EXEC_DEFAULT", ...),
        }
    """
    op = args.get("operator")
    if not op:
        raise ValueError("'operator' is required")
    kwargs = args.get("kwargs") or {}
    exec_ctx = args.get("execution_context")

    allowed_prefixes = args.get("_allowed_prefixes") or DEFAULT_ALLOWED_PREFIXES
    denied_extra = set(args.get("_denied_extra") or [])
    if op in denied_extra or not _is_allowed(op, allowed_prefixes):
        raise ValueError(f"Operator '{op}' is denied by policy")

    if "." not in op:
        raise ValueError(f"operator must be 'module.name' (got '{op}')")
    module_name, op_name = op.split(".", 1)
    module = getattr(bpy.ops, module_name, None)
    if module is None:
        raise ValueError(f"bpy.ops.{module_name} does not exist")
    fn = getattr(module, op_name, None)
    if fn is None:
        raise ValueError(f"bpy.ops.{op} does not exist")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:call_operator:{op}:{cmd_id}")

    if exec_ctx:
        result = fn(exec_ctx, **kwargs)
    else:
        result = fn(**kwargs)

    # bpy.ops returns a set like {'FINISHED'}, {'CANCELLED'}
    return {
        "operator": op,
        "result": list(result),
        "active_object": (
            bpy.context.active_object.name if bpy.context.active_object else None
        ),
    }


register_capability("call_operator", call_operator)
