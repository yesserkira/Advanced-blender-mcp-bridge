"""Scene inspection capability."""

import bpy

from . import register_capability


def scene_get(args: dict) -> dict:
    """Return scene information at the requested detail level.

    Args:
        args: {"detail": "summary"|"standard"|"full"} (default "standard")
    """
    detail = args.get("detail", "standard")
    if detail not in ("summary", "standard", "full"):
        raise ValueError(f"Invalid detail level: {detail}. Must be summary, standard, or full.")

    scene = bpy.context.scene
    result = {
        "scene": scene.name,
        "frame": {
            "current": scene.frame_current,
            "start": scene.frame_start,
            "end": scene.frame_end,
            "fps": scene.render.fps,
        },
    }

    # Object counts (all levels)
    counts: dict[str, int] = {}
    for obj in scene.objects:
        t = obj.type
        counts[t] = counts.get(t, 0) + 1
    result["object_counts"] = counts

    # Active camera
    result["active_camera"] = scene.camera.name if scene.camera else None

    if detail == "summary":
        return result

    # Standard: selection, active, per-object basic info, collections, world
    result["selection"] = [obj.name for obj in bpy.context.selected_objects]
    result["active"] = bpy.context.active_object.name if bpy.context.active_object else None

    objects = []
    for obj in scene.objects:
        obj_info: dict = {
            "name": obj.name,
            "type": obj.type,
            "location": list(obj.location),
            "rotation_euler": list(obj.rotation_euler),
            "scale": list(obj.scale),
            "dimensions": list(obj.dimensions),
            "parent": obj.parent.name if obj.parent else None,
        }

        # Find first collection containing this object
        for coll in bpy.data.collections:
            if obj.name in coll.objects:
                obj_info["collection"] = coll.name
                break
        else:
            obj_info["collection"] = "Scene Collection"

        if detail == "full":
            # Mesh stats
            if obj.type == "MESH" and obj.data:
                mesh = obj.data
                obj_info["mesh"] = {
                    "vertices": len(mesh.vertices),
                    "edges": len(mesh.edges),
                    "polygons": len(mesh.polygons),
                    "materials": [
                        slot.material.name if slot.material else None
                        for slot in obj.material_slots
                    ],
                }

            # Modifiers
            if obj.modifiers:
                obj_info["modifiers"] = [
                    {"name": mod.name, "type": mod.type}
                    for mod in obj.modifiers
                ]

            # Animation
            if obj.animation_data and obj.animation_data.action:
                action = obj.animation_data.action
                obj_info["animation"] = {
                    "has_action": True,
                    "action_name": action.name,
                    "keyframe_count": sum(
                        len(fc.keyframe_points) for fc in action.fcurves
                    ),
                }
            else:
                obj_info["animation"] = {
                    "has_action": False,
                    "action_name": None,
                    "keyframe_count": 0,
                }

        objects.append(obj_info)

    result["objects"] = objects

    # Collections
    collections = []
    for coll in bpy.data.collections:
        collections.append({
            "name": coll.name,
            "children": [c.name for c in coll.children],
            "objects": [o.name for o in coll.objects],
        })
    result["collections"] = collections

    # World
    world = scene.world
    result["world"] = {
        "name": world.name if world else None,
        "use_nodes": world.use_nodes if world else False,
    }

    return result


register_capability("scene.get", scene_get)


def object_transform(args: dict) -> dict:
    """Set location/rotation/scale on an existing object.

    Args:
        args: {
            "name": str - object name
            "location": [float, float, float] - optional
            "rotation_euler": [float, float, float] - optional
            "scale": [float, float, float] - optional
        }
    """
    name = args.get("name")
    if not name:
        raise ValueError("'name' is required")

    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object not found: {name}")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:object.transform:{cmd_id}")

    if "location" in args:
        loc = args["location"]
        if len(loc) != 3:
            raise ValueError("location must be [x, y, z]")
        obj.location = tuple(loc)

    if "rotation_euler" in args:
        rot = args["rotation_euler"]
        if len(rot) != 3:
            raise ValueError("rotation_euler must be [x, y, z]")
        obj.rotation_euler = tuple(rot)

    if "scale" in args:
        scl = args["scale"]
        if len(scl) != 3:
            raise ValueError("scale must be [x, y, z]")
        obj.scale = tuple(scl)

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
        args: {
            "name": str - object name
            "confirm": bool - reserved for policy (default false)
        }
    """
    name = args.get("name")
    if not name:
        raise ValueError("'name' is required")

    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object not found: {name}")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:object.delete:{cmd_id}")

    # Deselect all, then select only the target object
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.delete()

    remaining_count = len(bpy.context.scene.objects)
    return {
        "deleted": name,
        "remaining_count": remaining_count,
    }


register_capability("object.delete", object_delete)


def selection_set(args: dict) -> dict:
    """Set the selection to the given object names.

    Args:
        args: {
            "names": [str] - object names to select
            "active": str|None - optional active object name
        }
    """
    names = args.get("names", [])

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:selection.set:{cmd_id}")

    # Deselect all first
    bpy.ops.object.select_all(action='DESELECT')

    for n in names:
        obj = bpy.data.objects.get(n)
        if obj is None:
            raise ValueError(f"Object not found: {n}")
        obj.select_set(True)

    active_name = args.get("active")
    if active_name is not None:
        active_obj = bpy.data.objects.get(active_name)
        if active_obj is None:
            raise ValueError(f"Active object not found: {active_name}")
        bpy.context.view_layer.objects.active = active_obj

    return {
        "selected": [obj.name for obj in bpy.context.selected_objects],
        "active": bpy.context.active_object.name if bpy.context.active_object else None,
    }


register_capability("selection.set", selection_set)


def selection_get(args: dict) -> dict:
    """Return the current selection.

    Args:
        args: {} (no arguments)
    """
    return {
        "selected": [obj.name for obj in bpy.context.selected_objects],
        "active": bpy.context.active_object.name if bpy.context.active_object else None,
    }


register_capability("selection.get", selection_get)
