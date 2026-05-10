"""Selection management — explicit control of Blender's selection state.

Many bpy operators (object.duplicate, object.join, object.shade_smooth,
mesh.unwrap, ...) silently CANCEL when nothing is selected or the wrong
thing is active. These helpers fix the most common workflow gap.
"""

from __future__ import annotations

import bpy

from . import register_capability
from ._helpers import get_object, push_undo, ensure_object_mode


def deselect_all(args: dict) -> dict:
    """Deselect every object in the scene."""
    ensure_object_mode()
    push_undo("deselect_all", args)
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        # Fallback: iterate
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
    return {"selected": []}


def select(args: dict) -> dict:
    """Select one or more objects.

    Args:
        objects: list[str] — object names to select
        additive: bool — if False (default), deselects others first
        active: str | None — name to make active (default: last in list)
    """
    names = args.get("objects") or []
    if isinstance(names, str):
        names = [names]
    if not names:
        raise ValueError("'objects' is required (list of names)")
    additive = bool(args.get("additive", False))
    active_name = args.get("active")

    objs = [get_object(n) for n in names]

    ensure_object_mode()
    push_undo("select", args)

    if not additive:
        for o in bpy.context.view_layer.objects:
            o.select_set(False)

    for o in objs:
        try:
            o.select_set(True)
        except RuntimeError as e:
            # Object hidden in viewport can't be selected
            raise ValueError(f"Cannot select '{o.name}': {e}")

    if active_name is None:
        active_obj = objs[-1]
    else:
        active_obj = get_object(active_name)
        active_obj.select_set(True)
    bpy.context.view_layer.objects.active = active_obj

    return {
        "selected": [o.name for o in bpy.context.selected_objects],
        "active": bpy.context.view_layer.objects.active.name,
    }


def set_active(args: dict) -> dict:
    """Set the active object (does NOT change selection unless `select=True`)."""
    name = args.get("object")
    if not name:
        raise ValueError("'object' is required")
    obj = get_object(name)
    push_undo("set_active", args)
    if args.get("select"):
        try:
            obj.select_set(True)
        except RuntimeError:
            pass
    bpy.context.view_layer.objects.active = obj
    return {"active": obj.name}


def select_all(args: dict) -> dict:
    """Select all objects, optionally filtered by type.

    Args:
        type: 'MESH' | 'LIGHT' | 'CAMERA' | 'EMPTY' | 'CURVE' | ... (optional)
    """
    type_filter = args.get("type")
    ensure_object_mode()
    push_undo("select_all", args)
    selected: list[str] = []
    for o in bpy.context.view_layer.objects:
        if type_filter and o.type != type_filter:
            o.select_set(False)
            continue
        try:
            o.select_set(True)
            selected.append(o.name)
        except RuntimeError:
            pass
    return {"selected": selected, "count": len(selected)}


register_capability("select", select)
register_capability("deselect_all", deselect_all)
register_capability("set_active", set_active)
register_capability("select_all", select_all)
