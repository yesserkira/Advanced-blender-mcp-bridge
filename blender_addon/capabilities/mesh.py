"""Mesh creation primitive (only). Edit operations belong in call_operator
or execute_python with bmesh."""

from __future__ import annotations

import bpy

from . import register_capability

PRIMITIVES = {
    "cube": "primitive_cube_add",
    "sphere": "primitive_uv_sphere_add",
    "cylinder": "primitive_cylinder_add",
    "plane": "primitive_plane_add",
    "cone": "primitive_cone_add",
    "torus": "primitive_torus_add",
    "monkey": "primitive_monkey_add",
    "ico_sphere": "primitive_ico_sphere_add",
    "circle": "primitive_circle_add",
    "grid": "primitive_grid_add",
}


def mesh_create_primitive(args: dict) -> dict:
    """Create a single mesh primitive.

    Args:
        args: {
            "kind": str (one of PRIMITIVES),
            "name": str | None,
            "location": [x,y,z] (default [0,0,0]),
            "rotation": [x,y,z] | None,
            "size": float (default 1.0),
        }
    """
    kind = args.get("kind")
    if kind not in PRIMITIVES:
        raise ValueError(
            f"Unknown primitive kind: {kind}. "
            f"Must be one of: {sorted(PRIMITIVES)}"
        )
    location = tuple(args.get("location") or (0, 0, 0))
    size = float(args.get("size", 1.0))
    if size <= 0:
        raise ValueError("size must be positive")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:mesh.create_primitive:{cmd_id}")

    op_fn = getattr(bpy.ops.mesh, PRIMITIVES[kind])
    if kind == "torus":
        op_fn(location=location, major_radius=size, minor_radius=size * 0.25)
    elif kind in {"cube", "plane", "grid", "monkey", "circle"}:
        op_fn(location=location, size=size)
    else:
        op_fn(location=location, radius=size)

    obj = bpy.context.active_object
    name = args.get("name")
    if name:
        obj.name = name

    rotation = args.get("rotation")
    if rotation:
        obj.rotation_euler = tuple(rotation)

    return {
        "name": obj.name,
        "kind": kind,
        "polys": len(obj.data.polygons),
        "vertices": len(obj.data.vertices),
        "location": list(obj.location),
    }


register_capability("mesh.create_primitive", mesh_create_primitive)
