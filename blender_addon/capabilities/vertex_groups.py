"""Vertex groups + per-vertex weights — required for any rigging or weight-painting workflow.

These wrap the small but easy-to-misuse ``obj.vertex_groups.new()`` /
``vg.add()`` API which the AI cannot reach via ``set_property``.
"""

from __future__ import annotations

import bpy

from . import register_capability


def _get_mesh_object(name: str):
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object not found: {name}")
    if obj.type != "MESH":
        raise ValueError(
            f"object '{name}' is type {obj.type}; vertex groups require MESH",
        )
    return obj


def create_vertex_group(args: dict) -> dict:
    """Create a vertex group on a mesh object.

    Args:
        args: {"object": str, "name": str}
    """
    obj = _get_mesh_object(args.get("object"))
    name = args.get("name")
    if not name:
        raise ValueError("'name' is required")
    if name in obj.vertex_groups:
        raise ValueError(f"vertex group '{name}' already exists on '{obj.name}'")
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:create_vertex_group:{cmd_id}")
    vg = obj.vertex_groups.new(name=name)
    return {
        "object": obj.name, "group": vg.name,
        "index": vg.index, "count": len(obj.vertex_groups),
    }


def remove_vertex_group(args: dict) -> dict:
    """Remove a vertex group by name."""
    obj = _get_mesh_object(args.get("object"))
    name = args.get("name")
    if not name:
        raise ValueError("'name' is required")
    vg = obj.vertex_groups.get(name)
    if vg is None:
        raise ValueError(f"vertex group '{name}' not found on '{obj.name}'")
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:remove_vertex_group:{cmd_id}")
    obj.vertex_groups.remove(vg)
    return {"object": obj.name, "removed": name}


def list_vertex_groups(args: dict) -> dict:
    """List vertex groups on a mesh object (read-only)."""
    obj = _get_mesh_object(args.get("object"))
    return {
        "object": obj.name,
        "groups": [
            {"name": vg.name, "index": vg.index, "lock_weight": vg.lock_weight}
            for vg in obj.vertex_groups
        ],
    }


def set_vertex_weights(args: dict) -> dict:
    """Set per-vertex weights on a vertex group.

    Args:
        args: {
            "object": str,
            "group": str,
            "indices": [int, ...],          # vertex indices
            "weights": [float, ...] | float, # parallel array; or one weight applied to all
            "type": "REPLACE" | "ADD" | "SUBTRACT" (default "REPLACE"),
        }
    """
    obj = _get_mesh_object(args.get("object"))
    gname = args.get("group")
    if not gname:
        raise ValueError("'group' is required")
    vg = obj.vertex_groups.get(gname)
    if vg is None:
        raise ValueError(f"vertex group '{gname}' not found on '{obj.name}'")

    indices = args.get("indices") or []
    if not isinstance(indices, list):
        raise ValueError("'indices' must be a list of int")
    weights_arg = args.get("weights")
    if weights_arg is None:
        raise ValueError("'weights' is required (float or list of floats)")
    if isinstance(weights_arg, (int, float)):
        weights = [float(weights_arg)] * len(indices)
    elif isinstance(weights_arg, list):
        if len(weights_arg) != len(indices):
            raise ValueError(
                f"'weights' length {len(weights_arg)} != "
                f"'indices' length {len(indices)}",
            )
        weights = [float(w) for w in weights_arg]
    else:
        raise ValueError("'weights' must be a float or a list of floats")
    op = (args.get("type") or "REPLACE").upper()
    if op not in {"REPLACE", "ADD", "SUBTRACT"}:
        raise ValueError("'type' must be REPLACE, ADD, or SUBTRACT")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:set_vertex_weights:{cmd_id}")

    nverts = len(obj.data.vertices)
    out_of_range: list[int] = []
    valid_indices: list[int] = []
    valid_weights: list[float] = []
    for i, w in zip(indices, weights):
        if 0 <= i < nverts:
            valid_indices.append(int(i))
            valid_weights.append(float(w))
        else:
            out_of_range.append(int(i))

    # vg.add() wants the weight applied uniformly per call, so group by weight
    # for efficiency. For small counts this is fine to call per-vertex.
    for i, w in zip(valid_indices, valid_weights):
        vg.add([i], w, op)

    return {
        "object": obj.name,
        "group": gname,
        "set_count": len(valid_indices),
        "out_of_range": out_of_range,
        "type": op,
    }


register_capability("create_vertex_group", create_vertex_group)
register_capability("remove_vertex_group", remove_vertex_group)
register_capability("list_vertex_groups", list_vertex_groups)
register_capability("set_vertex_weights", set_vertex_weights)
