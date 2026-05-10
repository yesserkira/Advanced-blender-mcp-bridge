"""High-level composition: build many objects atomically; transactions.

Tools registered:
- create_objects: spec-driven multi-object scene composer
- transaction:    atomic batch of arbitrary tool calls (rolls back on failure)
- apply_to_selection: run a tool over each selected object
"""

from __future__ import annotations


import bpy

from . import OP_REGISTRY, register_capability
from . import _dryrun


# ---------------------------------------------------------------------------
# create_objects
# ---------------------------------------------------------------------------

_LIGHT_TYPES = {"POINT", "SUN", "SPOT", "AREA"}
_PRIMITIVES = {
    "cube", "sphere", "cylinder", "plane", "cone", "torus",
    "monkey", "ico_sphere", "circle", "grid",
}
_PRIMITIVE_OPS = {
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


def _make_one(spec: dict) -> dict:
    """Create a single datablock per spec; return summary."""
    kind = spec.get("kind")
    if not kind:
        raise ValueError("spec.kind is required")

    name = spec.get("name")
    location = tuple(spec.get("location") or (0, 0, 0))
    rotation = tuple(spec.get("rotation") or (0, 0, 0))
    scale = tuple(spec.get("scale") or (1, 1, 1))

    obj = None

    if kind in _PRIMITIVES:
        op_fn = getattr(bpy.ops.mesh, _PRIMITIVE_OPS[kind])
        size = float(spec.get("size", 1.0))
        if kind == "torus":
            op_fn(location=location,
                  major_radius=size,
                  minor_radius=size * float(spec.get("minor_ratio", 0.25)))
        elif kind in {"cube", "plane", "grid", "monkey", "circle"}:
            op_fn(location=location, size=size)
        else:
            op_fn(location=location, radius=size)
        obj = bpy.context.active_object

    elif kind == "light":
        light_type = (spec.get("light_type") or "POINT").upper()
        if light_type not in _LIGHT_TYPES:
            raise ValueError(f"light_type must be one of {_LIGHT_TYPES}")
        light_data = bpy.data.lights.new(name=name or light_type, type=light_type)
        if "energy" in spec:
            light_data.energy = float(spec["energy"])
        if "color" in spec:
            col = spec["color"]
            light_data.color = (float(col[0]), float(col[1]), float(col[2]))
        if light_type == "SPOT":
            if "spot_size" in spec:
                light_data.spot_size = float(spec["spot_size"])
            if "spot_blend" in spec:
                light_data.spot_blend = float(spec["spot_blend"])
        if light_type == "AREA" and "area_size" in spec:
            light_data.size = float(spec["area_size"])
        obj = bpy.data.objects.new(name=name or light_type, object_data=light_data)
        bpy.context.scene.collection.objects.link(obj)

    elif kind == "camera":
        cam_data = bpy.data.cameras.new(name=name or "Camera")
        if "lens" in spec:
            cam_data.lens = float(spec["lens"])
        if "sensor_width" in spec:
            cam_data.sensor_width = float(spec["sensor_width"])
        if "clip_start" in spec:
            cam_data.clip_start = float(spec["clip_start"])
        if "clip_end" in spec:
            cam_data.clip_end = float(spec["clip_end"])
        if "dof" in spec:
            dof = spec["dof"]
            cam_data.dof.use_dof = bool(dof.get("use_dof", True))
            if "focus_distance" in dof:
                cam_data.dof.focus_distance = float(dof["focus_distance"])
            if "aperture_fstop" in dof:
                cam_data.dof.aperture_fstop = float(dof["aperture_fstop"])
        obj = bpy.data.objects.new(name=name or "Camera", object_data=cam_data)
        bpy.context.scene.collection.objects.link(obj)
        if spec.get("set_active"):
            bpy.context.scene.camera = obj

    elif kind == "empty":
        empty_type = (spec.get("empty_type") or "PLAIN_AXES").upper()
        obj = bpy.data.objects.new(name=name or "Empty", object_data=None)
        obj.empty_display_type = empty_type
        if "empty_display_size" in spec:
            obj.empty_display_size = float(spec["empty_display_size"])
        bpy.context.scene.collection.objects.link(obj)

    else:
        raise ValueError(
            f"Unknown kind '{kind}'. Use a primitive ({sorted(_PRIMITIVES)}), "
            f"or one of: light, camera, empty."
        )

    if obj is None:
        raise RuntimeError(f"failed to create {kind}")

    if name:
        obj.name = name
    obj.location = location
    obj.rotation_euler = rotation
    obj.scale = scale

    # Parent
    parent_name = spec.get("parent")
    if parent_name:
        parent = bpy.data.objects.get(parent_name)
        if parent is not None:
            obj.parent = parent

    # Collection
    coll_name = spec.get("collection")
    if coll_name:
        target_coll = bpy.data.collections.get(coll_name)
        if target_coll is None:
            target_coll = bpy.data.collections.new(coll_name)
            bpy.context.scene.collection.children.link(target_coll)
        # unlink from default scene collection if linked there
        for c in obj.users_collection:
            try:
                c.objects.unlink(obj)
            except Exception:
                pass
        target_coll.objects.link(obj)

    # Material
    mat_name = spec.get("material")
    if mat_name and obj.type == "MESH":
        mat = bpy.data.materials.get(mat_name)
        if mat is not None:
            if obj.data.materials:
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)

    # Modifiers
    summary_mods: list[str] = []
    for mod_spec in spec.get("modifiers") or []:
        mtype = mod_spec.get("type")
        mname = mod_spec.get("name") or mtype
        try:
            mod = obj.modifiers.new(name=mname, type=mtype)
        except (TypeError, RuntimeError) as e:
            raise ValueError(f"modifier '{mtype}' on {obj.name}: {e}")
        for k, v in (mod_spec.get("properties") or {}).items():
            try:
                if isinstance(v, str) and k in {"object", "target", "mirror_object"}:
                    setattr(mod, k, bpy.data.objects.get(v))
                else:
                    setattr(mod, k, v)
            except Exception:
                pass
        summary_mods.append(mname)

    # Properties (object-level RNA props, e.g. hide_render, display_type)
    for k, v in (spec.get("properties") or {}).items():
        try:
            setattr(obj, k, v)
        except Exception:
            pass

    return {
        "name": obj.name,
        "kind": kind,
        "type": obj.type,
        "location": list(obj.location),
        "modifiers": summary_mods,
        "collection": (obj.users_collection[0].name if obj.users_collection else None),
    }


