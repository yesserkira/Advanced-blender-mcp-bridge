"""set_mode — switch the active object's interaction mode atomically.

Without this tool the AI must do call_operator("object.mode_set", mode="EDIT")
which fails silently when the active object isn't compatible with the
requested mode (e.g. trying to enter EDIT on a LIGHT). This wrapper validates
compatibility, optionally activates a target object first, and reports a
machine-actionable diagnostic when the mode is incompatible.
"""

from __future__ import annotations

import bpy

from . import register_capability


# Modes valid per object type, sourced from Blender 4.2 docs.
_MODE_BY_TYPE: dict[str, frozenset[str]] = {
    "MESH": frozenset({
        "OBJECT", "EDIT", "SCULPT",
        "VERTEX_PAINT", "WEIGHT_PAINT", "TEXTURE_PAINT",
        "PARTICLE_EDIT",
    }),
    "CURVE": frozenset({"OBJECT", "EDIT"}),
    "CURVES": frozenset({"OBJECT", "EDIT", "SCULPT_CURVES"}),
    "SURFACE": frozenset({"OBJECT", "EDIT"}),
    "META": frozenset({"OBJECT", "EDIT"}),
    "FONT": frozenset({"OBJECT", "EDIT"}),
    "ARMATURE": frozenset({"OBJECT", "EDIT", "POSE"}),
    "LATTICE": frozenset({"OBJECT", "EDIT"}),
    "GPENCIL": frozenset({
        "OBJECT", "EDIT", "SCULPT_GPENCIL",
        "PAINT_GPENCIL", "WEIGHT_GPENCIL", "VERTEX_GPENCIL",
    }),
    "GREASEPENCIL": frozenset({
        "OBJECT", "EDIT", "SCULPT_GREASE_PENCIL",
        "PAINT_GREASE_PENCIL", "WEIGHT_GREASE_PENCIL",
    }),
    "EMPTY": frozenset({"OBJECT"}),
    "LIGHT": frozenset({"OBJECT"}),
    "CAMERA": frozenset({"OBJECT"}),
    "SPEAKER": frozenset({"OBJECT"}),
    "VOLUME": frozenset({"OBJECT"}),
    "POINTCLOUD": frozenset({"OBJECT"}),
    "LIGHT_PROBE": frozenset({"OBJECT"}),
}

_ALL_MODES = frozenset(m for s in _MODE_BY_TYPE.values() for m in s)


def set_mode(args: dict) -> dict:
    """Switch interaction mode for an object.

    Args:
        args: {
            "mode": str — one of OBJECT / EDIT / SCULPT / POSE /
                    VERTEX_PAINT / WEIGHT_PAINT / TEXTURE_PAINT /
                    PARTICLE_EDIT / SCULPT_CURVES / ...
                    (case-insensitive accepted; normalised internally)
            "object": str | None — object to make active first (optional;
                                   uses current active otherwise),
        }

    Returns:
        {ok, mode, object, type, previous_mode}
    """
    mode = (args.get("mode") or "").upper()
    if mode not in _ALL_MODES:
        raise ValueError(
            f"Unknown mode '{mode}'. Allowed: {sorted(_ALL_MODES)}",
        )

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:set_mode:{cmd_id}")

    target_name = args.get("object")
    if target_name:
        obj = bpy.data.objects.get(target_name)
        if obj is None:
            raise ValueError(f"Object not found: {target_name}")
        bpy.context.view_layer.objects.active = obj
        try:
            obj.select_set(True)
        except RuntimeError:
            pass
    else:
        obj = bpy.context.view_layer.objects.active
        if obj is None:
            raise ValueError("No active object — pass 'object' to set one")

    valid_for_type = _MODE_BY_TYPE.get(obj.type, frozenset({"OBJECT"}))
    if mode not in valid_for_type:
        raise ValueError(
            f"Mode '{mode}' is not valid for object '{obj.name}' "
            f"(type {obj.type}). Valid modes: {sorted(valid_for_type)}",
        )

    previous_mode = bpy.context.mode

    # bpy.ops.object.mode_set wants the same mode strings as bpy.context.mode.
    if mode != _normalise_context_mode(previous_mode):
        # Always go through OBJECT first when crossing between non-OBJECT modes.
        if previous_mode != "OBJECT" and mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.mode_set(mode=mode)

    return {
        "ok": True,
        "mode": mode,
        "object": obj.name,
        "type": obj.type,
        "previous_mode": previous_mode,
    }


def _normalise_context_mode(ctx_mode: str) -> str:
    """`bpy.context.mode` returns labels like ``EDIT_MESH`` while
    ``mode_set`` wants ``EDIT``. Strip the suffix for comparison purposes.
    """
    if ctx_mode.startswith("EDIT_"):
        return "EDIT"
    if ctx_mode.startswith("PAINT_"):
        return ctx_mode  # PAINT_* already matches
    return ctx_mode


register_capability("set_mode", set_mode)
