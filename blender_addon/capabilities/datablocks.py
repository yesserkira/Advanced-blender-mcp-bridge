"""First-class data-block creators: lights, cameras, text, curves, empties,
armatures, images.

Closes the largest hole in the Tier-1 capability gap: previously the AI had
to ``call_operator("object.light_add")`` then ``set_property("...energy", ...)``
or fall back to ``execute_python``. Each helper here creates the datablock,
links it into the active scene's Scene Collection, and applies whatever
properties were passed in one undo step.
"""

from __future__ import annotations

import os

import bpy

from . import register_capability


# ---------------------------------------------------------------------------
# Lights
# ---------------------------------------------------------------------------

_LIGHT_KINDS = {"point": "POINT", "sun": "SUN", "spot": "SPOT", "area": "AREA"}


def create_light(args: dict) -> dict:
    """Create a light datablock + object.

    Args:
        args: {
            "kind": "point" | "sun" | "spot" | "area",
            "name": str | None,
            "location": [x,y,z] (default [0,0,0]),
            "rotation": [rx,ry,rz] | None  (radians),
            "color": [r,g,b] (default [1,1,1]),
            "energy": float | None  (Watts for point/spot/area, irradiance for sun),
            "size": float | None  (radius for point/spot, side for area, angle for sun),
            "spot_size": float | None  (radians, spot only),
            "spot_blend": float | None  (0..1, spot only),
            "shape": "SQUARE"|"RECTANGLE"|"DISK"|"ELLIPSE" | None  (area only),
        }
    """
    kind = (args.get("kind") or "").lower()
    if kind not in _LIGHT_KINDS:
        raise ValueError(
            f"kind must be one of {sorted(_LIGHT_KINDS)} (got '{kind}')"
        )
    bl_kind = _LIGHT_KINDS[kind]
    name = args.get("name") or kind.capitalize()

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:create_light:{cmd_id}")

    light_data = bpy.data.lights.new(name=name, type=bl_kind)
    obj = bpy.data.objects.new(name=name, object_data=light_data)
    bpy.context.scene.collection.objects.link(obj)

    loc = args.get("location") or (0.0, 0.0, 0.0)
    obj.location = tuple(float(x) for x in loc)
    rot = args.get("rotation")
    if rot is not None:
        obj.rotation_euler = tuple(float(x) for x in rot)

    color = args.get("color")
    if color is not None:
        light_data.color = tuple(float(x) for x in color)[:3]
    energy = args.get("energy")
    if energy is not None:
        light_data.energy = float(energy)

    size = args.get("size")
    if size is not None:
        if bl_kind == "SUN":
            # SUN uses `angle` (radians) instead of size.
            light_data.angle = float(size)
        elif bl_kind in {"POINT", "SPOT"}:
            light_data.shadow_soft_size = float(size)
        elif bl_kind == "AREA":
            light_data.size = float(size)

    if bl_kind == "SPOT":
        if args.get("spot_size") is not None:
            light_data.spot_size = float(args["spot_size"])
        if args.get("spot_blend") is not None:
            light_data.spot_blend = float(args["spot_blend"])
    if bl_kind == "AREA" and args.get("shape"):
        light_data.shape = args["shape"]

    return {
        "name": obj.name,
        "data": light_data.name,
        "kind": kind,
        "type": bl_kind,
        "location": list(obj.location),
        "energy": light_data.energy,
        "color": list(light_data.color),
    }


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------


def create_camera(args: dict) -> dict:
    """Create a camera datablock + object.

    Args:
        args: {
            "name": str | None,
            "location": [x,y,z] (default [0,0,0]),
            "rotation": [rx,ry,rz] | None (radians),
            "lens": float | None  (mm, perspective only),
            "ortho_scale": float | None,
            "type": "PERSP" | "ORTHO" | "PANO" (default PERSP),
            "sensor_width": float | None,
            "sensor_height": float | None,
            "clip_start": float | None,
            "clip_end": float | None,
            "set_active": bool (default False) — make this the active camera,
        }
    """
    name = args.get("name") or "Camera"
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:create_camera:{cmd_id}")

    cam_data = bpy.data.cameras.new(name=name)
    obj = bpy.data.objects.new(name=name, object_data=cam_data)
    bpy.context.scene.collection.objects.link(obj)

    obj.location = tuple(float(x) for x in (args.get("location") or (0.0, 0.0, 0.0)))
    rot = args.get("rotation")
    if rot is not None:
        obj.rotation_euler = tuple(float(x) for x in rot)

    cam_type = args.get("type")
    if cam_type:
        cam_data.type = cam_type
    if args.get("lens") is not None:
        cam_data.lens = float(args["lens"])
    if args.get("ortho_scale") is not None:
        cam_data.ortho_scale = float(args["ortho_scale"])
    if args.get("sensor_width") is not None:
        cam_data.sensor_width = float(args["sensor_width"])
    if args.get("sensor_height") is not None:
        cam_data.sensor_height = float(args["sensor_height"])
    if args.get("clip_start") is not None:
        cam_data.clip_start = float(args["clip_start"])
    if args.get("clip_end") is not None:
        cam_data.clip_end = float(args["clip_end"])

    if args.get("set_active"):
        bpy.context.scene.camera = obj

    return {
        "name": obj.name,
        "data": cam_data.name,
        "type": cam_data.type,
        "lens": cam_data.lens,
        "is_active": bpy.context.scene.camera is obj,
    }


