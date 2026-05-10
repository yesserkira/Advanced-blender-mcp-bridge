"""Rename any datablock — object, material, mesh, image, world, etc."""

from __future__ import annotations

import bpy

from . import register_capability


_DATA_KINDS = {
    "object": "objects",
    "material": "materials",
    "mesh": "meshes",
    "light": "lights",
    "camera": "cameras",
    "collection": "collections",
    "image": "images",
    "node_group": "node_groups",
    "action": "actions",
    "scene": "scenes",
    "world": "worlds",
    "texture": "textures",
    "armature": "armatures",
    "curve": "curves",
}


def rename(args: dict) -> dict:
    """Rename a datablock.

    Args:
        args: {
            "kind": str,            # 'object', 'material', 'mesh', ...
            "from": str,            # current name
            "to": str,              # new name
        }
    """
    kind = args.get("kind")
    src = args.get("from") or args.get("old") or args.get("current")
    dst = args.get("to") or args.get("new") or args.get("name")
    if not kind or not src or not dst:
        raise ValueError("'kind', 'from', and 'to' are required")

    coll_name = _DATA_KINDS.get(kind)
    if coll_name is None:
        raise ValueError(
            f"Unknown kind: '{kind}'. Valid: {sorted(_DATA_KINDS)}"
        )

    coll = getattr(bpy.data, coll_name)
    item = coll.get(src)
    if item is None:
        raise ValueError(f"{kind} '{src}' not found")

    if dst in coll and coll.get(dst) is not item:
        raise ValueError(
            f"{kind} '{dst}' already exists (Blender would auto-suffix to '{dst}.001')"
        )

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:rename:{cmd_id}")

    item.name = dst
    return {
        "kind": kind,
        "from": src,
        "to": item.name,  # actual name (Blender may suffix on collision)
        "renamed": item.name == dst,
    }


register_capability("rename", rename)
