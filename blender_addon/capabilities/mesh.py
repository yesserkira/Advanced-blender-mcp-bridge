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
    elif kind in ("cube", "plane"):
        op_fn(location=location, size=size)
    else:
        # sphere, cylinder, cone use 'radius'
        op_fn(location=location, radius=size)

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


# ---------------------------------------------------------------------------
# T-409: mesh.edit — bmesh-based editing operations
# ---------------------------------------------------------------------------

import bmesh
from mathutils import Vector

EDIT_OPERATIONS = {"extrude", "bevel", "loop_cut", "boolean"}


def mesh_edit(args: dict) -> dict:
    """Edit a mesh using bmesh operations.

    Args:
        args: {
            "object_name": str - name of mesh object to edit
            "operation": str - one of: extrude, bevel, loop_cut, boolean
            "params": dict - operation-specific parameters:
                extrude: {
                    "offset": float - extrusion distance (default 1.0)
                    "direction": [x,y,z] - extrusion direction (default [0,0,1])
                }
                bevel: {
                    "offset": float - bevel width (default 0.1)
                    "segments": int - number of segments (default 1)
                    "affect": "EDGES"|"VERTICES" (default "EDGES")
                }
                loop_cut: {
                    "cuts": int - number of cuts (default 1)
                    "edge_index": int - edge index to cut along (default 0)
                }
                boolean: {
                    "other_object": str - name of the other mesh object
                    "operation": "UNION"|"INTERSECT"|"DIFFERENCE" (default "DIFFERENCE")
                }
        }
    """
    object_name = args.get("object_name")
    operation = args.get("operation")
    params = args.get("params", {})

    if not object_name:
        raise ValueError("object_name is required")
    if operation not in EDIT_OPERATIONS:
        raise ValueError(
            f"Unknown operation: {operation}. "
            f"Must be one of: {', '.join(sorted(EDIT_OPERATIONS))}"
        )

    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object not found: {object_name}")
    if obj.type != "MESH":
        raise ValueError(f"Object '{object_name}' is not a mesh (type={obj.type})")

    # Push undo checkpoint
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:mesh.edit:{cmd_id}")

    if operation == "extrude":
        result = _edit_extrude(obj, params)
    elif operation == "bevel":
        result = _edit_bevel(obj, params)
    elif operation == "loop_cut":
        result = _edit_loop_cut(obj, params)
    elif operation == "boolean":
        result = _edit_boolean(obj, params)

    mesh = obj.data
    result["object"] = obj.name
    result["vertices"] = len(mesh.vertices)
    result["polys"] = len(mesh.polygons)
    return result


def _edit_extrude(obj, params: dict) -> dict:
    """Extrude all faces along a direction."""
    offset = params.get("offset", 1.0)
    direction = params.get("direction", [0, 0, 1])

    if len(direction) != 3:
        raise ValueError("direction must be [x, y, z]")

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()

    vec = Vector(direction).normalized() * offset

    result_geom = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])
    extruded_verts = [g for g in result_geom["geom"] if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=vec, verts=extruded_verts)

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

    return {"operation": "extrude", "offset": offset, "direction": list(direction)}


def _edit_bevel(obj, params: dict) -> dict:
    """Bevel edges or vertices."""
    offset = params.get("offset", 0.1)
    segments = params.get("segments", 1)
    affect = params.get("affect", "EDGES")

    if affect not in ("EDGES", "VERTICES"):
        raise ValueError("affect must be 'EDGES' or 'VERTICES'")
    if not isinstance(segments, int) or segments < 1:
        raise ValueError("segments must be a positive integer")
    if not isinstance(offset, (int, float)) or offset <= 0:
        raise ValueError("offset must be a positive number")

    bm = bmesh.new()
    bm.from_mesh(obj.data)

    if affect == "EDGES":
        bm.edges.ensure_lookup_table()
        geom = bm.edges[:]
    else:
        bm.verts.ensure_lookup_table()
        geom = bm.verts[:]

    bmesh.ops.bevel(
        bm,
        geom=geom,
        offset=offset,
        segments=segments,
        affect=affect,
    )

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

    return {"operation": "bevel", "offset": offset, "segments": segments, "affect": affect}


def _edit_loop_cut(obj, params: dict) -> dict:
    """Add loop cuts to the mesh via the operator."""
    cuts = params.get("cuts", 1)
    edge_index = params.get("edge_index", 0)

    if not isinstance(cuts, int) or cuts < 1:
        raise ValueError("cuts must be a positive integer")

    mesh = obj.data
    if edge_index < 0 or edge_index >= len(mesh.edges):
        raise ValueError(
            f"edge_index {edge_index} out of range (0-{len(mesh.edges) - 1})"
        )

    # Loop cut requires object mode context override
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.loopcut_slide(
        MESH_OT_loopcut={
            "number_cuts": cuts,
            "edge_index": edge_index,
        },
        TRANSFORM_OT_edge_slide={"value": 0.0},
    )
    bpy.ops.object.mode_set(mode="OBJECT")

    return {"operation": "loop_cut", "cuts": cuts, "edge_index": edge_index}


def _edit_boolean(obj, params: dict) -> dict:
    """Perform a boolean operation between two meshes."""
    other_name = params.get("other_object")
    bool_op = params.get("operation", "DIFFERENCE")

    if not other_name:
        raise ValueError("other_object is required for boolean operation")
    if bool_op not in ("UNION", "INTERSECT", "DIFFERENCE"):
        raise ValueError(
            f"operation must be 'UNION', 'INTERSECT', or 'DIFFERENCE', got '{bool_op}'"
        )

    other = bpy.data.objects.get(other_name)
    if other is None:
        raise ValueError(f"Other object not found: {other_name}")
    if other.type != "MESH":
        raise ValueError(f"Other object '{other_name}' is not a mesh (type={other.type})")

    bm = bmesh.new()
    bm.from_mesh(obj.data)

    bm_other = bmesh.new()
    bm_other.from_mesh(other.data)

    # Transform other mesh into obj's local space
    mat = obj.matrix_world.inverted() @ other.matrix_world
    bmesh.ops.transform(bm_other, matrix=mat, verts=bm_other.verts[:])

    result = bmesh.ops.boolean(
        bm,
        geom=bm.faces[:] + bm.edges[:] + bm.verts[:],
        geom_cut=bm_other.faces[:] + bm_other.edges[:] + bm_other.verts[:],
        use_self=True,
        boolean_mode=bool_op,
    )

    bm.to_mesh(obj.data)
    bm_other.free()
    bm.free()
    obj.data.update()

    return {"operation": "boolean", "boolean_mode": bool_op, "other_object": other_name}


register_capability("mesh.edit", mesh_edit)
