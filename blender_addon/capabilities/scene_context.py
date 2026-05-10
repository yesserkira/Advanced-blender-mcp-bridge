"""scene.context — lightweight scene orientation snapshot.

Designed for the `ping` MCP tool. Returns ~500 bytes of high-signal context
the AI can use to plan operations without issuing many queries.
"""

from __future__ import annotations

from typing import Any

import bpy

from . import register_capability
from ._helpers import vec


def scene_context(args: dict) -> dict[str, Any]:
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    active = view_layer.objects.active if view_layer else None
    # `bpy.context.selected_objects` is the canonical way to read selection
    # (LayerObjects has no `.selected` attribute).
    try:
        selected = [o.name for o in bpy.context.selected_objects]
    except AttributeError:
        selected = []

    # Counts (cheap)
    objects = list(bpy.data.objects)
    counts = {
        "objects": len(objects),
        "meshes": sum(1 for o in objects if o.type == "MESH"),
        "lights": sum(1 for o in objects if o.type == "LIGHT"),
        "cameras": sum(1 for o in objects if o.type == "CAMERA"),
        "empties": sum(1 for o in objects if o.type == "EMPTY"),
        "materials": len(bpy.data.materials),
        "collections": len(bpy.data.collections),
        "node_groups": len(bpy.data.node_groups),
        "images": len(bpy.data.images),
    }

    # Top-level objects (by name) — just first 20 for orientation
    obj_names = [o.name for o in objects[:20]]

    # Camera info (the AI often needs to render — cameras matter)
    active_camera = scene.camera
    camera_info: dict[str, Any] | None = None
    if active_camera is not None:
        camera_info = {
            "name": active_camera.name,
            "location": vec(active_camera.location, decimals=4),
        }

    # World scale
    units = scene.unit_settings
    units_info = {
        "system": units.system,           # 'NONE' | 'METRIC' | 'IMPERIAL'
        "length_unit": units.length_unit,  # e.g. 'METERS', 'FEET'
        "scale_length": round(units.scale_length, 4),
    }

    # Render
    r = scene.render
    render_info = {
        "engine": r.engine,
        "resolution": [int(r.resolution_x), int(r.resolution_y)],
        "fps": int(r.fps),
    }

    out: dict[str, Any] = {
        "blender_version": ".".join(str(x) for x in bpy.app.version),
        "scene": {
            "name": scene.name,
            "frame_current": scene.frame_current,
            "frame_range": [scene.frame_start, scene.frame_end],
        },
        "render": render_info,
        "units": units_info,
        "counts": counts,
        "active_object": (
            {"name": active.name, "type": active.type, "location": vec(active.location, decimals=4)}
            if active else None
        ),
        "active_camera": camera_info,
        "selection": selected[:30],   # cap at 30
        "objects_preview": obj_names,  # first 20 names
    }
    if counts["objects"] > 20:
        out["objects_preview_truncated"] = True
    return out


register_capability("scene.context", scene_context)
