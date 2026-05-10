"""mesh_edit — declarative bmesh DSL for edit-mode mesh operations.

Closes the largest single gap: previously the AI had to enter EDIT mode,
select verts/edges/faces, call ``bpy.ops.mesh.extrude_region`` (with all
its CANCELLED traps) and then leave the mode. This module wraps every
common edit operation as a single atomic op the AI can describe in JSON.

Operations supported (declarative ``ops`` list):

    {"op": "extrude_faces", "faces": [int...], "offset": [x,y,z]}
    {"op": "extrude_edges", "edges": [int...], "offset": [x,y,z]}
    {"op": "extrude_verts", "verts": [int...], "offset": [x,y,z]}
    {"op": "inset_faces",   "faces": [int...], "thickness": float, "depth": float?}
    {"op": "bevel_edges",   "edges": [int...], "offset": float, "segments": int?}
    {"op": "bevel_verts",   "verts": [int...], "offset": float, "segments": int?}
    {"op": "subdivide",     "edges": [int...], "cuts": int?}
    {"op": "loop_cut",      "edge": int, "cuts": int?}        # uses subdivide on a ring
    {"op": "merge_verts",   "verts": [int...], "mode": "CENTER"|"FIRST"|"LAST", "distance": float?}
    {"op": "remove_doubles","verts": [int...]?, "distance": float?}
    {"op": "delete_verts",  "verts": [int...]}
    {"op": "delete_edges",  "edges": [int...]}
    {"op": "delete_faces",  "faces": [int...]}
    {"op": "dissolve_verts","verts": [int...]}
    {"op": "dissolve_edges","edges": [int...]}
    {"op": "dissolve_faces","faces": [int...]}
    {"op": "bridge_loops",  "edges_a": [int...], "edges_b": [int...]}
    {"op": "fill",          "edges": [int...]}
    {"op": "triangulate",   "faces": [int...]?}
    {"op": "recalc_normals","inside": bool?}
    {"op": "flip_normals",  "faces": [int...]?}
    {"op": "smooth_verts",  "verts": [int...], "factor": float?}
    {"op": "transform_verts","verts": [int...], "translate"|"scale"|"rotation": ...}

Bmesh runs without entering EDIT mode in Blender's UI sense — we mutate
``bpy.data.meshes[name]`` directly via bmesh and write back. This avoids the
mode-set / area-context nightmares entirely.
"""

from __future__ import annotations

from typing import Any

import bpy
import bmesh
from mathutils import Matrix, Vector

from . import register_capability


_OP_HANDLERS: dict[str, Any] = {}  # populated below via @_register


def _register(name: str):
    def deco(fn):
        _OP_HANDLERS[name] = fn
        return fn
    return deco


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_mesh_object(name: str):
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object not found: {name}")
    if obj.type != "MESH":
        raise ValueError(
            f"object '{name}' is type {obj.type}; mesh_edit requires MESH",
        )
    return obj


def _verts_by_index(bm, indices: list[int]):
    bm.verts.ensure_lookup_table()
    n = len(bm.verts)
    return [bm.verts[i] for i in indices if 0 <= i < n]


def _edges_by_index(bm, indices: list[int]):
    bm.edges.ensure_lookup_table()
    n = len(bm.edges)
    return [bm.edges[i] for i in indices if 0 <= i < n]


def _faces_by_index(bm, indices: list[int]):
    bm.faces.ensure_lookup_table()
    n = len(bm.faces)
    return [bm.faces[i] for i in indices if 0 <= i < n]


def _vec3(v) -> Vector:
    return Vector((float(v[0]), float(v[1]), float(v[2])))


# ---------------------------------------------------------------------------
# Op handlers
# ---------------------------------------------------------------------------


@_register("extrude_faces")
def _op_extrude_faces(bm, spec):
    faces = _faces_by_index(bm, spec.get("faces") or [])
    if not faces:
        return {"reason": "no faces selected"}
    offset = _vec3(spec.get("offset") or (0, 0, 0))
    geom = bmesh.ops.extrude_face_region(bm, geom=faces)["geom"]
    new_verts = [g for g in geom if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=new_verts, vec=offset)
    return {"new_verts": len(new_verts), "offset": list(offset)}


@_register("extrude_edges")
def _op_extrude_edges(bm, spec):
    edges = _edges_by_index(bm, spec.get("edges") or [])
    if not edges:
        return {"reason": "no edges selected"}
    offset = _vec3(spec.get("offset") or (0, 0, 0))
    geom = bmesh.ops.extrude_edge_only(bm, edges=edges)["geom"]
    new_verts = [g for g in geom if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=new_verts, vec=offset)
    return {"new_verts": len(new_verts), "offset": list(offset)}


