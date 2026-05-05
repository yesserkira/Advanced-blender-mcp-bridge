"""Blender MCP Server v2.0 — generic, batch-aware, introspection-driven.

Exposes a small set of LOAD-BEARING tools rather than many narrow wrappers.
Every mutator accepts a single args dict OR an "items" list for batched
execution under one undo step.
"""

import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .blender_client import BlenderError, BlenderWS
from .policy import Policy, PolicyDenied

logger = logging.getLogger("blender_mcp")
mcp = FastMCP("blender")

_bl: BlenderWS | None = None
_policy: Policy | None = None


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def _get_client() -> BlenderWS:
    global _bl
    if _bl is None:
        token = os.environ.get("BLENDER_MCP_TOKEN", "")
        if not token:
            try:
                import keyring
                token = keyring.get_password("blender-mcp", "default") or ""
            except Exception:
                pass
        url = os.environ.get("BLENDER_MCP_URL", "ws://127.0.0.1:9876")
        _bl = BlenderWS(url=url, token=token)
    return _bl


def _get_policy() -> Policy:
    global _policy
    if _policy is None:
        _policy = Policy.load(os.environ.get("BLENDER_MCP_POLICY"))
    return _policy


async def _call(op: str, args: dict | None = None, timeout: float = 30.0) -> dict:
    """Call a Blender op and return either the result dict or a uniform error."""
    bl = _get_client()
    try:
        return await bl.call(op, args or {}, timeout=timeout)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}
    except PolicyDenied as e:
        return {"error": getattr(e, "code", "POLICY_DENIED"), "message": str(e), "hint": e.hint}


def _maybe_batch(items_or_arg, single_arg: dict, common: dict | None = None) -> dict:
    """Build args for a tool that may be batched.

    If `items_or_arg` is a list -> {"items": [...], "common": common}.
    Else -> single_arg.
    """
    if isinstance(items_or_arg, list):
        return {"items": items_or_arg, "common": common or {}}
    return single_arg


# ===========================================================================
# Connectivity
# ===========================================================================


@mcp.tool()
async def ping() -> str:
    """Ping the Blender add-on; returns 'pong' if connected."""
    bl = _get_client()
    try:
        return str(await bl.call("ping"))
    except BlenderError as e:
        return f"error: {e.code}: {e}"


# ===========================================================================
# P2: Smart awareness
# ===========================================================================


@mcp.tool()
async def query(target: str, fields: list[str] | None = None) -> dict | list:
    """Granular read of any Blender datablock without downloading the whole scene.

    Target string syntax:
        scene
        scene.render | scene.cycles | scene.eevee
        render | world | view_layer
        object:Cube
        object:Cube.modifiers
        object:Cube.modifiers[0]
        object:Cube.modifiers["Bevel"]
        material:Gold.node_tree.nodes
        collection:Lights

    Args:
        target: dotted RNA path (see above).
        fields: optional list of attribute names to project. Omit for all.

    Returns:
        Dict of properties (or list when target is a collection).
    """
    _get_policy().require("query")
    return await _call("query", {"target": target, "fields": fields})


@mcp.tool(name="list")
async def list_(kind: str, filter: dict | None = None) -> list[dict]:
    """Enumerate datablocks of a given kind.

    Args:
        kind: 'objects' | 'materials' | 'meshes' | 'lights' | 'cameras'
              | 'collections' | 'images' | 'node_groups' | 'actions' | 'scenes'.
        filter: optional dict, supports keys:
                {"type": "MESH"}, {"name_contains": "Ring"},
                {"name_prefix": "Light"}, {"in_collection": "Lights"}.
    """
    _get_policy().require("list")
    return await _call("list", {"kind": kind, "filter": filter})


@mcp.tool()
async def describe_api(rna_path: str) -> dict:
    """Introspect a bpy.types class via its bl_rna.

    Returns its property table (name, type, enum items, soft min/max,
    default, description) and registered functions. Use this to discover
    parameters of any modifier, node, or RNA struct without hard-coded knowledge.

    Examples:
        describe_api("SubsurfModifier")
        describe_api("ShaderNodeBsdfPrincipled")
        describe_api("CyclesRenderSettings")
    """
    _get_policy().require("describe_api")
    return await _call("describe_api", {"rna_path": rna_path})


