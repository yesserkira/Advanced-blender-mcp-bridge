"""Generic modifier capability — works with all 30+ Blender modifier types via RNA.

Replaces v1's hard-coded SUBSURF/BEVEL/MIRROR/ARRAY/BOOLEAN switch.
"""

from __future__ import annotations

from typing import Any

import bpy

from . import register_capability


def _coerce_value(prop, value):
    """Coerce JSON value into the type expected by an RNA property."""
    if value is None:
        return None
    if prop.type == "POINTER":
        # Accept name string -> resolve via fixed_type collection
        if isinstance(value, str):
            fixed = getattr(prop.fixed_type, "identifier", "")
            if fixed == "Object":
                return bpy.data.objects.get(value)
            if fixed == "Material":
                return bpy.data.materials.get(value)
            if fixed in {"Mesh", "Curve", "Lattice", "Armature", "Collection",
                         "Image", "Texture", "NodeTree", "Action"}:
                coll = {
                    "Mesh": "meshes", "Curve": "curves", "Lattice": "lattices",
                    "Armature": "armatures", "Collection": "collections",
                    "Image": "images", "Texture": "textures",
                    "NodeTree": "node_groups", "Action": "actions",
                }[fixed]
                return getattr(bpy.data, coll).get(value)
        return value
    if prop.type in {"INT"} and isinstance(value, (int, float)):
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


def add_modifier(args: dict) -> dict:
    """Add a modifier to an object using RNA introspection.

    Args:
        args: {
            "object": str,
            "type": str (Blender enum: SUBSURF, BEVEL, MIRROR, ARRAY, BOOLEAN,
                          SOLIDIFY, WIREFRAME, SHRINKWRAP, WELD, DECIMATE,
                          SCREW, DISPLACE, SMOOTH, REMESH, SKIN, MASK,
                          NODES, ...),
            "name": str | None,
            "properties": dict (RNA property names to set),
        }
    """
    obj_name = args.get("object")
    mod_type = args.get("type")
    if not obj_name or not mod_type:
        raise ValueError("'object' and 'type' are required")
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        raise ValueError(f"Object not found: {obj_name}")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:add_modifier:{cmd_id}")

    name = args.get("name") or mod_type
    try:
        mod = obj.modifiers.new(name=name, type=mod_type)
    except (TypeError, RuntimeError) as e:
        raise ValueError(f"Could not create modifier of type '{mod_type}': {e}")

    properties = args.get("properties") or {}
    set_props: list[str] = []
    skipped: list[dict] = []

    rna_props = {p.identifier: p for p in mod.bl_rna.properties}
    for k, v in properties.items():
        prop = rna_props.get(k)
        if prop is None:
            skipped.append({"name": k, "reason": "not an RNA property"})
            continue
        if prop.is_readonly:
            skipped.append({"name": k, "reason": "readonly"})
            continue
        try:
            coerced = _coerce_value(prop, v)
            setattr(mod, k, coerced)
            set_props.append(k)
        except Exception as e:
            skipped.append({"name": k, "reason": str(e)})

    return {
        "object": obj.name,
        "modifier": mod.name,
        "type": mod.type,
        "index": list(obj.modifiers).index(mod),
        "properties_set": set_props,
        "skipped": skipped,
    }


register_capability("add_modifier", add_modifier)


def remove_modifier(args: dict) -> dict:
    """Remove a modifier by name.

    Args:
        args: {"object": str, "name": str}
    """
    obj_name = args.get("object")
    name = args.get("name")
    if not obj_name or not name:
        raise ValueError("'object' and 'name' are required")
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        raise ValueError(f"Object not found: {obj_name}")
    mod = obj.modifiers.get(name)
    if mod is None:
        raise ValueError(f"Modifier '{name}' not found on {obj_name}")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:remove_modifier:{cmd_id}")

    obj.modifiers.remove(mod)
    return {"object": obj.name, "removed": name}


register_capability("remove_modifier", remove_modifier)
