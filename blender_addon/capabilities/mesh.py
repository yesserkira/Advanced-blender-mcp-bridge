"""Mesh creation capability."""

import bpy

from . import register_capability

PRIMITIVES = {
    "cube": "primitive_cube_add",
    "sphere": "primitive_uv_sphere_add",
    "cylinder": "primitive_cylinder_add",
    "plane": "primitive_plane_add",
    "cone": "primitive_cone_add",
    "torus": "primitive_torus_add",
}


def mesh_create_primitive(args: dict) -> dict:
    """Create a mesh primitive.

    Args:
        args: {
            "kind": str - one of cube, sphere, cylinder, plane, cone, torus
            "name": str|None - optional object name
            "location": [float, float, float] - default [0,0,0]
            "size": float - default 1.0
        }
    """
    kind = args.get("kind")
    if kind not in PRIMITIVES:
        raise ValueError(
            f"Unknown primitive kind: {kind}. "
            f"Must be one of: {', '.join(PRIMITIVES.keys())}"
        )

    name = args.get("name")
    location = tuple(args.get("location", [0, 0, 0]))
    size = args.get("size", 1.0)

    if len(location) != 3:
        raise ValueError("location must be [x, y, z]")
    if not isinstance(size, (int, float)) or size <= 0:
        raise ValueError("size must be a positive number")

    # Push undo checkpoint
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:mesh.create_primitive:{cmd_id}")

    # Create the primitive
    op_fn = getattr(bpy.ops.mesh, PRIMITIVES[kind])
    if kind == "torus":
        op_fn(location=location, major_radius=size, minor_radius=size * 0.25)
    else:
        op_fn(location=location, size=size)

    obj = bpy.context.active_object
    if name:
        obj.name = name

    mesh = obj.data
    return {
        "name": obj.name,
        "polys": len(mesh.polygons),
        "vertices": len(mesh.vertices),
    }


register_capability("mesh.create_primitive", mesh_create_primitive)