@mcp.tool()
async def get_audit_log(limit: int = 50, since_ts: str | None = None) -> dict:
    """Tail the local audit log of recently executed commands."""
    _get_policy().require("get_audit_log")
    return await _call("audit.read", {"limit": limit, "since_ts": since_ts})


# ===========================================================================
# P3: Generic pass-through
# ===========================================================================


@mcp.tool()
async def add_modifier(
    object: str | list[dict] | None = None,
    type: str | None = None,
    name: str | None = None,
    properties: dict | None = None,
) -> dict:
    """Add a modifier to an object (works with all 30+ Blender modifier types).

    Single form:
        add_modifier(object="Cube", type="BEVEL",
                     properties={"width": 0.05, "segments": 3})
    Batch form (one undo step for all):
        add_modifier(object=[
            {"object": "Cube",  "type": "SUBSURF", "properties": {"levels": 2}},
            {"object": "Plane", "type": "SOLIDIFY","properties": {"thickness": 0.1}},
        ])

    Use `describe_api("BevelModifier")` etc. to discover available properties.
    """
    _get_policy().require("add_modifier")
    if isinstance(object, list):
        return await _call("add_modifier", {"items": object})
    args = {"object": object, "type": type}
    if name is not None:
        args["name"] = name
    if properties is not None:
        args["properties"] = properties
    return await _call("add_modifier", args)


@mcp.tool()
async def remove_modifier(object: str, name: str) -> dict:
    """Remove a modifier from an object by name."""
    _get_policy().require("remove_modifier")
    return await _call("remove_modifier", {"object": object, "name": name})


@mcp.tool()
async def build_nodes(
    target: str,
    graph: dict,
    clear: bool = True,
) -> dict:
    """Build any node graph (shader / geometry / world / compositor) declaratively.

    Target syntax:
        material:Gold        - existing material
        material:Gold!       - create if missing
        world                - active scene world (use_nodes auto-enabled)
        scene.compositor     - scene compositor tree
        object:X.modifiers.Y - geometry-nodes modifier (created if missing)

    Graph shape:
        {
          "nodes": [
            {"name":"bsdf","type":"ShaderNodeBsdfPrincipled","location":[0,0],
             "inputs":{"Base Color":[0.8,0.1,0.1,1.0],"Metallic":0.9,"Roughness":0.2}},
            {"name":"out","type":"ShaderNodeOutputMaterial","location":[400,0]}
          ],
          "links": [{"from":"bsdf.BSDF","to":"out.Surface"}]
        }
    """
    _get_policy().require("build_nodes")
    return await _call(
        "build_nodes",
        {"target": target, "graph": graph, "clear": clear},
        timeout=60.0,
    )


@mcp.tool()
async def assign_material(object: str, material: str, slot: int = 0) -> dict:
    """Assign an existing material to an object slot."""
    _get_policy().require("assign_material")
    return await _call(
        "assign_material",
        {"object": object, "material": material, "slot": slot},
    )


@mcp.tool()
async def set_property(path: str, value: Any) -> dict:
    """Set any RNA property by Python-style path (parsed safely, no eval).

    Examples:
        set_property("bpy.data.scenes['Scene'].cycles.samples", 256)
        set_property("bpy.data.scenes['Scene'].render.resolution_x", 1920)
        set_property("bpy.data.objects['Cube'].location", [1, 0, 2])
        set_property("bpy.data.scenes['Scene'].view_settings.view_transform", "AgX")
    """
    _get_policy().require("set_property")
    return await _call("set_property", {"path": path, "value": value})


@mcp.tool()
async def get_property(path: str) -> dict:
    """Read any RNA property by Python-style path (read-only mirror of set_property)."""
    _get_policy().require("get_property")
    return await _call("get_property", {"path": path})