@_register("extrude_verts")
def _op_extrude_verts(bm, spec):
    verts = _verts_by_index(bm, spec.get("verts") or [])
    if not verts:
        return {"reason": "no verts selected"}
    offset = _vec3(spec.get("offset") or (0, 0, 0))
    geom = bmesh.ops.extrude_vert_indiv(bm, verts=verts)["verts"]
    bmesh.ops.translate(bm, verts=geom, vec=offset)
    return {"new_verts": len(geom), "offset": list(offset)}


@_register("inset_faces")
def _op_inset_faces(bm, spec):
    faces = _faces_by_index(bm, spec.get("faces") or [])
    if not faces:
        return {"reason": "no faces selected"}
    thickness = float(spec.get("thickness", 0.1))
    depth = float(spec.get("depth", 0.0))
    res = bmesh.ops.inset_region(
        bm, faces=faces, thickness=thickness, depth=depth, use_even_offset=True,
    )
    return {"new_faces": len(res.get("faces", []))}


@_register("bevel_edges")
def _op_bevel_edges(bm, spec):
    edges = _edges_by_index(bm, spec.get("edges") or [])
    if not edges:
        return {"reason": "no edges selected"}
    res = bmesh.ops.bevel(
        bm,
        geom=edges,
        offset=float(spec.get("offset", 0.05)),
        segments=int(spec.get("segments", 1)),
        affect="EDGES",
        clamp_overlap=True,
    )
    return {"new_faces": len(res.get("faces", []))}


@_register("bevel_verts")
def _op_bevel_verts(bm, spec):
    verts = _verts_by_index(bm, spec.get("verts") or [])
    if not verts:
        return {"reason": "no verts selected"}
    res = bmesh.ops.bevel(
        bm,
        geom=verts,
        offset=float(spec.get("offset", 0.05)),
        segments=int(spec.get("segments", 1)),
        affect="VERTICES",
    )
    return {"new_faces": len(res.get("faces", []))}


@_register("subdivide")
def _op_subdivide(bm, spec):
    edges = _edges_by_index(bm, spec.get("edges") or [])
    if not edges:
        return {"reason": "no edges selected"}
    cuts = int(spec.get("cuts", 1))
    bmesh.ops.subdivide_edges(
        bm, edges=edges, cuts=cuts, use_grid_fill=True,
    )
    return {"cuts": cuts, "edges": len(edges)}


@_register("loop_cut")
def _op_loop_cut(bm, spec):
    """Loop-cut around the ring of an edge — implemented via bmesh subdivide
    on the matching edge ring rather than the ``mesh.loopcut`` operator
    (which needs a UI region context)."""
    edge_idx = spec.get("edge")
    if edge_idx is None:
        return {"reason": "'edge' is required"}
    bm.edges.ensure_lookup_table()
    if not (0 <= edge_idx < len(bm.edges)):
        return {"reason": f"edge index {edge_idx} out of range"}
    edge = bm.edges[edge_idx]
    # collect the ring by walking the same-direction edges of adjacent quads
    ring = {edge}
    frontier = [edge]
    while frontier:
        e = frontier.pop()
        for f in e.link_faces:
            if len(f.edges) != 4:
                continue
            i = list(f.edges).index(e)
            opp = f.edges[(i + 2) % 4]
            if opp not in ring:
                ring.add(opp)
                frontier.append(opp)
    cuts = int(spec.get("cuts", 1))
    bmesh.ops.subdivide_edges(bm, edges=list(ring), cuts=cuts, use_grid_fill=True)
    return {"ring_edges": len(ring), "cuts": cuts}


_MERGE_MODES = {"CENTER": "MERGE_CENTER", "FIRST": "MERGE_FIRST", "LAST": "MERGE_LAST"}


@_register("merge_verts")
def _op_merge_verts(bm, spec):
    verts = _verts_by_index(bm, spec.get("verts") or [])
    if len(verts) < 2:
        return {"reason": "need at least 2 verts"}
    mode = (spec.get("mode") or "CENTER").upper()
    if mode == "DISTANCE":
        return _op_remove_doubles(bm, spec)
    if mode not in _MERGE_MODES:
        return {"reason": f"unknown mode '{mode}'"}
    if mode == "CENTER":
        center = sum((v.co for v in verts), Vector()) / len(verts)
        target = bm.verts.new(center)
        bmesh.ops.pointmerge(bm, verts=verts + [target], merge_co=center)
    elif mode == "FIRST":
        bmesh.ops.pointmerge(bm, verts=verts, merge_co=verts[0].co)
    else:  # LAST
        bmesh.ops.pointmerge(bm, verts=verts, merge_co=verts[-1].co)
    return {"merged": len(verts), "mode": mode}


