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
            "select": list[str] | None,  # objects to select before running
            "active": str | None,        # object to make active before running
            "deselect_others": bool,     # default True when 'select' is given
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

    # ---- Optional selection / active context ----
    select_names = args.get("select")
    active_name = args.get("active")
    deselect_others = bool(args.get("deselect_others", True))
    if select_names is not None or active_name is not None:
        try:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        if deselect_others:
            for o in bpy.context.view_layer.objects:
                o.select_set(False)
        if select_names:
            for n in select_names:
                obj = bpy.data.objects.get(n)
                if obj is None:
                    raise ValueError(f"select target not found: {n}")
                try:
                    obj.select_set(True)
                except RuntimeError as e:
                    raise ValueError(f"cannot select '{n}': {e}")
        if active_name:
            obj = bpy.data.objects.get(active_name)
            if obj is None:
                raise ValueError(f"active target not found: {active_name}")
            try:
                obj.select_set(True)
            except RuntimeError:
                pass
            bpy.context.view_layer.objects.active = obj
        elif select_names:
            # Default active to last in select list
            last = bpy.data.objects.get(select_names[-1])
            if last is not None:
                bpy.context.view_layer.objects.active = last

    if exec_ctx:
        result = fn(exec_ctx, **kwargs)
    else:
        result = fn(**kwargs)

    # bpy.ops returns a set like {'FINISHED'}, {'CANCELLED'}
    result_list = list(result)
    active = bpy.context.active_object
    selected = [o.name for o in bpy.context.selected_objects]
    base = {
        "operator": op,
        "result": result_list,
        "active_object": active.name if active else None,
        "selected": selected,
    }

    # ---- R-1: structured diagnostic on CANCELLED ----
    if "CANCELLED" in result_list:
        expected_mode = _EXPECTED_MODE.get(module_name)
        current_mode = bpy.context.mode
        area_type = None
        try:
            area_type = bpy.context.area.type if bpy.context.area else None
        except AttributeError:
            area_type = None
        hint = _diagnostic_hint(
            op=op, module_name=module_name,
            expected_mode=expected_mode, current_mode=current_mode,
            active=active, selected=selected, area_type=area_type,
        )
        base.update({
            "ok": False,
            "code": "OP_CANCELLED",
            "current_mode": current_mode,
            "expected_mode": expected_mode,
            "area_type": area_type,
            "active_type": active.type if active else None,
            "hint": hint,
        })
    else:
        base["ok"] = True
    return base


# --- diagnostic helpers (R-1) ---------------------------------------------

# Maps the operator's submodule name to the mode that submodule typically
# requires. Used for the structured CANCELLED diagnostic.
_EXPECTED_MODE: dict[str, str] = {
    "mesh": "EDIT_MESH",
    "curve": "EDIT_CURVE",
    "armature": "EDIT_ARMATURE",
    "pose": "POSE",
    "uv": "EDIT_MESH",
    "transform": "OBJECT",  # works in EDIT too, but most callers want OBJECT
    "object": "OBJECT",
    "particle": "PARTICLE",
    "sculpt": "SCULPT",
    "paint": "PAINT_TEXTURE",
}


def _diagnostic_hint(
    *,
    op: str, module_name: str,
    expected_mode: str | None, current_mode: str,
    active, selected: list[str], area_type: str | None,
) -> str:
    """Heuristic single-line hint to help the caller (AI) recover."""
    if expected_mode and current_mode != expected_mode:
        # cross-check object compatibility for EDIT_*
        if expected_mode.startswith("EDIT_"):
            need_type = expected_mode.split("_", 1)[1]
            if active is None:
                return (
                    f"Operator '{op}' needs {expected_mode} but no object is active. "
                    f"Set an active {need_type} object (set_active or select)."
                )
            if active.type != need_type:
                return (
                    f"Operator '{op}' needs an active {need_type}, but the "
                    f"active object '{active.name}' is type {active.type}."
                )
            return (
                f"Operator '{op}' needs mode {expected_mode}; currently {current_mode}. "
                f"Call set_mode(object='{active.name}', mode='EDIT')."
            )
        if expected_mode == "POSE":
            if active is None or active.type != "ARMATURE":
                return (
                    f"Operator '{op}' needs an active ARMATURE in POSE mode "
                    f"(currently {current_mode})."
                )
            return (
                f"Operator '{op}' needs POSE mode on '{active.name}'; "
                f"call set_mode(object='{active.name}', mode='POSE')."
            )
        return (
            f"Operator '{op}' needs mode {expected_mode}; currently {current_mode}."
        )
    if not selected and module_name in {"object", "transform"}:
        return f"Operator '{op}' has nothing selected. Pass select=[...] or active=name."
    if area_type is None or area_type == "EMPTY":
        return (
            f"Operator '{op}' was cancelled. No active area context (background/headless). "
            "If this needs a 3D viewport, run from the viewport or use a higher-level tool."
        )
    return (
        f"Operator '{op}' returned CANCELLED in mode {current_mode} / area {area_type}. "
        "Check selection, active object type, and required mode."
    )


register_capability("call_operator", call_operator)
