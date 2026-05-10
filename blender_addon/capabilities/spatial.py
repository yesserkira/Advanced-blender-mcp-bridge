"""Spatial helper tools — semantic positioning instead of raw coordinates.

These let the AI say "put the lamp above the table" rather than computing
bounding boxes manually with execute_python.
"""

from __future__ import annotations

import math

from mathutils import Vector

from . import register_capability
from ._helpers import get_object, push_undo, world_bbox, bbox_center


# ---------------------------------------------------------------------------
# place_above — position object above another (sit on top)
# ---------------------------------------------------------------------------


def place_above(args: dict) -> dict:
    """Place an object so it sits flush on top of a target.

    Args:
        object: name of object to move
        target: name of target object (or "ground" for z=0)
        gap: optional vertical gap between them (default 0.0)
        align_xy: 'center' (default) | 'keep'  — center over target XY or keep XY
    """
    obj_name = args.get("object")
    tgt_name = args.get("target")
    gap = float(args.get("gap", 0.0))
    align_xy = args.get("align_xy", "center")
    if not obj_name or not tgt_name:
        raise ValueError("'object' and 'target' are required")

    obj = get_object(obj_name)
    obj_mn, obj_mx = world_bbox(obj)
    obj_h_below = obj.location.z - obj_mn.z  # how far below origin is the bbox bottom

    if tgt_name == "ground":
        new_z = (obj_h_below) + gap
        new_xy = (obj.location.x, obj.location.y)
    else:
        tgt = get_object(tgt_name)
        tgt_mn, tgt_mx = world_bbox(tgt)
        new_z = tgt_mx.z + obj_h_below + gap
        if align_xy == "center":
            tgt_center = bbox_center(tgt)
            obj_center = bbox_center(obj)
            offset = tgt_center.xy - obj_center.xy
            new_xy = (obj.location.x + offset.x, obj.location.y + offset.y)
        else:
            new_xy = (obj.location.x, obj.location.y)

    push_undo("place_above", args)
    obj.location = (new_xy[0], new_xy[1], new_z)
    return {
        "object": obj.name,
        "target": tgt_name,
        "new_location": [round(obj.location.x, 4), round(obj.location.y, 4), round(obj.location.z, 4)],
    }


register_capability("place_above", place_above)


# ---------------------------------------------------------------------------
# align_to — align object's center/edge to another's
# ---------------------------------------------------------------------------


def align_to(args: dict) -> dict:
    """Align object to target along one or more axes.

    Args:
        object: name of object to move
        target: name of target object
        axes: list from {'x','y','z'} — which axes to align (default all)
        mode: 'center' (default) | 'min' | 'max'
              center: centers match
              min:   aligns the lower bbox edge
              max:   aligns the upper bbox edge
    """
    obj_name = args.get("object")
    tgt_name = args.get("target")
    axes = args.get("axes") or ["x", "y", "z"]
    mode = args.get("mode", "center")
    if not obj_name or not tgt_name:
        raise ValueError("'object' and 'target' are required")

    obj = get_object(obj_name)
    tgt = get_object(tgt_name)

    obj_mn, obj_mx = world_bbox(obj)
    obj_center = bbox_center(obj)
    tgt_mn, tgt_mx = world_bbox(tgt)
    tgt_center = bbox_center(tgt)

    new_loc = list(obj.location)
    axis_idx = {"x": 0, "y": 1, "z": 2}
    for ax in axes:
        i = axis_idx[ax]
        if mode == "center":
            delta = tgt_center[i] - obj_center[i]
        elif mode == "min":
            delta = tgt_mn[i] - obj_mn[i]
        elif mode == "max":
            delta = tgt_mx[i] - obj_mx[i]
        else:
            raise ValueError(f"Unknown mode: {mode}")
        new_loc[i] = obj.location[i] + delta

    push_undo("align_to", args)
    obj.location = tuple(new_loc)
    return {
        "object": obj.name,
        "target": tgt.name,
        "new_location": [round(x, 4) for x in new_loc],
    }


register_capability("align_to", align_to)


# ---------------------------------------------------------------------------
# array_around — duplicate object N times around a center
# ---------------------------------------------------------------------------


