"""Object & pose-bone constraints — RNA-introspecting (mirrors add_modifier).

Closes the gap where the AI had to ``execute_python`` for every
``COPY_LOCATION`` / ``TRACK_TO`` / ``IK`` / ``LIMIT_*`` setup. Works on both
object constraints and pose-bone constraints, including resolving target /
subtarget pointer values from name strings.
"""

from __future__ import annotations

import bpy

from . import register_capability


def _resolve_owner(args: dict):
    """Return (owner, owner_kind, debug_name).

    owner_kind is ``"object"`` or ``"bone"``. ``owner`` exposes ``.constraints``
    in either case.
    """
    obj_name = args.get("object")
    if not obj_name:
        raise ValueError("'object' is required")
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        raise ValueError(f"Object not found: {obj_name}")

    bone_name = args.get("bone")
    if bone_name:
        if obj.type != "ARMATURE":
            raise ValueError(
                f"object '{obj_name}' is not an armature; cannot use 'bone'",
            )
        if obj.pose is None:
            raise ValueError(
                f"armature '{obj_name}' has no pose data — enter pose mode once "
                "or call set_mode(object='%s', mode='POSE')" % obj_name,
            )
        pbone = obj.pose.bones.get(bone_name)
        if pbone is None:
            raise ValueError(f"bone '{bone_name}' not found on '{obj_name}'")
        return pbone, "bone", f"{obj_name}.pose.bones['{bone_name}']"
    return obj, "object", obj_name


def _coerce_value(prop, value):
    """Coerce JSON value into the type expected by an RNA property.

    Mirrors :mod:`capabilities.modifier`._coerce_value (kept independent so
    the two modules don't depend on each other).
    """
    if value is None:
        return None
    if prop.type == "POINTER":
        if isinstance(value, str):
            fixed = getattr(prop.fixed_type, "identifier", "")
            if fixed == "Object":
                return bpy.data.objects.get(value)
            if fixed == "Action":
                return bpy.data.actions.get(value)
        return value
    if prop.type == "INT" and isinstance(value, (int, float)):
        return int(value)
    if prop.type == "FLOAT":
        if hasattr(prop, "array_length") and prop.array_length > 0 and isinstance(value, (list, tuple)):
            return tuple(float(v) for v in value)
        return float(value) if isinstance(value, (int, float)) else value
    if prop.type == "BOOLEAN":
        if hasattr(prop, "array_length") and prop.array_length > 0 and isinstance(value, (list, tuple)):
            return tuple(bool(v) for v in value)
        return bool(value)
    return value


def add_constraint(args: dict) -> dict:
    """Add a constraint to an object or pose bone.

    Args:
        args: {
            "object": str,
            "bone": str | None       # if set, constraint is added to the pose bone,
            "type": str               # Blender enum: COPY_LOCATION, COPY_ROTATION,
                                       # COPY_SCALE, COPY_TRANSFORMS, LIMIT_LOCATION,
                                       # LIMIT_ROTATION, LIMIT_SCALE, TRACK_TO,
                                       # DAMPED_TRACK, LOCKED_TRACK, IK, FOLLOW_PATH,
                                       # CHILD_OF, ARMATURE, SHRINKWRAP, ...
            "name": str | None,
            "target": str | None,    # convenience: object name; sets `.target`
            "subtarget": str | None, # convenience: bone name on target armature
            "properties": dict | None,  # any RNA property on the constraint
        }
    """
    owner, owner_kind, debug_name = _resolve_owner(args)
    ctype = args.get("type")
    if not ctype:
        raise ValueError("'type' is required")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:add_constraint:{cmd_id}")

    name = args.get("name") or ctype.title().replace("_", " ")
    try:
        c = owner.constraints.new(type=ctype)
    except (TypeError, RuntimeError) as e:
        raise ValueError(f"Could not create constraint of type '{ctype}': {e}")
    c.name = name

    # Convenience pointer assignment.
    target_name = args.get("target")
    if target_name and hasattr(c, "target"):
        target_obj = bpy.data.objects.get(target_name)
        if target_obj is None:
            raise ValueError(f"target object not found: {target_name}")
        c.target = target_obj
    subtarget = args.get("subtarget")
    if subtarget and hasattr(c, "subtarget"):
        c.subtarget = subtarget

    properties = args.get("properties") or {}
    set_props: list[str] = []
    skipped: list[dict] = []
    rna_props = {p.identifier: p for p in c.bl_rna.properties}
    for k, v in properties.items():
        prop = rna_props.get(k)
        if prop is None:
            skipped.append({"name": k, "reason": "not an RNA property"})
            continue
        if prop.is_readonly:
            skipped.append({"name": k, "reason": "readonly"})
            continue
        try:
            setattr(c, k, _coerce_value(prop, v))
            set_props.append(k)
        except Exception as e:  # noqa: BLE001
            skipped.append({"name": k, "reason": str(e)})

    return {
        "owner": debug_name,
        "owner_kind": owner_kind,
        "name": c.name,
        "type": c.type,
        "index": list(owner.constraints).index(c),
        "properties_set": set_props,
        "skipped": skipped,
    }


def remove_constraint(args: dict) -> dict:
    """Remove a constraint by name from an object or pose bone."""
    owner, owner_kind, debug_name = _resolve_owner(args)
    name = args.get("name")
    if not name:
        raise ValueError("'name' is required")
    c = owner.constraints.get(name)
    if c is None:
        raise ValueError(f"constraint '{name}' not found on {debug_name}")
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:remove_constraint:{cmd_id}")
    owner.constraints.remove(c)
    return {"owner": debug_name, "owner_kind": owner_kind, "removed": name}


def list_constraints(args: dict) -> dict:
    """List constraints on an object or pose bone (read-only)."""
    owner, owner_kind, debug_name = _resolve_owner(args)
    out = [
        {
            "name": c.name,
            "type": c.type,
            "mute": c.mute,
            "influence": c.influence,
            "target": getattr(getattr(c, "target", None), "name", None),
            "subtarget": getattr(c, "subtarget", None),
        }
        for c in owner.constraints
    ]
    return {"owner": debug_name, "owner_kind": owner_kind, "constraints": out}


register_capability("add_constraint", add_constraint)
register_capability("remove_constraint", remove_constraint)
register_capability("list_constraints", list_constraints)
