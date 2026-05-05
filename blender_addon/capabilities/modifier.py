"""Modifier capability."""

import bpy

from . import register_capability

ALLOWED_TYPES = {"SUBSURF", "BEVEL", "MIRROR", "ARRAY", "BOOLEAN"}


def modifier_add(args: dict) -> dict:
    """Add a modifier to an object.

    Args:
        args: {
            "object_name": str - name of the target object
            "modifier_type": str - one of SUBSURF, BEVEL, MIRROR, ARRAY, BOOLEAN
            "modifier_name": str|None - optional display name for the modifier
            "params": dict|None - modifier-specific parameters
        }
    """
    object_name = args.get("object_name")
    if not object_name:
        raise ValueError("'object_name' is required")

    modifier_type = args.get("modifier_type")
    if modifier_type not in ALLOWED_TYPES:
        raise ValueError(
            f"Unknown modifier_type: {modifier_type}. "
            f"Must be one of: {', '.join(sorted(ALLOWED_TYPES))}"
        )

    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object not found: {object_name}")

    modifier_name = args.get("modifier_name") or modifier_type
    params = args.get("params", {}) or {}

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:modifier.add:{cmd_id}")

    mod = obj.modifiers.new(name=modifier_name, type=modifier_type)

    # Apply type-specific params
    if modifier_type == "SUBSURF":
        mod.levels = params.get("levels", 2)
        mod.render_levels = params.get("render_levels", 2)
    elif modifier_type == "BEVEL":
        mod.width = params.get("width", 0.1)
        mod.segments = params.get("segments", 1)
    elif modifier_type == "MIRROR":
        use_axis = params.get("use_axis", [True, False, False])
        mod.use_axis[0] = use_axis[0]
        mod.use_axis[1] = use_axis[1]
        mod.use_axis[2] = use_axis[2]
    elif modifier_type == "ARRAY":
        mod.count = params.get("count", 2)
        offset = params.get("relative_offset_displace", [1, 0, 0])
        mod.relative_offset_displace[0] = offset[0]
        mod.relative_offset_displace[1] = offset[1]
        mod.relative_offset_displace[2] = offset[2]
    elif modifier_type == "BOOLEAN":
        operation = params.get("operation", "DIFFERENCE")
        mod.operation = operation
        bool_obj_name = params.get("object")
        if bool_obj_name:
            bool_obj = bpy.data.objects.get(bool_obj_name)
            if bool_obj is None:
                raise ValueError(f"Boolean target object not found: {bool_obj_name}")
            mod.object = bool_obj

    return {
        "object": obj.name,
        "modifier_name": mod.name,
        "modifier_type": mod.type,
        "index": list(obj.modifiers).index(mod),
    }


register_capability("modifier.add", modifier_add)
