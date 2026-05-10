"""Shared helpers for capability modules.

Avoids duplicating _get_object / _push_undo / _vec / _world_bbox across
every capability file.
"""

from __future__ import annotations

import bpy
from mathutils import Vector


def get_object(name: str):
    """Fetch object by name or raise ValueError with a helpful message."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        existing = [o.name for o in bpy.data.objects][:10]
        hint = f" Available: {existing}" if existing else " Scene is empty."
        raise ValueError(f"Object not found: {name}.{hint}")
    return obj


def get_collection(name: str):
    """Fetch collection by name or raise ValueError."""
    coll = bpy.data.collections.get(name)
    if coll is None:
        raise ValueError(f"Collection not found: {name}")
    return coll


def push_undo(label: str, args: dict) -> None:
    """Push an undo step tagged with the command ID."""
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:{label}:{cmd_id}")


def vec(v, decimals: int | None = None) -> list[float]:
    """Convert a Blender vector-like to a plain list of floats.

    Args:
        v: any iterable of numbers (Vector, tuple, list)
        decimals: if set, round each component to this many decimal places
    """
    try:
        if decimals is not None:
            return [round(float(x), decimals) for x in v]
        return [float(x) for x in v]
    except Exception:
        return []


def world_bbox(obj) -> tuple[Vector, Vector]:
    """Return (min_corner, max_corner) of the object's world-space AABB."""
    if not obj.bound_box:
        loc = Vector(obj.location)
        return loc, loc
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    mn = Vector((
        min(c.x for c in corners),
        min(c.y for c in corners),
        min(c.z for c in corners),
    ))
    mx = Vector((
        max(c.x for c in corners),
        max(c.y for c in corners),
        max(c.z for c in corners),
    ))
    return mn, mx


def bbox_center(obj) -> Vector:
    """Return the center of the object's world-space bounding box."""
    mn, mx = world_bbox(obj)
    return (mn + mx) * 0.5


def ensure_object_mode() -> None:
    """Switch to OBJECT mode if needed (selection ops require it)."""
    if bpy.context.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
