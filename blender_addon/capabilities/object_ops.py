"""Object lifecycle helpers: duplicate, set_visibility, set_parent, clear_parent.

These cover gaps that previously required bpy.ops with hand-managed selection
or set_property with deep RNA paths.
"""

from __future__ import annotations

import bpy

from . import register_capability
from ._helpers import get_object, push_undo


# ---------------------------------------------------------------------------
# duplicate_object
# ---------------------------------------------------------------------------


def duplicate_object(args: dict) -> dict:
    """Duplicate an object (no selection juggling required).

    Args:
        object: name of object to duplicate
        linked: bool — if True, share mesh/curve data (default False)
        name: str — name for new object (default '<orig>.copy')
        location_offset: [x,y,z] — offset from original (default [0,0,0])
        collection: str — collection to link to (default: source's collections)
    """
    src_name = args.get("object")
    if not src_name:
        raise ValueError("'object' is required")
    src = get_object(src_name)
    linked = bool(args.get("linked", False))
    new_name = args.get("name") or f"{src_name}.copy"
    offset = args.get("location_offset") or [0.0, 0.0, 0.0]
    coll_name = args.get("collection")

    push_undo("duplicate_object", args)

    copy = src.copy()
    if not linked and src.data is not None:
        copy.data = src.data.copy()
    elif linked and src.data is not None:
        copy.data = src.data
    copy.name = new_name
    copy.location = (
        src.location.x + float(offset[0]),
        src.location.y + float(offset[1]),
        src.location.z + float(offset[2]),
    )

    if coll_name:
        coll = bpy.data.collections.get(coll_name)
        if coll is None:
            raise ValueError(f"Collection not found: {coll_name}")
        coll.objects.link(copy)
    else:
        # Link to all collections that contain the source
        targets = list(src.users_collection)
        if not targets:
            targets = [bpy.context.scene.collection]
        for c in targets:
            c.objects.link(copy)

    return {
        "source": src_name,
        "new": copy.name,
        "linked_data": linked,
        "location": [round(copy.location.x, 4), round(copy.location.y, 4), round(copy.location.z, 4)],
    }


register_capability("duplicate_object", duplicate_object)


# ---------------------------------------------------------------------------
# set_visibility
# ---------------------------------------------------------------------------


def set_visibility(args: dict) -> dict:
    """Set viewport / render / select visibility on an object.

    Args:
        object: name (or 'objects': list of names for batch)
        viewport: bool | None — hide_viewport (None = leave alone)
        render: bool | None    — hide_render
        selectable: bool | None — hide_select
        show_in_viewport: bool | None — hide_set() temporary hide (eye icon)
    """
    names: list[str]
    if "objects" in args and args["objects"]:
        names = list(args["objects"])
    else:
        single = args.get("object")
        if not single:
            raise ValueError("'object' or 'objects' is required")
        names = [single]

    viewport = args.get("viewport")
    render = args.get("render")
    selectable = args.get("selectable")
    show_in_viewport = args.get("show_in_viewport")

    push_undo("set_visibility", args)

    results: list[dict] = []
    for name in names:
        obj = get_object(name)
        if viewport is not None:
            obj.hide_viewport = not bool(viewport)
        if render is not None:
            obj.hide_render = not bool(render)
        if selectable is not None:
            obj.hide_select = not bool(selectable)
        if show_in_viewport is not None:
            try:
                obj.hide_set(not bool(show_in_viewport))
            except Exception:
                pass
        results.append({
            "name": obj.name,
            "viewport": not obj.hide_viewport,
            "render": not obj.hide_render,
            "selectable": not obj.hide_select,
        })
    return {"objects": results}


register_capability("set_visibility", set_visibility)


# ---------------------------------------------------------------------------
# set_parent / clear_parent
# ---------------------------------------------------------------------------


def set_parent(args: dict) -> dict:
    """Parent one or more objects to a target.

    Args:
        child: str — child object name (or 'children': list)
        parent: str — parent object name
        keep_transform: bool — preserve world transform (default True)
        type: 'OBJECT' (default) | 'BONE' | 'VERTEX' | 'ARMATURE'
        bone: str | None — bone name (when type='BONE')
    """
    parent_name = args.get("parent")
    if not parent_name:
        raise ValueError("'parent' is required")
    parent = get_object(parent_name)

    if "children" in args and args["children"]:
        child_names = list(args["children"])
    else:
        single = args.get("child")
        if not single:
            raise ValueError("'child' or 'children' is required")
        child_names = [single]

    keep_transform = bool(args.get("keep_transform", True))
    parent_type = args.get("type", "OBJECT")
    bone = args.get("bone")

    push_undo("set_parent", args)

    results: list[dict] = []
    for name in child_names:
        child = get_object(name)
        # Capture world matrix before reparent (for keep_transform)
        world_mat = child.matrix_world.copy()
        child.parent = parent
        child.parent_type = parent_type
        if parent_type == "BONE" and bone:
            child.parent_bone = bone
        if keep_transform:
            # Reset parent inverse so the world transform is preserved
            child.matrix_parent_inverse = parent.matrix_world.inverted() @ world_mat @ child.matrix_basis.inverted()
        else:
            child.matrix_parent_inverse.identity()
        results.append({"child": child.name, "parent": parent.name})

    return {"parented": results, "count": len(results)}


def clear_parent(args: dict) -> dict:
    """Unparent one or more objects.

    Args:
        object: str (or 'objects': list)
        keep_transform: bool — preserve world transform (default True)
    """
    if "objects" in args and args["objects"]:
        names = list(args["objects"])
    else:
        single = args.get("object")
        if not single:
            raise ValueError("'object' or 'objects' is required")
        names = [single]

    keep_transform = bool(args.get("keep_transform", True))
    push_undo("clear_parent", args)

    cleared: list[str] = []
    for name in names:
        obj = get_object(name)
        if obj.parent is None:
            cleared.append(obj.name)
            continue
        if keep_transform:
            world_mat = obj.matrix_world.copy()
            obj.parent = None
            obj.matrix_world = world_mat
        else:
            obj.parent = None
            obj.matrix_parent_inverse.identity()
        cleared.append(obj.name)
    return {"cleared": cleared, "count": len(cleared)}


register_capability("set_parent", set_parent)
register_capability("clear_parent", clear_parent)
