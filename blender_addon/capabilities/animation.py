"""Animation keyframe capability."""

import bpy

from . import register_capability


def animation_keyframe(args: dict) -> dict:
    """Insert a keyframe on an object property.

    Args:
        args: {
            "object_name": str - name of the target object
            "data_path": str - property path, e.g. "location", "rotation_euler", "scale"
            "frame": int - frame number to insert the keyframe at
            "value": float|list|None - optional value to set before inserting
            "index": int|None - optional channel index (-1 for all)
        }
    """
    object_name = args.get("object_name")
    if not object_name:
        raise ValueError("'object_name' is required")

    data_path = args.get("data_path")
    if not data_path:
        raise ValueError("'data_path' is required")

    frame = args.get("frame")
    if frame is None:
        raise ValueError("'frame' is required")

    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object not found: {object_name}")

    value = args.get("value")
    index = args.get("index", -1)

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:animation.keyframe:{cmd_id}")

    # Set the frame
    bpy.context.scene.frame_set(frame)

    # If value is provided, set the property first
    if value is not None:
        prop = getattr(obj, data_path)
        if isinstance(value, list):
            for i, v in enumerate(value):
                prop[i] = v
        elif index >= 0:
            prop[index] = value
        else:
            setattr(obj, data_path, value)

    # Insert keyframe
    obj.keyframe_insert(data_path=data_path, frame=frame, index=index)

    # Read back the current value
    current = getattr(obj, data_path)
    if hasattr(current, "__len__"):
        current = list(current)

    return {
        "object": obj.name,
        "data_path": data_path,
        "frame": frame,
        "value": current,
    }


register_capability("animation.keyframe", animation_keyframe)
