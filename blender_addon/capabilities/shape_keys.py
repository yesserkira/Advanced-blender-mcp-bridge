"""Shape keys (relative + absolute) on mesh / curve / surface / lattice objects.

Wraps ``obj.shape_key_add(name=..., from_mix=...)``, value setting, and
removal — none of which are reachable through ``set_property``.
"""

from __future__ import annotations

import bpy

from . import register_capability


_SHAPE_KEY_TYPES = {"MESH", "CURVE", "SURFACE", "LATTICE"}


def _get_keyable_object(name: str):
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object not found: {name}")
    if obj.type not in _SHAPE_KEY_TYPES:
        raise ValueError(
            f"object '{name}' (type {obj.type}) does not support shape keys",
        )
    return obj


def add_shape_key(args: dict) -> dict:
    """Add a shape key to an object.

    The first call also creates the implicit "Basis" key as Blender requires.

    Args:
        args: {
            "object": str,
            "name": str (default "Key"),
            "from_mix": bool (default False) — initialise from current shape mix,
            "value": float (default 0.0) — initial influence,
            "slider_min": float | None,
            "slider_max": float | None,
        }
    """
    obj = _get_keyable_object(args.get("object"))
    name = args.get("name") or "Key"

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:add_shape_key:{cmd_id}")

    if obj.data.shape_keys is None:
        # Create Basis automatically.
        obj.shape_key_add(name="Basis", from_mix=False)
    sk = obj.shape_key_add(name=name, from_mix=bool(args.get("from_mix", False)))
    sk.value = float(args.get("value", 0.0))
    if args.get("slider_min") is not None:
        sk.slider_min = float(args["slider_min"])
    if args.get("slider_max") is not None:
        sk.slider_max = float(args["slider_max"])
    return {
        "object": obj.name,
        "name": sk.name,
        "value": sk.value,
        "count": len(obj.data.shape_keys.key_blocks),
    }


def set_shape_key_value(args: dict) -> dict:
    """Set the influence value of an existing shape key."""
    obj = _get_keyable_object(args.get("object"))
    name = args.get("name")
    if not name:
        raise ValueError("'name' is required")
    if obj.data.shape_keys is None:
        raise ValueError(f"object '{obj.name}' has no shape keys")
    sk = obj.data.shape_keys.key_blocks.get(name)
    if sk is None:
        raise ValueError(f"shape key '{name}' not found on '{obj.name}'")
    if "value" not in args:
        raise ValueError("'value' is required")
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:set_shape_key_value:{cmd_id}")
    sk.value = float(args["value"])
    return {"object": obj.name, "name": name, "value": sk.value}


def remove_shape_key(args: dict) -> dict:
    """Remove a shape key by name. Pass all=True to clear every key."""
    obj = _get_keyable_object(args.get("object"))
    if obj.data.shape_keys is None:
        return {"object": obj.name, "removed": [], "remaining": 0}
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:remove_shape_key:{cmd_id}")
    if args.get("all"):
        names = [k.name for k in obj.data.shape_keys.key_blocks]
        obj.shape_key_clear()
        return {"object": obj.name, "removed": names, "remaining": 0}
    name = args.get("name")
    if not name:
        raise ValueError("'name' or 'all' is required")
    sk = obj.data.shape_keys.key_blocks.get(name)
    if sk is None:
        raise ValueError(f"shape key '{name}' not found on '{obj.name}'")
    obj.shape_key_remove(sk)
    remaining = len(obj.data.shape_keys.key_blocks) if obj.data.shape_keys else 0
    return {"object": obj.name, "removed": [name], "remaining": remaining}


def list_shape_keys(args: dict) -> dict:
    """List shape keys on an object (read-only)."""
    obj = _get_keyable_object(args.get("object"))
    if obj.data.shape_keys is None:
        return {"object": obj.name, "keys": []}
    keys = [
        {
            "name": k.name,
            "value": k.value,
            "slider_min": k.slider_min,
            "slider_max": k.slider_max,
            "mute": k.mute,
        }
        for k in obj.data.shape_keys.key_blocks
    ]
    return {
        "object": obj.name,
        "keys": keys,
        "use_relative": obj.data.shape_keys.use_relative,
    }


register_capability("add_shape_key", add_shape_key)
register_capability("set_shape_key_value", set_shape_key_value)
register_capability("remove_shape_key", remove_shape_key)
register_capability("list_shape_keys", list_shape_keys)