@_register("remove_doubles")
def _op_remove_doubles(bm, spec):
    verts = _verts_by_index(bm, spec.get("verts") or []) if spec.get("verts") else list(bm.verts)
    distance = float(spec.get("distance", 0.0001))
    bmesh.ops.remove_doubles(bm, verts=verts, dist=distance)
    return {"distance": distance, "candidates": len(verts)}


@_register("delete_verts")
def _op_delete_verts(bm, spec):
    verts = _verts_by_index(bm, spec.get("verts") or [])
    if not verts:
        return {"reason": "no verts"}
    bmesh.ops.delete(bm, geom=verts, context="VERTS")
    return {"deleted": len(verts), "context": "VERTS"}


@_register("delete_edges")
def _op_delete_edges(bm, spec):
    edges = _edges_by_index(bm, spec.get("edges") or [])
    if not edges:
        return {"reason": "no edges"}
    bmesh.ops.delete(bm, geom=edges, context="EDGES")
    return {"deleted": len(edges), "context": "EDGES"}


@_register("delete_faces")
def _op_delete_faces(bm, spec):
    faces = _faces_by_index(bm, spec.get("faces") or [])
    if not faces:
        return {"reason": "no faces"}
    bmesh.ops.delete(bm, geom=faces, context="FACES")
    return {"deleted": len(faces), "context": "FACES"}


@_register("dissolve_verts")
def _op_dissolve_verts(bm, spec):
    verts = _verts_by_index(bm, spec.get("verts") or [])
    if not verts:
        return {"reason": "no verts"}
    bmesh.ops.dissolve_verts(bm, verts=verts)
    return {"dissolved": len(verts)}


@_register("dissolve_edges")
def _op_dissolve_edges(bm, spec):
    edges = _edges_by_index(bm, spec.get("edges") or [])
    if not edges:
        return {"reason": "no edges"}
    bmesh.ops.dissolve_edges(bm, edges=edges, use_verts=bool(spec.get("use_verts", False)))
    return {"dissolved": len(edges)}


@_register("dissolve_faces")
def _op_dissolve_faces(bm, spec):
    faces = _faces_by_index(bm, spec.get("faces") or [])
    if not faces:
        return {"reason": "no faces"}
    bmesh.ops.dissolve_faces(bm, faces=faces)
    return {"dissolved": len(faces)}


@_register("bridge_loops")
def _op_bridge_loops(bm, spec):
    a = _edges_by_index(bm, spec.get("edges_a") or [])
    b = _edges_by_index(bm, spec.get("edges_b") or [])
    if not a or not b:
        return {"reason": "edges_a and edges_b are both required"}
    res = bmesh.ops.bridge_loops(bm, edges=a + b)
    return {"new_faces": len(res.get("faces", []))}


@_register("fill")
def _op_fill(bm, spec):
    edges = _edges_by_index(bm, spec.get("edges") or [])
    if not edges:
        return {"reason": "no edges"}
    res = bmesh.ops.edgenet_fill(bm, edges=edges)
    return {"new_faces": len(res.get("faces", []))}


@_register("triangulate")
def _op_triangulate(bm, spec):
    faces_arg = spec.get("faces")
    faces = _faces_by_index(bm, faces_arg) if faces_arg else list(bm.faces)
    if not faces:
        return {"reason": "no faces"}
    res = bmesh.ops.triangulate(bm, faces=faces)
    return {"new_faces": len(res.get("faces", []))}


@_register("recalc_normals")
def _op_recalc_normals(bm, spec):
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    if spec.get("inside"):
        bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
    return {"recalculated": len(bm.faces), "inside": bool(spec.get("inside"))}


@_register("flip_normals")
def _op_flip_normals(bm, spec):
    faces_arg = spec.get("faces")
    faces = _faces_by_index(bm, faces_arg) if faces_arg else list(bm.faces)
    if not faces:
        return {"reason": "no faces"}
    bmesh.ops.reverse_faces(bm, faces=faces)
    return {"flipped": len(faces)}


@_register("smooth_verts")
def _op_smooth_verts(bm, spec):
    verts = _verts_by_index(bm, spec.get("verts") or [])
    if not verts:
        return {"reason": "no verts"}
    factor = float(spec.get("factor", 0.5))
    bmesh.ops.smooth_vert(
        bm, verts=verts, factor=factor,
        use_axis_x=True, use_axis_y=True, use_axis_z=True,
    )
    return {"smoothed": len(verts), "factor": factor}


