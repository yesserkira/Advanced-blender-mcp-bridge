"""Collection management — create, delete, rename, move objects between."""

from __future__ import annotations

import bpy

from . import register_capability
from ._helpers import get_object, get_collection, push_undo


def create_collection(args: dict) -> dict:
    """Create a new collection.

    Args:
        name: str — collection name (must be unique)
        parent: str | None — parent collection (default: scene root)
    """
    name = args.get("name")
    if not name:
        raise ValueError("'name' is required")
    if name in bpy.data.collections:
        raise ValueError(f"Collection '{name}' already exists")
    parent_name = args.get("parent")

    push_undo("create_collection", args)

    coll = bpy.data.collections.new(name)
    if parent_name:
        parent = get_collection(parent_name)
        parent.children.link(coll)
    else:
        bpy.context.scene.collection.children.link(coll)

    return {"name": coll.name, "parent": parent_name or bpy.context.scene.collection.name}


def delete_collection(args: dict) -> dict:
    """Delete a collection.

    Args:
        name: str — collection name
        unlink_objects: bool — also remove objects from scene (default False, just unlinks from this collection)
    """
    name = args.get("name")
    if not name:
        raise ValueError("'name' is required")
    coll = get_collection(name)
    unlink_objects = bool(args.get("unlink_objects", False))

    push_undo("delete_collection", args)

    object_names = [o.name for o in coll.objects]

    if unlink_objects:
        for obj in list(coll.objects):
            # Remove from data if it has no other users
            if len(obj.users_collection) <= 1:
                bpy.data.objects.remove(obj, do_unlink=True)

    bpy.data.collections.remove(coll)
    return {"deleted": name, "objects_affected": object_names}


def move_to_collection(args: dict) -> dict:
    """Move object(s) into a collection.

    Args:
        objects: list[str] | str — object name(s)
        collection: str — destination collection name
        unlink_others: bool — remove from previous collections (default True)
    """
    raw = args.get("objects") or args.get("object")
    if raw is None:
        raise ValueError("'objects' or 'object' is required")
    names = [raw] if isinstance(raw, str) else list(raw)
    coll_name = args.get("collection")
    if not coll_name:
        raise ValueError("'collection' is required")
    coll = get_collection(coll_name)
    unlink_others = bool(args.get("unlink_others", True))

    push_undo("move_to_collection", args)

    moved: list[str] = []
    for name in names:
        obj = get_object(name)
        if unlink_others:
            for c in list(obj.users_collection):
                if c is not coll:
                    c.objects.unlink(obj)
        if obj.name not in coll.objects:
            coll.objects.link(obj)
        moved.append(obj.name)

    return {"moved": moved, "collection": coll.name, "count": len(moved)}


def list_collections(args: dict) -> dict:
    """List all collections with member counts."""
    out: list[dict] = []
    for c in bpy.data.collections:
        out.append({
            "name": c.name,
            "object_count": len(c.objects),
            "child_collections": [child.name for child in c.children],
        })
    return {"collections": out, "count": len(out)}


register_capability("create_collection", create_collection)
register_capability("delete_collection", delete_collection)
register_capability("move_to_collection", move_to_collection)
register_capability("list_collections", list_collections)
