"""scene.snapshot — compact JSON snapshot of the scene.

Designed to be served as the MCP resource ``blender://scene/current``. The
goal is a small (≤ ~30 KB for typical scenes) digest the AI client can pull
each turn instead of issuing many `query`/`list` calls.

Stable across no-op invocations: the `hash` field is sha256 over the
canonical JSON of every other field, so clients can skip identical reads.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import bpy

from . import register_capability
from ._helpers import vec


# Hard cap to keep payloads bounded. When exceeded, we truncate the objects
# list and add `truncated: true` plus a `total_objects` count. Callers can
# fall back to the existing `list` tool with filters for the full set.
DEFAULT_MAX_OBJECTS = 500


def _object_summary(obj) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": obj.name,
        "type": obj.type,
        "visible": bool(obj.visible_get()) if hasattr(obj, "visible_get") else True,
        "location": vec(obj.location),
        "rotation_euler": vec(obj.rotation_euler),
        "scale": vec(obj.scale),
    }
    if obj.parent is not None:
        out["parent"] = obj.parent.name
    # Polygon count is the most asked-for stat; cheap when data is a Mesh.
    data = obj.data
    if obj.type == "MESH" and data is not None and hasattr(data, "polygons"):
        out["polys"] = len(data.polygons)
    if obj.type == "MESH" and data is not None and getattr(data, "materials", None):
        mats = [m.name for m in data.materials if m is not None]
        if mats:
            out["materials"] = mats
    if obj.type == "LIGHT" and data is not None:
        out["light_type"] = data.type
        out["energy"] = float(getattr(data, "energy", 0.0))
    if obj.type == "CAMERA" and data is not None:
        out["lens"] = float(getattr(data, "lens", 0.0))
    return out


def _collection_tree(coll) -> dict[str, Any]:
    return {
        "name": coll.name,
        "objects": [o.name for o in coll.objects],
        "children": [_collection_tree(c) for c in coll.children],
    }


def _render_summary(scene) -> dict[str, Any]:
    r = scene.render
    out: dict[str, Any] = {
        "engine": r.engine,
        "resolution": [int(r.resolution_x), int(r.resolution_y)],
        "resolution_percentage": int(r.resolution_percentage),
        "fps": int(r.fps),
    }
    cyc = getattr(scene, "cycles", None)
    if cyc is not None and r.engine == "CYCLES":
        out["samples"] = int(getattr(cyc, "samples", 0))
    eev = getattr(scene, "eevee", None)
    if eev is not None and r.engine.startswith("BLENDER_EEVEE"):
        out["samples"] = int(getattr(eev, "taa_render_samples", 0))
    return out


def _stable_hash(data: dict) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"),
                           default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def scene_snapshot(args: dict) -> dict[str, Any]:
    """Return a compact, hash-stable snapshot of the active scene.

    Args:
        args: optional ``{"max_objects": int, "summary": bool}``.
              If ``summary`` is True, returns counts only (no per-object data).

    Returns:
        Dict with ``frame``, ``selection``, ``active_camera``, ``objects``,
        ``collections``, ``materials``, ``render``, ``hash``, plus
        ``truncated`` / ``total_objects`` if the cap kicked in.
    """
    scene = bpy.context.scene
    summary_only = bool(args.get("summary"))
    max_objects = int(args.get("max_objects", DEFAULT_MAX_OBJECTS))

    selection = [o.name for o in bpy.context.selected_objects]
    active = bpy.context.view_layer.objects.active
    active_name = active.name if active is not None else None

    all_objects = list(scene.objects)
    truncated = False
    if not summary_only and len(all_objects) > max_objects:
        objects_view = all_objects[:max_objects]
        truncated = True
    else:
        objects_view = all_objects

    payload: dict[str, Any] = {
        "version": 1,
        "scene": scene.name,
        "frame": int(scene.frame_current),
        "frame_range": [int(scene.frame_start), int(scene.frame_end)],
        "active_camera": scene.camera.name if scene.camera is not None else None,
        "active_object": active_name,
        "selection": selection,
        "render": _render_summary(scene),
        "counts": {
            "objects": len(all_objects),
            "materials": len(bpy.data.materials),
            "meshes": len(bpy.data.meshes),
            "lights": len(bpy.data.lights),
            "cameras": len(bpy.data.cameras),
            "collections": len(bpy.data.collections),
            "node_groups": len(bpy.data.node_groups),
        },
    }

    if not summary_only:
        payload["objects"] = [_object_summary(o) for o in objects_view]
        payload["collections"] = _collection_tree(scene.collection)
        payload["materials"] = [
            {"name": m.name, "users": int(m.users)} for m in bpy.data.materials
        ]

    if truncated:
        payload["truncated"] = True
        payload["total_objects"] = len(all_objects)
        payload["max_objects"] = max_objects

    payload["hash"] = _stable_hash(payload)
    return payload


register_capability("scene.snapshot", scene_snapshot)