@_register("transform_verts")
def _op_transform_verts(bm, spec):
    verts = _verts_by_index(bm, spec.get("verts") or [])
    if not verts:
        return {"reason": "no verts"}
    if spec.get("translate") is not None:
        bmesh.ops.translate(bm, verts=verts, vec=_vec3(spec["translate"]))
    if spec.get("scale") is not None:
        center = sum((v.co for v in verts), Vector()) / len(verts)
        # Scale around the local centroid by translating to origin, scaling, translating back.
        space = Matrix.Translation(-center)
        bmesh.ops.scale(bm, verts=verts, vec=_vec3(spec["scale"]), space=space)
    return {"affected": len(verts)}


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def mesh_edit(args: dict) -> dict:
    """Apply a sequence of bmesh edit operations to a mesh object.

    Args:
        args: {
            "object": str,
            "ops": [ {"op": "...", ...}, ... ],
            "validate": bool (default True) — run mesh.validate() after ops,
        }

    Returns:
        {
            "object": str,
            "vertices_before"/"after": int,
            "edges_before"/"after": int,
            "faces_before"/"after": int,
            "results": [ {"op": "...", ...handler-specific...}, ... ],
            "errors": [ {"index": int, "op": str, "error": str}, ... ],
        }
    """
    obj = _resolve_mesh_object(args.get("object"))
    ops = args.get("ops") or []
    if not isinstance(ops, list) or not ops:
        raise ValueError("'ops' must be a non-empty list")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:mesh_edit:{cmd_id}")

    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    try:
        v0, e0, f0 = len(bm.verts), len(bm.edges), len(bm.faces)
        results: list[dict] = []
        errors: list[dict] = []
        for i, spec in enumerate(ops):
            if not isinstance(spec, dict):
                errors.append({"index": i, "op": None, "error": "spec must be a dict"})
                continue
            opname = spec.get("op")
            handler = _OP_HANDLERS.get(opname)
            if handler is None:
                errors.append({
                    "index": i, "op": opname,
                    "error": f"unknown op '{opname}'. "
                             f"Available: {sorted(_OP_HANDLERS)}",
                })
                continue
            try:
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.faces.ensure_lookup_table()
                out = handler(bm, spec)
                results.append({"index": i, "op": opname, **(out or {})})
            except Exception as e:  # noqa: BLE001
                errors.append({
                    "index": i, "op": opname,
                    "error": str(e), "type": type(e).__name__,
                })
        v1, e1, f1 = len(bm.verts), len(bm.edges), len(bm.faces)
        bm.to_mesh(me)
    finally:
        bm.free()

    me.update()
    if args.get("validate", True):
        me.validate(verbose=False)

    return {
        "object": obj.name,
        "vertices_before": v0, "vertices_after": v1,
        "edges_before": e0, "edges_after": e1,
        "faces_before": f0, "faces_after": f1,
        "results": results,
        "errors": errors,
        "ok_count": len(results),
        "error_count": len(errors),
    }


# ---------------------------------------------------------------------------
# Read-only mesh inspection
# ---------------------------------------------------------------------------


def mesh_read(args: dict) -> dict:
    """Read mesh geometry data with bounded slicing.

    Args:
        args: {
            "object": str,
            "what": ["vertices"|"edges"|"faces"|"normals"|"loop_uvs"] (default ["vertices"]),
            "start": int (default 0),
            "limit": int (default 1000, max 10000),
            "uv_layer": str | None — only used when 'loop_uvs' requested,
        }
    """
    obj = _resolve_mesh_object(args.get("object"))
    what = args.get("what") or ["vertices"]
    if isinstance(what, str):
        what = [what]
    start = max(0, int(args.get("start", 0)))
    limit = max(1, min(10000, int(args.get("limit", 1000))))

    me = obj.data
    out: dict[str, Any] = {
        "object": obj.name,
        "counts": {
            "vertices": len(me.vertices),
            "edges": len(me.edges),
            "faces": len(me.polygons),
            "loops": len(me.loops),
        },
        "start": start,
        "limit": limit,
    }
    if "vertices" in what:
        out["vertices"] = [
            list(v.co) for v in me.vertices[start:start + limit]
        ]
    if "edges" in what:
        out["edges"] = [
            list(e.vertices) for e in me.edges[start:start + limit]
        ]
    if "faces" in what:
        out["faces"] = [
            list(p.vertices) for p in me.polygons[start:start + limit]
        ]
    if "normals" in what:
        out["vertex_normals"] = [
            list(v.normal) for v in me.vertices[start:start + limit]
        ]
        out["face_normals"] = [
            list(p.normal) for p in me.polygons[start:start + limit]
        ]
    if "loop_uvs" in what:
        layer_name = args.get("uv_layer")
        layer = (
            me.uv_layers.get(layer_name) if layer_name else me.uv_layers.active
        )
        if layer is not None:
            data = layer.data
            out["loop_uvs"] = [
                list(d.uv) for d in data[start:start + limit]
            ]
            out["uv_layer"] = layer.name
        else:
            out["loop_uvs"] = []
            out["uv_layer"] = None
    return out


register_capability("mesh_edit", mesh_edit)
register_capability("mesh_read", mesh_read)