def set_active_camera(args: dict) -> dict:
    """Set the active scene camera by object name."""
    name = args.get("name")
    if not name:
        raise ValueError("'name' is required")
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "CAMERA":
        raise ValueError(f"object '{name}' is not a camera")
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:set_active_camera:{cmd_id}")
    bpy.context.scene.camera = obj
    return {"camera": name, "scene": bpy.context.scene.name}


# ---------------------------------------------------------------------------
# Empties
# ---------------------------------------------------------------------------

_EMPTY_DISPLAYS = {
    "PLAIN_AXES", "ARROWS", "SINGLE_ARROW", "CIRCLE", "CUBE",
    "SPHERE", "CONE", "IMAGE",
}


def create_empty(args: dict) -> dict:
    """Create an empty (controller / parent) object.

    Args:
        args: {
            "name": str | None,
            "location": [x,y,z],
            "rotation": [rx,ry,rz] | None,
            "scale": [sx,sy,sz] | None,
            "display": "PLAIN_AXES"|"ARROWS"|"CUBE"|"SPHERE"|"CIRCLE"|... (default PLAIN_AXES),
            "size": float (default 1.0),
        }
    """
    name = args.get("name") or "Empty"
    display = args.get("display") or "PLAIN_AXES"
    if display not in _EMPTY_DISPLAYS:
        raise ValueError(
            f"display must be one of {sorted(_EMPTY_DISPLAYS)} (got '{display}')"
        )

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:create_empty:{cmd_id}")

    obj = bpy.data.objects.new(name=name, object_data=None)
    obj.empty_display_type = display
    obj.empty_display_size = float(args.get("size", 1.0))
    obj.location = tuple(float(x) for x in (args.get("location") or (0.0, 0.0, 0.0)))
    if args.get("rotation") is not None:
        obj.rotation_euler = tuple(float(x) for x in args["rotation"])
    if args.get("scale") is not None:
        obj.scale = tuple(float(x) for x in args["scale"])
    bpy.context.scene.collection.objects.link(obj)

    return {
        "name": obj.name,
        "display": obj.empty_display_type,
        "location": list(obj.location),
    }


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def create_text(args: dict) -> dict:
    """Create a 3D text object.

    Args:
        args: {
            "name": str | None,
            "body": str (default "Text"),
            "size": float (default 1.0),
            "extrude": float (default 0.0),
            "bevel_depth": float (default 0.0),
            "align_x": "LEFT"|"CENTER"|"RIGHT"|"JUSTIFY"|"FLUSH" | None,
            "align_y": "TOP_BASELINE"|"TOP"|"CENTER"|"BOTTOM_BASELINE"|"BOTTOM" | None,
            "location": [x,y,z],
            "rotation": [rx,ry,rz] | None,
        }
    """
    name = args.get("name") or "Text"
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:create_text:{cmd_id}")

    text_data = bpy.data.curves.new(name=name, type="FONT")
    text_data.body = str(args.get("body", "Text"))
    text_data.size = float(args.get("size", 1.0))
    text_data.extrude = float(args.get("extrude", 0.0))
    text_data.bevel_depth = float(args.get("bevel_depth", 0.0))
    if args.get("align_x"):
        text_data.align_x = args["align_x"]
    if args.get("align_y"):
        text_data.align_y = args["align_y"]

    obj = bpy.data.objects.new(name=name, object_data=text_data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = tuple(float(x) for x in (args.get("location") or (0.0, 0.0, 0.0)))
    if args.get("rotation") is not None:
        obj.rotation_euler = tuple(float(x) for x in args["rotation"])

    return {
        "name": obj.name,
        "data": text_data.name,
        "body": text_data.body,
        "size": text_data.size,
        "location": list(obj.location),
    }


# ---------------------------------------------------------------------------
# Curves (Bezier / NURBS / Poly)
# ---------------------------------------------------------------------------

_CURVE_KINDS = {"bezier": "BEZIER", "nurbs": "NURBS", "poly": "POLY"}


def create_curve(args: dict) -> dict:
    """Create a curve object from a list of control points.

    Args:
        args: {
            "name": str | None,
            "kind": "bezier" | "nurbs" | "poly",
            "points": [[x,y,z], ...]   # control points
            "closed": bool (default False) — close the spline (cyclic),
            "bevel_depth": float (default 0.0) — non-zero gives the curve thickness,
            "bevel_resolution": int (default 4),
            "fill_mode": "FULL"|"BACK"|"FRONT"|"HALF"|"NONE" | None,
            "location": [x,y,z],
            "rotation": [rx,ry,rz] | None,
        }
    """
    kind = (args.get("kind") or "bezier").lower()
    if kind not in _CURVE_KINDS:
        raise ValueError(
            f"kind must be one of {sorted(_CURVE_KINDS)} (got '{kind}')"
        )
    points = args.get("points") or []
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("'points' must be a list with at least 2 control points")
    name = args.get("name") or "Curve"

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:create_curve:{cmd_id}")

    curve_data = bpy.data.curves.new(name=name, type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.bevel_depth = float(args.get("bevel_depth", 0.0))
    curve_data.bevel_resolution = int(args.get("bevel_resolution", 4))
    if args.get("fill_mode"):
        curve_data.fill_mode = args["fill_mode"]

    spline = curve_data.splines.new(_CURVE_KINDS[kind])
    if kind == "bezier":
        spline.bezier_points.add(len(points) - 1)  # already has 1
        for bp, p in zip(spline.bezier_points, points):
            bp.co = (float(p[0]), float(p[1]), float(p[2]))
            bp.handle_left_type = "AUTO"
            bp.handle_right_type = "AUTO"
    else:
        spline.points.add(len(points) - 1)
        for sp, p in zip(spline.points, points):
            x, y, z = (float(p[0]), float(p[1]), float(p[2]))
            sp.co = (x, y, z, 1.0)
    spline.use_cyclic_u = bool(args.get("closed", False))

    obj = bpy.data.objects.new(name=name, object_data=curve_data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = tuple(float(x) for x in (args.get("location") or (0.0, 0.0, 0.0)))
    if args.get("rotation") is not None:
        obj.rotation_euler = tuple(float(x) for x in args["rotation"])

    return {
        "name": obj.name,
        "data": curve_data.name,
        "kind": kind,
        "point_count": len(points),
        "closed": spline.use_cyclic_u,
        "location": list(obj.location),
    }


# ---------------------------------------------------------------------------
# Armatures
# ---------------------------------------------------------------------------


def create_armature(args: dict) -> dict:
    """Create an armature object with optional initial bones.

    Bones are added in a temporary EDIT mode session and the object is
    returned to OBJECT mode before the call returns, so the caller doesn't
    inherit a mode change.

    Args:
        args: {
            "name": str | None,
            "location": [x,y,z],
            "bones": [
                {
                    "name": str,
                    "head": [x,y,z],
                    "tail": [x,y,z],
                    "parent": str | None,        # name of parent bone (must precede in list)
                    "use_connect": bool | None,  # connect to parent's tail
                    "roll": float | None,        # radians
                },
                ...
            ],
            "display_type": "OCTAHEDRAL"|"STICK"|"BBONE"|"ENVELOPE"|"WIRE" | None,
            "show_in_front": bool | None,
        }
    """
    name = args.get("name") or "Armature"
    bones_spec = args.get("bones") or []

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:create_armature:{cmd_id}")

    arm_data = bpy.data.armatures.new(name=name)
    obj = bpy.data.objects.new(name=name, object_data=arm_data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = tuple(float(x) for x in (args.get("location") or (0.0, 0.0, 0.0)))

    if args.get("display_type"):
        arm_data.display_type = args["display_type"]
    if args.get("show_in_front") is not None:
        obj.show_in_front = bool(args["show_in_front"])

    created_bones: list[str] = []
    if bones_spec:
        # We need to be in EDIT mode to add EditBones. Make this object active.
        prev_active = bpy.context.view_layer.objects.active
        prev_mode = bpy.context.mode
        try:
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            if prev_mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="EDIT")
            ebones = arm_data.edit_bones
            for spec in bones_spec:
                bname = spec.get("name")
                if not bname:
                    continue
                eb = ebones.new(bname)
                eb.head = tuple(float(x) for x in (spec.get("head") or (0.0, 0.0, 0.0)))
                eb.tail = tuple(float(x) for x in (spec.get("tail") or (0.0, 1.0, 0.0)))
                if spec.get("roll") is not None:
                    eb.roll = float(spec["roll"])
                pname = spec.get("parent")
                if pname:
                    parent = ebones.get(pname)
                    if parent is not None:
                        eb.parent = parent
                        if spec.get("use_connect"):
                            eb.use_connect = True
                created_bones.append(bname)
        finally:
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass
            if prev_active is not None:
                bpy.context.view_layer.objects.active = prev_active

    return {
        "name": obj.name,
        "data": arm_data.name,
        "bones_created": created_bones,
        "bone_count": len(arm_data.bones),
        "location": list(obj.location),
    }


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def load_image(args: dict) -> dict:
    """Load an image from disk into bpy.data.images.

    Path is expected to have been pre-validated by the policy layer.

    Args:
        args: {
            "path": str,
            "name": str | None,        # default: basename of path
            "check_existing": bool (default True) — return existing if already loaded,
            "pack": bool (default False) — pack pixel data into the .blend,
            "alpha_mode": "STRAIGHT"|"PREMUL"|"CHANNEL_PACKED"|"NONE" | None,
            "colorspace": str | None,  # e.g. "Non-Color" for normal/roughness maps
        }
    """
    path = args.get("path")
    if not path:
        raise ValueError("'path' is required")
    if not os.path.isfile(path):
        raise ValueError(f"file not found: {path}")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:load_image:{cmd_id}")

    img = bpy.data.images.load(path, check_existing=bool(args.get("check_existing", True)))
    if args.get("name"):
        img.name = args["name"]
    if args.get("alpha_mode"):
        img.alpha_mode = args["alpha_mode"]
    if args.get("colorspace"):
        try:
            img.colorspace_settings.name = args["colorspace"]
        except Exception as e:  # noqa: BLE001
            return {
                "name": img.name, "filepath": img.filepath,
                "size": list(img.size),
                "warning": f"colorspace '{args['colorspace']}' rejected: {e}",
            }
    if args.get("pack"):
        img.pack()

    return {
        "name": img.name,
        "filepath": img.filepath,
        "size": [img.size[0], img.size[1]],
        "channels": img.channels,
        "is_packed": bool(img.packed_file),
    }


def create_image(args: dict) -> dict:
    """Create a blank image datablock.

    Args:
        args: {
            "name": str (required),
            "width": int (default 1024),
            "height": int (default 1024),
            "color": [r,g,b,a] (default [0,0,0,1]),
            "alpha": bool (default True),
            "float": bool (default False) — 32-bit float buffer,
            "is_data": bool (default False) — non-color data (sets Non-Color colorspace),
        }
    """
    name = args.get("name")
    if not name:
        raise ValueError("'name' is required")
    w = int(args.get("width", 1024))
    h = int(args.get("height", 1024))
    color = args.get("color") or (0.0, 0.0, 0.0, 1.0)
    color4 = tuple(float(x) for x in color)
    if len(color4) == 3:
        color4 = (color4[0], color4[1], color4[2], 1.0)

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:create_image:{cmd_id}")

    img = bpy.data.images.new(
        name=name,
        width=w, height=h,
        alpha=bool(args.get("alpha", True)),
        float_buffer=bool(args.get("float", False)),
    )
    img.generated_color = color4
    if args.get("is_data"):
        try:
            img.colorspace_settings.name = "Non-Color"
        except Exception:
            pass
    return {
        "name": img.name,
        "size": [img.size[0], img.size[1]],
        "channels": img.channels,
        "is_float": img.is_float,
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_capability("create_light", create_light)
register_capability("create_camera", create_camera)
register_capability("set_active_camera", set_active_camera)
register_capability("create_empty", create_empty)
register_capability("create_text", create_text)
register_capability("create_curve", create_curve)
register_capability("create_armature", create_armature)
register_capability("load_image", load_image)
register_capability("create_image", create_image)
