"""Light and camera creation capabilities."""

import bpy

from . import register_capability

LIGHT_TYPES = {"POINT", "SUN", "SPOT", "AREA"}

DEFAULT_ENERGY = {
    "POINT": 1000.0,
    "SUN": 1.0,
    "SPOT": 1000.0,
    "AREA": 1000.0,
}


def light_create(args: dict) -> dict:
    """Create a light object.

    Args:
        args: {
            "type": str - one of POINT, SUN, SPOT, AREA
            "name": str|None - optional object name
            "location": [float, float, float] - default [0,0,0]
            "energy": float|None - default depends on type
            "color": [float, float, float] - default [1,1,1]
            "radius": float|None - point/spot/area radius
            "spot_size": float|None - radians, SPOT only
            "spot_blend": float|None - SPOT only
            "size": float|None - AREA only
        }
    """
    light_type = args.get("type")
    if light_type not in LIGHT_TYPES:
        raise ValueError(
            f"Unknown light type: {light_type}. "
            f"Must be one of: {', '.join(sorted(LIGHT_TYPES))}"
        )

    name = args.get("name")
    location = tuple(args.get("location", [0, 0, 0]))
    energy = args.get("energy", DEFAULT_ENERGY[light_type])
    color = args.get("color", [1, 1, 1])

    if len(location) != 3:
        raise ValueError("location must be [x, y, z]")
    if len(color) != 3:
        raise ValueError("color must be [r, g, b]")

    # Push undo checkpoint
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:light.create:{cmd_id}")

    bpy.ops.object.light_add(type=light_type, location=location)
    obj = bpy.context.active_object

    if name:
        obj.name = name

    light = obj.data
    light.energy = energy
    light.color = tuple(color)

    if args.get("radius") is not None:
        light.shadow_soft_size = args["radius"]

    if light_type == "SPOT":
        if args.get("spot_size") is not None:
            light.spot_size = args["spot_size"]
        if args.get("spot_blend") is not None:
            light.spot_blend = args["spot_blend"]

    if light_type == "AREA" and args.get("size") is not None:
        light.size = args["size"]

    return {
        "name": obj.name,
        "type": light_type,
        "location": list(obj.location),
        "energy": light.energy,
    }


def camera_create(args: dict) -> dict:
    """Create a camera object.

    Args:
        args: {
            "name": str|None - optional object name
            "location": [float, float, float] - default [0,0,5]
            "rotation_euler": [float, float, float] - default [0,0,0]
            "lens": float - focal length in mm, default 50
            "clip_start": float - default 0.1
            "clip_end": float - default 1000
            "sensor_width": float - default 36
        }
    """
    name = args.get("name")
    location = tuple(args.get("location", [0, 0, 5]))
    rotation = tuple(args.get("rotation_euler", [0, 0, 0]))
    lens = args.get("lens", 50.0)
    clip_start = args.get("clip_start", 0.1)
    clip_end = args.get("clip_end", 1000.0)
    sensor_width = args.get("sensor_width", 36.0)

    if len(location) != 3:
        raise ValueError("location must be [x, y, z]")
    if len(rotation) != 3:
        raise ValueError("rotation_euler must be [rx, ry, rz]")

    # Push undo checkpoint
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:camera.create:{cmd_id}")

    bpy.ops.object.camera_add(location=location, rotation=rotation)
    obj = bpy.context.active_object

    if name:
        obj.name = name

    cam = obj.data
    cam.lens = lens
    cam.clip_start = clip_start
    cam.clip_end = clip_end
    cam.sensor_width = sensor_width

    return {
        "name": obj.name,
        "lens": cam.lens,
        "location": list(obj.location),
    }


def camera_set_active(args: dict) -> dict:
    """Set the active scene camera.

    Args:
        args: {
            "name": str - name of the camera object
        }
    """
    name = args.get("name")
    if not name:
        raise ValueError("name is required")

    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object not found: {name}")
    if obj.type != "CAMERA":
        raise ValueError(f"Object '{name}' is not a CAMERA (type={obj.type})")

    # Push undo checkpoint
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:camera.set_active:{cmd_id}")

    bpy.context.scene.camera = obj

    return {"active_camera": obj.name}


register_capability("light.create", light_create)
register_capability("camera.create", camera_create)
register_capability("camera.set_active", camera_set_active)