@mcp.tool()
async def call_operator(
    operator: str,
    kwargs: dict | None = None,
    execution_context: str | None = None,
) -> dict:
    """Invoke any allowed bpy.ops operator.

    Allowed prefixes (default policy): mesh.*, object.*, material.*, scene.*,
    render.*, image.*, node.*, transform.*, view3d.*, curve.*, armature.*,
    pose.*, uv.*, particle.*, collection.*, world.*, anim.*, action.*,
    graph.*, nla.*, modifier.*, geometry.*

    Always denied: wm.quit_blender, wm.read_factory_settings, wm.open_mainfile,
    wm.save_mainfile, preferences.*, etc.

    Examples:
        call_operator("object.shade_smooth")
        call_operator("object.modifier_apply", {"modifier": "Subdivision"})
    """
    _get_policy().require("call_operator")
    args: dict = {"operator": operator, "kwargs": kwargs or {}}
    if execution_context:
        args["execution_context"] = execution_context
    return await _call("call_operator", args)


# ===========================================================================
# Mesh + scene basics (kept; batch-aware)
# ===========================================================================


@mcp.tool()
async def create_primitive(
    kind: str | list[dict] | None = None,
    name: str | None = None,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
    size: float = 1.0,
) -> dict:
    """Create one or many mesh primitives.

    kind: 'cube'|'sphere'|'cylinder'|'plane'|'cone'|'torus'|'monkey'|
          'ico_sphere'|'circle'|'grid'.

    Pass kind as a list of spec dicts to batch-create primitives in one undo step.
    """
    _get_policy().require("create_primitive")
    if isinstance(kind, list):
        return await _call("mesh.create_primitive", {"items": kind})
    args: dict = {"kind": kind, "size": size}
    if name is not None:
        args["name"] = name
    if location is not None:
        args["location"] = location
    if rotation is not None:
        args["rotation"] = rotation
    return await _call("mesh.create_primitive", args)


@mcp.tool()
async def set_transform(
    object: str | list[dict] | None = None,
    location: list[float] | None = None,
    rotation_euler: list[float] | None = None,
    scale: list[float] | None = None,
) -> dict:
    """Set location/rotation/scale on one or many objects."""
    _get_policy().require("set_transform")
    if isinstance(object, list):
        return await _call("object.transform", {"items": object})
    args: dict = {"object": object}
    if location is not None:
        args["location"] = location
    if rotation_euler is not None:
        args["rotation_euler"] = rotation_euler
    if scale is not None:
        args["scale"] = scale
    return await _call("object.transform", args)


@mcp.tool()
async def delete_object(object: str | list[dict] | None = None) -> dict:
    """Delete one or many objects."""
    policy = _get_policy()
    policy.require("delete_object")
    if policy.confirm_required_for("delete_object"):
        from .approval import request_approval

        outcome = await request_approval(
            tool="delete_object",
            args={"object": object},
        )
        if not outcome.available:
            return {
                "error": "CONFIRM_REQUIRED",
                "message": "delete_object requires user confirmation but no approval endpoint is available. Install/start the Blender MCP VS Code extension.",
                "detail": outcome.error,
            }
        if not outcome.approved:
            return {
                "error": "CONFIRM_DENIED",
                "message": "User rejected delete_object via approval prompt.",
            }
    if isinstance(object, list):
        return await _call("object.delete", {"items": object})
    return await _call("object.delete", {"object": object})


# ===========================================================================
# P4: Composition
# ===========================================================================


@mcp.tool()
async def create_objects(specs: list[dict]) -> dict:
    """Build many objects atomically (one undo step) from a spec list.

    Each spec:
      {
        "kind": "cube" | "sphere" | "cylinder" | ... | "light" | "camera" | "empty",
        "name": str?,
        "location": [x,y,z]?, "rotation": [x,y,z]?, "scale": [x,y,z]?,
        "size": float?,
        "material": str?,                 # mesh objects only
        "collection": str?,               # creates collection if missing
        "parent": str?,
        "modifiers": [{"type":"BEVEL","name":"B","properties":{...}}, ...]?,
        "properties": {rna_attr: value, ...}?,
        # light:    "light_type":"POINT|SUN|SPOT|AREA","energy":..,"color":..
        # camera:   "lens":..,"sensor_width":..,"dof":{...},"set_active":bool
        # empty:    "empty_type":"PLAIN_AXES|ARROWS|...","empty_display_size":..
      }
    """
    _get_policy().require("create_objects")
    return await _call("create_objects", {"specs": specs}, timeout=60.0)


