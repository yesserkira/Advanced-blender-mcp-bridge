"""Object transform / delete (the only ops needed beyond query/composer)."""

from __future__ import annotations

import bpy

from . import register_capability


def object_transform(args: dict) -> dict:
    """Set location/rotation/scale on an existing object.

    Args:
        args: {
            "object": str  (also accepts "name" for backwards compatibility),
            "location": [x,y,z] | None,
            "rotation_euler": [x,y,z] | None,
            "scale": [x,y,z] | None,
        }
    """
    name = args.get("object") or args.get("name")
    if not name:
        raise ValueError("'object' is required")
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object not found: {name}")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:object.transform:{cmd_id}")

    if "location" in args and args["location"] is not None:
        obj.location = tuple(args["location"])
    if "rotation_euler" in args and args["rotation_euler"] is not None:
        obj.rotation_euler = tuple(args["rotation_euler"])
    if "scale" in args and args["scale"] is not None:
        obj.scale = tuple(args["scale"])

    return {
        "name": obj.name,
        "location": list(obj.location),
        "rotation_euler": list(obj.rotation_euler),
        "scale": list(obj.scale),
    }


register_capability("object.transform", object_transform)


def object_delete(args: dict) -> dict:
    """Delete an object by name.

    Args:
        args: {"object": str (or "name"), "confirm": bool}
    """
    name = args.get("object") or args.get("name")
    if not name:
        raise ValueError("'object' is required")
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object not found: {name}")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:object.delete:{cmd_id}")

    bpy.data.objects.remove(obj, do_unlink=True)
    return {
        "deleted": name,
        "remaining_count": len(bpy.context.scene.objects),
    }


register_capability("object.delete", object_delete)