def array_around(args: dict) -> dict:
    """Duplicate an object N times in a circle around a center.

    Args:
        object: name of object to duplicate
        count: number of copies (including the original) — default 6
        radius: circle radius — default 2.0
        center: [x, y, z] world center — default origin
        axis: 'z' (default) | 'x' | 'y' — rotation axis
        face_center: bool — rotate copies to face the center (default True)
        name_prefix: str — prefix for new objects (default `<original>_arr`)
    """
    obj_name = args.get("object")
    count = max(1, int(args.get("count", 6)))
    radius = float(args.get("radius", 2.0))
    center = args.get("center") or [0.0, 0.0, 0.0]
    axis = args.get("axis", "z")
    face_center = bool(args.get("face_center", True))
    prefix = args.get("name_prefix") or f"{obj_name}_arr"
    if not obj_name:
        raise ValueError("'object' is required")

    src = get_object(obj_name)
    cx, cy, cz = float(center[0]), float(center[1]), float(center[2])

    push_undo("array_around", args)

    created: list[str] = []
    for i in range(count):
        angle = (2 * math.pi * i) / count
        if axis == "z":
            pos = (cx + radius * math.cos(angle), cy + radius * math.sin(angle), cz)
            rot_z = angle + math.pi if face_center else 0.0
            rot = (src.rotation_euler.x, src.rotation_euler.y, rot_z)
        elif axis == "x":
            pos = (cx, cy + radius * math.cos(angle), cz + radius * math.sin(angle))
            rot_x = angle + math.pi if face_center else 0.0
            rot = (rot_x, src.rotation_euler.y, src.rotation_euler.z)
        elif axis == "y":
            pos = (cx + radius * math.cos(angle), cy, cz + radius * math.sin(angle))
            rot_y = angle + math.pi if face_center else 0.0
            rot = (src.rotation_euler.x, rot_y, src.rotation_euler.z)
        else:
            raise ValueError(f"axis must be x|y|z, got {axis!r}")

        if i == 0:
            # Reuse original for the first slot
            src.location = pos
            if face_center:
                src.rotation_euler = rot
            created.append(src.name)
            continue

        copy = src.copy()
        if src.data is not None:
            copy.data = src.data  # share mesh data (linked duplicate)
        copy.name = f"{prefix}_{i:02d}"
        copy.location = pos
        if face_center:
            copy.rotation_euler = rot
        # Link to same collections as original
        for coll in src.users_collection:
            coll.objects.link(copy)
        created.append(copy.name)

    return {
        "source": obj_name,
        "count": count,
        "radius": radius,
        "center": [cx, cy, cz],
        "axis": axis,
        "created": created,
    }


register_capability("array_around", array_around)


# ---------------------------------------------------------------------------
# distribute — evenly distribute objects along a line
# ---------------------------------------------------------------------------


def distribute(args: dict) -> dict:
    """Evenly distribute objects along a straight line between two points.

    Args:
        objects: list of object names (>=2) — first stays at start, last at end
        start: [x, y, z] start point (optional — defaults to first object's position)
        end: [x, y, z] end point (optional — defaults to last object's position)
    """
    names = args.get("objects") or []
    if len(names) < 2:
        raise ValueError("at least 2 objects required")

    objs = [get_object(n) for n in names]
    start = args.get("start")
    end = args.get("end")
    p0 = Vector(start) if start else Vector(objs[0].location)
    p1 = Vector(end) if end else Vector(objs[-1].location)

    push_undo("distribute", args)

    n = len(objs)
    placements: list[dict] = []
    for i, obj in enumerate(objs):
        t = i / (n - 1)
        new_pos = p0.lerp(p1, t)
        obj.location = new_pos
        placements.append({
            "name": obj.name,
            "location": [round(new_pos.x, 4), round(new_pos.y, 4), round(new_pos.z, 4)],
        })
    return {"placements": placements, "count": n}


register_capability("distribute", distribute)


# ---------------------------------------------------------------------------
# look_at — rotate object to face a target
# ---------------------------------------------------------------------------


def look_at(args: dict) -> dict:
    """Rotate an object so its -Z axis points at a target (camera/light convention).

    Args:
        object: name of object to rotate (typically a camera or light)
        target: name of target object — OR
        point: [x, y, z] world point to look at
        track_axis: 'NEG_Z' (default) | 'POS_Z' | 'NEG_X' | 'POS_X' | 'NEG_Y' | 'POS_Y'
        up_axis: 'Y' (default) | 'X' | 'Z' — which axis stays "up"
    """
    obj_name = args.get("object")
    tgt_name = args.get("target")
    point = args.get("point")
    track_axis = args.get("track_axis", "NEG_Z")
    up_axis = args.get("up_axis", "Y")
    if not obj_name:
        raise ValueError("'object' is required")
    if not tgt_name and not point:
        raise ValueError("'target' or 'point' is required")

    obj = get_object(obj_name)
    if tgt_name:
        tgt = get_object(tgt_name)
        target_loc = bbox_center(tgt)
    else:
        target_loc = Vector(point)

    direction = target_loc - Vector(obj.location)
    if direction.length < 1e-6:
        raise ValueError("object and target are at the same position")

    # Use track_quat: maps the direction vector onto track_axis with up_axis upright
    quat = direction.to_track_quat(track_axis, up_axis)

    push_undo("look_at", args)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = quat
    obj.rotation_mode = "XYZ"  # convert back so users see Euler

    return {
        "object": obj.name,
        "looking_at": [round(target_loc.x, 4), round(target_loc.y, 4), round(target_loc.z, 4)],
        "rotation_euler": [round(x, 4) for x in obj.rotation_euler],
    }


register_capability("look_at", look_at)


# ---------------------------------------------------------------------------
# bbox_info — return world-space AABB of an object (read-only)
# ---------------------------------------------------------------------------


def bbox_info(args: dict) -> dict:
    """Return world-space axis-aligned bounding box of an object."""
    obj_name = args.get("object")
    if not obj_name:
        raise ValueError("'object' is required")
    obj = get_object(obj_name)
    mn, mx = world_bbox(obj)
    size = mx - mn
    return {
        "object": obj.name,
        "min": [round(mn.x, 4), round(mn.y, 4), round(mn.z, 4)],
        "max": [round(mx.x, 4), round(mx.y, 4), round(mx.z, 4)],
        "size": [round(size.x, 4), round(size.y, 4), round(size.z, 4)],
        "center": [
            round((mn.x + mx.x) * 0.5, 4),
            round((mn.y + mx.y) * 0.5, 4),
            round((mn.z + mx.z) * 0.5, 4),
        ],
    }


register_capability("bbox_info", bbox_info)