@mcp.tool()
async def transaction(steps: list[dict], label: str | None = None) -> dict:
    """Atomically run a list of {tool, args} steps under one undo checkpoint.

    On any step failure: undo once and return failure info. On success: keep
    a single combined undo entry.

    Example:
        transaction([
          {"tool": "create_objects", "args": {"specs": [...]}},
          {"tool": "build_nodes", "args": {"target": "material:Gold!", "graph": {...}}},
          {"tool": "assign_material", "args": {"object": "Sphere", "material": "Gold"}},
        ], label="setup-shot-A")
    """
    _get_policy().require("transaction")
    args: dict = {"steps": steps}
    if label:
        args["label"] = label
    return await _call("transaction", args, timeout=120.0)


@mcp.tool()
async def apply_to_selection(
    tool: str,
    args: dict | None = None,
    name_key: str = "object",
) -> dict:
    """Run a tool against each currently selected object.

    Example:
        apply_to_selection("add_modifier",
                           {"type": "BEVEL", "properties": {"width": 0.02}})
    """
    _get_policy().require("apply_to_selection")
    return await _call(
        "apply_to_selection",
        {"tool": tool, "args": args or {}, "name_key": name_key},
    )


# ===========================================================================
# Animation (kept)
# ===========================================================================


@mcp.tool()
async def set_keyframe(
    object_name: str | list[dict] | None = None,
    data_path: str | None = None,
    frame: int | None = None,
    value: Any = None,
    index: int = -1,
) -> dict:
    """Insert a keyframe on an object property. Pass object_name as a list
    of spec dicts to batch-insert."""
    _get_policy().require("set_keyframe")
    if isinstance(object_name, list):
        return await _call("animation.keyframe", {"items": object_name})
    args: dict = {"object_name": object_name, "data_path": data_path, "frame": frame}
    if value is not None:
        args["value"] = value
    if index != -1:
        args["index"] = index
    return await _call("animation.keyframe", args)


# ===========================================================================
# P5: Asset library
# ===========================================================================


@mcp.tool()
async def import_asset(
    path: str,
    format: str | None = None,
    collection: str | None = None,
) -> dict:
    """Import an asset file (.blend/.glb/.gltf/.fbx/.obj/.usd/.stl/.ply/
    .abc/.x3d/.dae/.svg). Path is jail-checked against policy.allowed_roots."""
    policy = _get_policy()
    policy.require("import_asset")
    resolved = policy.validate_path(path)
    args: dict = {"path": str(resolved)}
    if format:
        args["format"] = format
    if collection:
        args["collection"] = collection
    return await _call("import_asset", args, timeout=120.0)


@mcp.tool()
async def link_blend(
    path: str,
    datablocks: list[dict],
    link: bool = True,
) -> dict:
    """Link or append datablocks from another .blend file.

    Args:
        path: .blend path (jail-checked).
        datablocks: [{"type":"Object","name":"Tree_01"}, ...]
        link: True to link (live), False to append (copy).
    """
    policy = _get_policy()
    policy.require("link_blend")
    resolved = policy.validate_path(path)
    return await _call(
        "link_blend",
        {"path": str(resolved), "datablocks": datablocks, "link": link},
        timeout=60.0,
    )


@mcp.tool()
async def list_assets(directory: str, recursive: bool = False) -> dict:
    """Enumerate importable asset files in a directory (jail-checked)."""
    policy = _get_policy()
    policy.require("list_assets")
    resolved = policy.validate_path(directory)
    return await _call(
        "list_assets",
        {"directory": str(resolved), "recursive": recursive},
        timeout=60.0,
    )


# ===========================================================================
# P6: Visual feedback
# ===========================================================================


