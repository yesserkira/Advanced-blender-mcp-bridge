"""Asset import / link / list — supports the full set of Blender importers.

Path-jail enforced by the MCP server (which resolves and validates against
policy.allowed_roots before forwarding).
"""

from __future__ import annotations

import os
from pathlib import Path

import bpy

from . import register_capability


_FORMAT_BY_EXT = {
    ".blend": "blend",
    ".glb": "gltf",
    ".gltf": "gltf",
    ".fbx": "fbx",
    ".obj": "obj",
    ".usd": "usd",
    ".usda": "usd",
    ".usdc": "usd",
    ".usdz": "usd",
    ".stl": "stl",
    ".ply": "ply",
    ".abc": "alembic",
    ".x3d": "x3d",
    ".dae": "dae",
    ".svg": "svg",
}


def _detect_format(path: str, override: str | None) -> str:
    if override:
        return override.lower().lstrip(".")
    ext = Path(path).suffix.lower()
    fmt = _FORMAT_BY_EXT.get(ext)
    if fmt is None:
        raise ValueError(f"Cannot detect format from extension '{ext}'. "
                         f"Pass format= explicitly. Known: {sorted(set(_FORMAT_BY_EXT.values()))}")
    return fmt


def import_asset(args: dict) -> dict:
    """Import an asset file into the scene.

    Args:
        args: {
            "path": str (already validated by server),
            "format": str | None,
            "collection": str | None,
        }
    """
    path = args.get("path")
    if not path:
        raise ValueError("'path' is required")
    if not os.path.isfile(path):
        raise ValueError(f"file not found: {path}")
    fmt = _detect_format(path, args.get("format"))

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:import_asset:{cmd_id}")

    before = set(bpy.data.objects.keys())

    if fmt == "blend":
        # Append all objects from the blend
        with bpy.data.libraries.load(path, link=False) as (data_from, data_to):
            data_to.objects = list(data_from.objects)
        for obj in data_to.objects:
            if obj is not None:
                bpy.context.scene.collection.objects.link(obj)
    elif fmt == "gltf":
        bpy.ops.import_scene.gltf(filepath=path)
    elif fmt == "fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif fmt == "obj":
        # Blender 4.x has bpy.ops.wm.obj_import
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=path)
        else:
            bpy.ops.import_scene.obj(filepath=path)
    elif fmt == "usd":
        bpy.ops.wm.usd_import(filepath=path)
    elif fmt == "stl":
        if hasattr(bpy.ops.wm, "stl_import"):
            bpy.ops.wm.stl_import(filepath=path)
        else:
            bpy.ops.import_mesh.stl(filepath=path)
    elif fmt == "ply":
        if hasattr(bpy.ops.wm, "ply_import"):
            bpy.ops.wm.ply_import(filepath=path)
        else:
            bpy.ops.import_mesh.ply(filepath=path)
    elif fmt == "alembic":
        bpy.ops.wm.alembic_import(filepath=path)
    elif fmt == "x3d":
        bpy.ops.import_scene.x3d(filepath=path)
    elif fmt == "dae":
        bpy.ops.wm.collada_import(filepath=path)
    elif fmt == "svg":
        bpy.ops.import_curve.svg(filepath=path)
    else:
        raise ValueError(f"Unsupported format: {fmt}")

    after = set(bpy.data.objects.keys())
    new_names = sorted(after - before)

    # Move into collection if requested
    coll_name = args.get("collection")
    if coll_name and new_names:
        target = bpy.data.collections.get(coll_name)
        if target is None:
            target = bpy.data.collections.new(coll_name)
            bpy.context.scene.collection.children.link(target)
        for n in new_names:
            obj = bpy.data.objects.get(n)
            if obj is None:
                continue
            for c in obj.users_collection:
                try:
                    c.objects.unlink(obj)
                except Exception:
                    pass
            target.objects.link(obj)

    return {
        "format": fmt,
        "path": path,
        "imported_objects": new_names,
        "count": len(new_names),
    }


register_capability("import_asset", import_asset)


def link_blend(args: dict) -> dict:
    """Link or append datablocks from another .blend file.

    Args:
        args: {
            "path": str,
            "datablocks": [{"type": str, "name": str}, ...],
            "link": bool (default True; False = append),
        }
    """
    path = args.get("path")
    datablocks = args.get("datablocks") or []
    link = bool(args.get("link", True))
    if not path or not os.path.isfile(path):
        raise ValueError(f"file not found: {path}")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:link_blend:{cmd_id}")

    by_type: dict[str, list[str]] = {}
    for db in datablocks:
        by_type.setdefault(db["type"], []).append(db["name"])

    loaded: dict[str, list[str]] = {}
    with bpy.data.libraries.load(path, link=link) as (data_from, data_to):
        for tname, names in by_type.items():
            attr = _datablock_collection_attr(tname)
            available = list(getattr(data_from, attr))
            wanted = [n for n in names if n in available]
            setattr(data_to, attr, wanted)
            loaded[tname] = wanted

    # Auto-instance Object datablocks into the current scene if appended
    if not link:
        for obj in data_to.objects:  # type: ignore[attr-defined]
            if obj is not None:
                bpy.context.scene.collection.objects.link(obj)

    return {"path": path, "link": link, "loaded": loaded}


register_capability("link_blend", link_blend)


def _datablock_collection_attr(type_name: str) -> str:
    mapping = {
        "Object": "objects",
        "Material": "materials",
        "Mesh": "meshes",
        "Light": "lights",
        "Camera": "cameras",
        "Collection": "collections",
        "Image": "images",
        "Texture": "textures",
        "NodeTree": "node_groups",
        "Action": "actions",
        "World": "worlds",
        "Scene": "scenes",
        "Curve": "curves",
        "Armature": "armatures",
    }
    if type_name not in mapping:
        raise ValueError(f"Unknown datablock type: {type_name}")
    return mapping[type_name]


def list_assets(args: dict) -> dict:
    """Enumerate importable asset files in a directory.

    Args:
        args: {"directory": str, "recursive": bool (default False)}
    """
    directory = args.get("directory")
    recursive = bool(args.get("recursive", False))
    if not directory or not os.path.isdir(directory):
        raise ValueError(f"directory not found: {directory}")

    found = []
    if recursive:
        for root, _, files in os.walk(directory):
            for fn in files:
                _maybe_add(found, os.path.join(root, fn))
    else:
        for fn in os.listdir(directory):
            full = os.path.join(directory, fn)
            if os.path.isfile(full):
                _maybe_add(found, full)

    return {"directory": directory, "count": len(found), "assets": found}


def _maybe_add(out: list, path: str):
    ext = Path(path).suffix.lower()
    if ext not in _FORMAT_BY_EXT:
        return
    entry: dict = {"path": path, "format": _FORMAT_BY_EXT[ext], "name": Path(path).name}
    if ext == ".blend":
        try:
            with bpy.data.libraries.load(path, link=True) as (data_from, _):
                entry["objects"] = list(data_from.objects)[:50]
                entry["materials"] = list(data_from.materials)[:50]
        except Exception:
            pass
    out.append(entry)


register_capability("list_assets", list_assets)
