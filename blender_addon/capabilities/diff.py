"""scene_diff — track what changed in the scene between calls.

Maintains in-memory hash snapshots keyed by snapshot_id. First call returns
a baseline; subsequent calls report added/removed/modified objects and which
fields changed.
"""

from __future__ import annotations

import secrets

import bpy

from . import register_capability


_SNAPSHOTS: dict[str, dict[str, dict]] = {}


def _capture() -> dict[str, dict]:
    """Capture a per-object snapshot of the current scene."""
    snap: dict[str, dict] = {}
    for obj in bpy.context.scene.objects:
        info = {
            "type": obj.type,
            "location": [round(v, 6) for v in obj.location],
            "rotation_euler": [round(v, 6) for v in obj.rotation_euler],
            "scale": [round(v, 6) for v in obj.scale],
            "hide_render": obj.hide_render,
            "hide_viewport": obj.hide_viewport,
            "parent": obj.parent.name if obj.parent else None,
            "collection": (obj.users_collection[0].name if obj.users_collection else None),
            "modifiers": [{"name": m.name, "type": m.type} for m in obj.modifiers],
            "materials": [
                slot.material.name if slot.material else None
                for slot in obj.material_slots
            ],
        }
        if obj.type == "MESH" and obj.data is not None:
            info["mesh"] = {
                "vertices": len(obj.data.vertices),
                "polygons": len(obj.data.polygons),
            }
        snap[obj.name] = info
    return snap


def scene_diff(args: dict) -> dict:
    """Diff against a stored snapshot (creating one if not provided).

    Args:
        args: {"snapshot_id": str | None}
    """
    snap_id = args.get("snapshot_id")
    current = _capture()

    if not snap_id or snap_id not in _SNAPSHOTS:
        new_id = snap_id or secrets.token_urlsafe(8)
        _SNAPSHOTS[new_id] = current
        return {
            "snapshot_id": new_id,
            "baseline": True,
            "object_count": len(current),
        }

    prev = _SNAPSHOTS[snap_id]
    added = sorted(set(current) - set(prev))
    removed = sorted(set(prev) - set(current))
    modified = []
    common = set(current) & set(prev)
    for name in sorted(common):
        a = prev[name]
        b = current[name]
        changed_fields = [k for k in a.keys() | b.keys() if a.get(k) != b.get(k)]
        if changed_fields:
            modified.append({"name": name, "fields": changed_fields})

    # Update baseline so consecutive calls give incremental diffs
    _SNAPSHOTS[snap_id] = current

    return {
        "snapshot_id": snap_id,
        "baseline": False,
        "added": added,
        "removed": removed,
        "modified": modified,
        "object_count": len(current),
    }


register_capability("scene_diff", scene_diff)