@mcp.tool()
async def viewport_screenshot(
    width: int = 1024,
    height: int = 1024,
    view_camera: str | None = None,
    shading: str | None = None,
    show_overlays: bool = False,
) -> dict:
    """Capture the viewport as a PNG (base64).

    Args:
        width / height: 1..4096.
        view_camera: name of a camera object to render from (optional).
        shading: 'WIREFRAME'|'SOLID'|'MATERIAL'|'RENDERED' (optional).
        show_overlays: include grid/gizmos.
    """
    policy = _get_policy()
    policy.require("viewport_screenshot")
    policy.check_resolution(width, height)
    args: dict = {"w": width, "h": height, "show_overlays": show_overlays}
    if view_camera:
        args["view_camera"] = view_camera
    if shading:
        args["shading"] = shading
    return await _call("render.viewport_screenshot", args, timeout=60.0)


@mcp.tool()
async def render_region(
    x: int,
    y: int,
    w: int,
    h: int,
    samples: int = 32,
    engine: str | None = None,
    camera: str | None = None,
) -> dict:
    """Render a focused region of the scene with the engine (Cycles/EEVEE).

    Use for cheap iterative feedback on a specific area without committing
    to a full-scene render.
    """
    policy = _get_policy()
    policy.require("render_region")
    args: dict = {"x": x, "y": y, "w": w, "h": h, "samples": samples}
    if engine:
        args["engine"] = engine
    if camera:
        args["camera"] = camera
    return await _call("render.region", args, timeout=300.0)


@mcp.tool()
async def bake_preview(material: str, w: int = 256, h: int = 256) -> dict:
    """Render a quick preview of a material on a temporary plane (PNG b64)."""
    _get_policy().require("bake_preview")
    return await _call(
        "render.bake_preview",
        {"material": material, "w": w, "h": h},
        timeout=120.0,
    )


@mcp.tool()
async def scene_diff(snapshot_id: str | None = None) -> dict:
    """Snapshot/diff scene state.

    First call (no snapshot_id, or with a new id): returns baseline marker.
    Subsequent calls with the same snapshot_id: returns added/removed/modified.

    Tracks per-object: transform, modifier list, material assignments,
    visibility, parent, collection, mesh stats.
    """
    _get_policy().require("scene_diff")
    return await _call("scene_diff", {"snapshot_id": snapshot_id})


# ===========================================================================
# Execute Python (loosened in v2; controlled by add-on exec_mode)
# ===========================================================================


@mcp.tool()
async def execute_python(
    code: str,
    timeout: float = 10.0,
    mode: str | None = None,
) -> dict:
    """Execute Python in the Blender add-on sandbox.

    Modes (set via add-on prefs or per-call):
      - 'safe' (default): AST validator + restricted builtins. Allowed
         imports include bpy, mathutils, bmesh, math, pathlib, io, json,
         re, colorsys, random, itertools, functools, collections, ...
      - 'trusted': no validation, full Python (auth token still required).

    Returns {executed, mode, lines, result_preview} on success or
    {executed: False, error, error_type, traceback, failed_line, suggestion}.
    """
    policy = _get_policy()
    policy.require("execute_python")
    if policy.confirm_required_for("execute_python"):
        from .approval import request_approval

        outcome = await request_approval(
            tool="execute_python",
            args={"timeout": timeout, "mode": mode, "code_len": len(code)},
            code=code,
        )
        if not outcome.available:
            return {
                "error": "CONFIRM_REQUIRED",
                "message": "execute_python requires user confirmation but no approval endpoint is available. Install/start the Blender MCP VS Code extension.",
                "detail": outcome.error,
            }
        if not outcome.approved:
            return {
                "error": "CONFIRM_DENIED",
                "message": "User rejected execute_python via approval prompt.",
            }
    args: dict = {"code": code, "timeout": timeout}
    if mode:
        args["mode"] = mode
    return await _call("exec.python", args, timeout=max(timeout + 5, 35))


# ===========================================================================
# Entry point
# ===========================================================================


def main():
    """Entry point for the MCP server."""
    logging.basicConfig(
        level=logging.INFO, format="%(name)s %(levelname)s %(message)s"
    )
    mcp.run()


if __name__ == "__main__":
    main()