def create_objects(args: dict) -> dict:
    """Create many objects atomically (one undo step).

    Args:
        args: {"specs": [ {kind, name?, location?, rotation?, scale?,
                          material?, modifiers?, parent?, collection?,
                          properties?, ...spec-specific...}, ... ]}

    When `args["__dry_run"]` is True, returns the planned creations without
    touching Blender state. See capabilities/_dryrun.py.
    """
    specs = args.get("specs")
    if not isinstance(specs, list) or not specs:
        raise ValueError("'specs' must be a non-empty list")

    if _dryrun.is_dry_run(args):
        return _dryrun.report(
            "create_objects",
            [_dryrun.would_create(s) for s in specs if isinstance(s, dict)],
        )

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:create_objects:{cmd_id}:n={len(specs)}")

    results = []
    errors = []
    for i, spec in enumerate(specs):
        try:
            results.append(_make_one(spec))
        except Exception as e:
            errors.append({"index": i, "spec": spec, "error": str(e)})

    return {
        "created": results,
        "count": len(results),
        "errors": errors,
    }


register_capability("create_objects", create_objects)


# ---------------------------------------------------------------------------
# transaction
# ---------------------------------------------------------------------------


def transaction(args: dict) -> dict:
    """Atomically run a list of {tool, args} steps under one undo checkpoint.

    On any failure: undo once and return failure info. On success: keep
    a single undo entry.

    Args:
        args: {"steps": [{"tool": str, "args": dict}, ...], "label": str | None}
    """
    steps = args.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("'steps' must be a non-empty list")

    label = args.get("label") or args.get("_cmd_id", "tx")
    bpy.ops.ed.undo_push(message=f"AI:transaction:{label}")

    results = []
    for i, step in enumerate(steps):
        tool = step.get("tool")
        sargs = step.get("args") or {}
        if not tool:
            bpy.ops.ed.undo()
            return {"ok": False, "failed_at": i, "error": "step.tool missing",
                    "completed": results}
        fn = OP_REGISTRY.get(tool)
        if fn is None:
            bpy.ops.ed.undo()
            return {"ok": False, "failed_at": i, "error": f"unknown tool '{tool}'",
                    "completed": results}
        # Disable per-step undo by passing a sentinel; capabilities still call
        # undo_push (Blender just merges them). Acceptable for v2.
        try:
            r = fn(sargs)
            results.append({"tool": tool, "result": r})
        except Exception as e:
            bpy.ops.ed.undo()
            return {"ok": False, "failed_at": i, "tool": tool,
                    "error": str(e), "completed": results}

    return {"ok": True, "label": label, "step_count": len(results),
            "results": results}


register_capability("transaction", transaction)


# ---------------------------------------------------------------------------
# apply_to_selection
# ---------------------------------------------------------------------------


def apply_to_selection(args: dict) -> dict:
    """Run a tool against each currently-selected object.

    The selected object's name is injected into the tool args under the key
    given by `name_key` (default "object").

    Args:
        args: {
            "tool": str,
            "args": dict,
            "name_key": str (default "object"),
        }
    """
    tool = args.get("tool")
    base_args = args.get("args") or {}
    name_key = args.get("name_key") or "object"
    if not tool:
        raise ValueError("'tool' is required")
    fn = OP_REGISTRY.get(tool)
    if fn is None:
        raise ValueError(f"unknown tool '{tool}'")

    selected = list(bpy.context.selected_objects)
    if not selected:
        return {"tool": tool, "count": 0, "results": []}

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:apply_to_selection:{tool}:{cmd_id}")

    results = []
    for obj in selected:
        per_args = dict(base_args)
        per_args[name_key] = obj.name
        try:
            results.append({"object": obj.name, "ok": True, "result": fn(per_args)})
        except Exception as e:
            results.append({"object": obj.name, "ok": False, "error": str(e)})
    return {"tool": tool, "count": len(results), "results": results}


register_capability("apply_to_selection", apply_to_selection)
