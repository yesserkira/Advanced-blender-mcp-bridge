"""Blender MCP Server — exposes Blender capabilities as MCP tools."""

import logging
import os

from mcp.server.fastmcp import FastMCP

from .blender_client import BlenderWS, BlenderError
from .policy import Policy, PolicyDenied

logger = logging.getLogger("blender_mcp")

# Initialize MCP server
mcp = FastMCP("blender")

# Global client and policy — initialized in main()
_bl: BlenderWS | None = None
_policy: Policy | None = None


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
        policy_path = os.environ.get("BLENDER_MCP_POLICY")
        _policy = Policy.load(policy_path)
    return _policy


@mcp.tool()
async def ping() -> str:
    """Ping the Blender add-on to check connectivity. Returns 'pong' if connected."""
    bl = _get_client()
    result = await bl.call("ping")
    return str(result)


@mcp.tool()
async def get_scene_info(detail: str = "standard") -> dict:
    """Get information about the current Blender scene.

    Args:
        detail: Level of detail - 'summary', 'standard', or 'full'.
            - summary: scene name, object counts, frame range
            - standard: + per-object transforms, collections, world
            - full: + mesh stats, materials, modifiers, animation

    Returns:
        Scene information dict. Object names are wrapped in <<UNTRUSTED>> markers
        since they originate from user content.

    Always call this before modifying the scene to understand its current state.
    """
    policy = _get_policy()
    policy.require("get_scene_info")

    bl = _get_client()
    try:
        result = await bl.call("scene.get", {"detail": detail})
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}

    # Wrap object names in UNTRUSTED markers (§14.9)
    if "objects" in result:
        for obj in result["objects"]:
            if "name" in obj:
                obj["name"] = f"<<UNTRUSTED>>{obj['name']}<</UNTRUSTED>>"

    return result


@mcp.tool()
async def create_primitive(
    kind: str,
    name: str | None = None,
    location: list[float] | None = None,
    size: float = 1.0,
) -> dict:
    """Create a mesh primitive in Blender.

    Args:
        kind: Type of primitive - 'cube', 'sphere', 'cylinder', 'plane', 'cone', or 'torus'.
        name: Optional name for the created object.
        location: [x, y, z] position. Defaults to [0, 0, 0].
        size: Size of the primitive. Defaults to 1.0.

    Returns:
        Dict with 'name', 'polys', and 'vertices' of the created object.

    Example:
        create_primitive(kind="cube", name="MyCube", location=[0, 0, 1], size=2.0)
    """
    policy = _get_policy()
    policy.require("create_primitive")

    bl = _get_client()
    args = {
        "kind": kind,
        "location": location or [0, 0, 0],
        "size": size,
    }
    if name is not None:
        args["name"] = name

    try:
        return await bl.call("mesh.create_primitive", args)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def viewport_screenshot(width: int = 1024, height: int = 1024) -> dict:
    """Capture a screenshot of the Blender viewport.

    Args:
        width: Image width in pixels (max 4096). Defaults to 1024.
        height: Image height in pixels (max 4096). Defaults to 1024.

    Returns:
        Dict with 'image_base64' (PNG encoded as base64), 'mime', 'width', 'height'.

    Call this after making changes to verify the result visually.
    """
    policy = _get_policy()
    policy.require("viewport_screenshot")
    policy.check_resolution(width, height)

    bl = _get_client()
    try:
        return await bl.call("render.viewport_screenshot", {"w": width, "h": height})
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def set_transform(
    name: str,
    location: list[float] | None = None,
    rotation_euler: list[float] | None = None,
    scale: list[float] | None = None,
) -> dict:
    """Set the location, rotation, and/or scale of an existing object.

    Args:
        name: Name of the object to transform.
        location: [x, y, z] position. If omitted, location is unchanged.
        rotation_euler: [x, y, z] Euler rotation in radians. If omitted, unchanged.
        scale: [x, y, z] scale. If omitted, unchanged.

    Returns:
        Dict with 'name', 'location', 'rotation_euler', 'scale' after the change.

    Example:
        set_transform(name="Cube", location=[1, 0, 0], scale=[2, 2, 2])
    """
    policy = _get_policy()
    policy.require("set_transform")

    bl = _get_client()
    args = {"name": name}
    if location is not None:
        args["location"] = location
    if rotation_euler is not None:
        args["rotation_euler"] = rotation_euler
    if scale is not None:
        args["scale"] = scale

    try:
        result = await bl.call("object.transform", args)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}

    if "name" in result:
        result["name"] = f"<<UNTRUSTED>>{result['name']}<</UNTRUSTED>>"
    return result


@mcp.tool()
async def delete_object(name: str, confirm: bool = False) -> dict:
    """Delete an object from the scene by name.

    Args:
        name: Name of the object to delete.
        confirm: Confirmation flag (reserved for policy approval flow).

    Returns:
        Dict with 'deleted' (object name) and 'remaining_count'.

    Example:
        delete_object(name="Cube")
    """
    policy = _get_policy()
    policy.require("delete_object")

    if policy.confirm_required_for("delete_object") and not confirm:
        return {
            "error": "CONFIRM_REQUIRED",
            "message": "delete_object requires confirm=True (policy)",
        }

    bl = _get_client()
    try:
        return await bl.call("object.delete", {"name": name, "confirm": confirm})
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def select(names: list[str], active: str | None = None) -> dict:
    """Set the selection to the given objects.

    Args:
        names: List of object names to select. All other objects are deselected.
        active: Optional name of the object to set as active.

    Returns:
        Dict with 'selected' (list of names) and 'active' (name or null).

    Example:
        select(names=["Cube", "Light"], active="Cube")
    """
    policy = _get_policy()
    policy.require("select")

    bl = _get_client()
    args: dict = {"names": names}
    if active is not None:
        args["active"] = active

    try:
        result = await bl.call("selection.set", args)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}

    if "selected" in result:
        result["selected"] = [
            f"<<UNTRUSTED>>{n}<</UNTRUSTED>>" for n in result["selected"]
        ]
    if result.get("active"):
        result["active"] = f"<<UNTRUSTED>>{result['active']}<</UNTRUSTED>>"
    return result


@mcp.tool()
async def get_selection() -> dict:
    """Get the current object selection and active object.

    Returns:
        Dict with 'selected' (list of object names) and 'active' (name or null).

    Example:
        get_selection()
    """
    policy = _get_policy()
    policy.require("get_selection")

    bl = _get_client()
    try:
        result = await bl.call("selection.get", {})
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}

    if "selected" in result:
        result["selected"] = [
            f"<<UNTRUSTED>>{n}<</UNTRUSTED>>" for n in result["selected"]
        ]
    if result.get("active"):
        result["active"] = f"<<UNTRUSTED>>{result['active']}<</UNTRUSTED>>"
    return result


@mcp.tool()
async def create_material_pbr(
    name: str,
    base_color: list[float] | None = None,
    metallic: float = 0.0,
    roughness: float = 0.5,
    emission_color: list[float] | None = None,
    emission_strength: float | None = None,
    alpha: float | None = None,
) -> dict:
    """Create a Principled BSDF material in Blender.

    Args:
        name: Material name.
        base_color: [r, g, b, a] base color. Defaults to [0.8, 0.8, 0.8, 1.0].
        metallic: Metallic factor 0-1. Defaults to 0.0.
        roughness: Roughness factor 0-1. Defaults to 0.5.
        emission_color: [r, g, b, a] emission color (optional).
        emission_strength: Emission strength (optional).
        alpha: Alpha transparency 0-1 (optional).

    Returns:
        Dict with 'name', 'node_tree', and 'inputs_set' listing which inputs were configured.

    Example:
        create_material_pbr(name="RedMetal", base_color=[1,0,0,1], metallic=0.9, roughness=0.2)
    """
    policy = _get_policy()
    policy.require("create_material_pbr")

    bl = _get_client()
    args = {"name": name}
    if base_color is not None:
        args["base_color"] = base_color
    if metallic != 0.0:
        args["metallic"] = metallic
    if roughness != 0.5:
        args["roughness"] = roughness
    if emission_color is not None:
        args["emission_color"] = emission_color
    if emission_strength is not None:
        args["emission_strength"] = emission_strength
    if alpha is not None:
        args["alpha"] = alpha

    try:
        return await bl.call("material.create_pbr", args)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def assign_material(
    object_name: str,
    material_name: str,
    slot: int = 0,
) -> dict:
    """Assign an existing material to an object in Blender.

    Args:
        object_name: Name of the target object.
        material_name: Name of the material to assign.
        slot: Material slot index. Defaults to 0. If the object has no slots, one is created.

    Returns:
        Dict with 'object', 'material', and 'slot' index used.

    Example:
        assign_material(object_name="Cube", material_name="RedMetal", slot=0)
    """
    policy = _get_policy()
    policy.require("assign_material")

    bl = _get_client()
    args = {
        "object_name": object_name,
        "material_name": material_name,
        "slot": slot,
    }

    try:
        return await bl.call("material.assign", args)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def create_light(
    type: str,
    name: str | None = None,
    location: list[float] | None = None,
    energy: float | None = None,
    color: list[float] | None = None,
    radius: float | None = None,
    spot_size: float | None = None,
    spot_blend: float | None = None,
    size: float | None = None,
) -> dict:
    """Create a light object in Blender.

    Args:
        type: Light type - 'POINT', 'SUN', 'SPOT', or 'AREA'.
        name: Optional name for the light object.
        location: [x, y, z] position. Defaults to [0, 0, 0].
        energy: Light power. Default 1000 for POINT/SPOT/AREA, 1.0 for SUN.
        color: [r, g, b] color in 0-1 range. Defaults to [1, 1, 1].
        radius: Shadow soft size / radius.
        spot_size: Spot cone angle in radians (SPOT only).
        spot_blend: Spot edge softness 0-1 (SPOT only).
        size: Area light size (AREA only).

    Returns:
        Dict with 'name', 'type', 'location', and 'energy' of the created light.

    Example:
        create_light(type="POINT", name="KeyLight", location=[3, -2, 4], energy=800)
    """
    policy = _get_policy()
    policy.require("create_light")

    bl = _get_client()
    args = {"type": type}
    if name is not None:
        args["name"] = name
    if location is not None:
        args["location"] = location
    if energy is not None:
        args["energy"] = energy
    if color is not None:
        args["color"] = color
    if radius is not None:
        args["radius"] = radius
    if spot_size is not None:
        args["spot_size"] = spot_size
    if spot_blend is not None:
        args["spot_blend"] = spot_blend
    if size is not None:
        args["size"] = size

    try:
        return await bl.call("light.create", args)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def create_camera(
    name: str | None = None,
    location: list[float] | None = None,
    rotation_euler: list[float] | None = None,
    lens: float = 50.0,
    clip_start: float = 0.1,
    clip_end: float = 1000.0,
    sensor_width: float = 36.0,
) -> dict:
    """Create a camera object in Blender.

    Args:
        name: Optional name for the camera object.
        location: [x, y, z] position. Defaults to [0, 0, 5].
        rotation_euler: [rx, ry, rz] Euler rotation in radians. Defaults to [0, 0, 0].
        lens: Focal length in mm. Defaults to 50.
        clip_start: Near clipping distance. Defaults to 0.1.
        clip_end: Far clipping distance. Defaults to 1000.
        sensor_width: Sensor width in mm. Defaults to 36.

    Returns:
        Dict with 'name', 'lens', and 'location' of the created camera.

    Example:
        create_camera(name="MainCam", location=[7, -5, 3], lens=85)
    """
    policy = _get_policy()
    policy.require("create_camera")

    bl = _get_client()
    args = {}
    if name is not None:
        args["name"] = name
    if location is not None:
        args["location"] = location
    if rotation_euler is not None:
        args["rotation_euler"] = rotation_euler
    args["lens"] = lens
    args["clip_start"] = clip_start
    args["clip_end"] = clip_end
    args["sensor_width"] = sensor_width

    try:
        return await bl.call("camera.create", args)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def set_active_camera(name: str) -> dict:
    """Set the active camera for the current Blender scene.

    Args:
        name: Name of an existing camera object to set as active.

    Returns:
        Dict with 'active_camera' set to the name of the now-active camera.

    Example:
        set_active_camera(name="MainCam")
    """
    policy = _get_policy()
    policy.require("set_active_camera")

    bl = _get_client()
    try:
        return await bl.call("camera.set_active", {"name": name})
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def apply_modifier(
    object_name: str,
    modifier_type: str,
    modifier_name: str | None = None,
    params: dict | None = None,
) -> dict:
    """Add a modifier to an object in Blender.

    Args:
        object_name: Name of the target object.
        modifier_type: Type of modifier - 'SUBSURF', 'BEVEL', 'MIRROR', 'ARRAY', or 'BOOLEAN'.
        modifier_name: Optional display name for the modifier. Defaults to modifier_type.
        params: Modifier-specific parameters:
            - SUBSURF: levels (int), render_levels (int)
            - BEVEL: width (float), segments (int)
            - MIRROR: use_axis ([bool, bool, bool])
            - ARRAY: count (int), relative_offset_displace ([f, f, f])
            - BOOLEAN: operation ("INTERSECT"|"UNION"|"DIFFERENCE"), object (str)

    Returns:
        Dict with 'object', 'modifier_name', 'modifier_type', and 'index'.

    Example:
        apply_modifier(object_name="Cube", modifier_type="SUBSURF", params={"levels": 3})
    """
    policy = _get_policy()
    policy.require("apply_modifier")

    bl = _get_client()
    args = {
        "object_name": object_name,
        "modifier_type": modifier_type,
    }
    if modifier_name is not None:
        args["modifier_name"] = modifier_name
    if params is not None:
        args["params"] = params

    try:
        return await bl.call("modifier.add", args)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def set_keyframe(
    object_name: str,
    data_path: str,
    frame: int,
    value: float | list[float] | None = None,
    index: int | None = None,
) -> dict:
    """Insert a keyframe on an object property in Blender.

    Args:
        object_name: Name of the target object.
        data_path: Property path, e.g. 'location', 'rotation_euler', 'scale'.
        frame: Frame number to insert the keyframe at.
        value: Optional value to set before inserting the keyframe. Can be a float or [f,f,f].
        index: Optional channel index. -1 for all channels (default).

    Returns:
        Dict with 'object', 'data_path', 'frame', and 'value'.

    Example:
        set_keyframe(object_name="Cube", data_path="location", frame=1, value=[0, 0, 0])
    """
    policy = _get_policy()
    policy.require("set_keyframe")

    bl = _get_client()
    args = {
        "object_name": object_name,
        "data_path": data_path,
        "frame": frame,
    }
    if value is not None:
        args["value"] = value
    if index is not None:
        args["index"] = index

    try:
        return await bl.call("animation.keyframe", args)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def edit_mesh(
    object_name: str,
    operation: str,
    params: dict | None = None,
) -> dict:
    """Edit a mesh using bmesh operations.

    Args:
        object_name: Name of the mesh object to edit.
        operation: Edit operation - 'extrude', 'bevel', 'loop_cut', or 'boolean'.
        params: Operation-specific parameters:
            extrude: {"offset": float, "direction": [x,y,z]}
            bevel: {"offset": float, "segments": int, "affect": "EDGES"|"VERTICES"}
            loop_cut: {"cuts": int, "edge_index": int}
            boolean: {"other_object": str, "operation": "UNION"|"INTERSECT"|"DIFFERENCE"}

    Returns:
        Dict with 'object', 'operation', 'vertices', 'polys', and operation-specific fields.

    Example:
        edit_mesh(object_name="Cube", operation="extrude", params={"offset": 2.0, "direction": [0, 0, 1]})
    """
    policy = _get_policy()
    policy.require("edit_mesh")

    bl = _get_client()
    args = {
        "object_name": object_name,
        "operation": operation,
    }
    if params is not None:
        args["params"] = params

    try:
        return await bl.call("mesh.edit", args)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def begin_transaction(transaction_id: str) -> dict:
    """Begin a new transaction to group multiple operations into one undo checkpoint.

    Args:
        transaction_id: Unique identifier for this transaction.

    Returns:
        Dict with 'transaction_id' and 'status' ("active").

    Example:
        begin_transaction(transaction_id="build-scene-001")
    """
    policy = _get_policy()
    policy.require("begin_transaction")

    bl = _get_client()
    try:
        return await bl.call("transaction.begin", {"transaction_id": transaction_id})
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def commit_transaction(transaction_id: str) -> dict:
    """Commit an active transaction, finalizing its undo checkpoint.

    Args:
        transaction_id: ID of the active transaction to commit.

    Returns:
        Dict with 'transaction_id', 'status' ("committed"), and 'op_count'.

    Example:
        commit_transaction(transaction_id="build-scene-001")
    """
    policy = _get_policy()
    policy.require("commit_transaction")

    bl = _get_client()
    try:
        return await bl.call("transaction.commit", {"transaction_id": transaction_id})
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def rollback_transaction(transaction_id: str) -> dict:
    """Roll back an active transaction, undoing all operations since begin.

    Args:
        transaction_id: ID of the active transaction to roll back.

    Returns:
        Dict with 'transaction_id' and 'status' ("rolled_back").

    Example:
        rollback_transaction(transaction_id="build-scene-001")
    """
    policy = _get_policy()
    policy.require("rollback_transaction")

    bl = _get_client()
    try:
        return await bl.call("transaction.rollback", {"transaction_id": transaction_id})
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def execute_python(code: str, timeout: float = 10.0) -> dict:
    """Execute validated Python code in Blender's restricted environment.

    The code is first validated by an AST scanner that rejects dangerous
    constructs (os/sys/subprocess imports, eval/exec calls, dunder access).
    Only bpy, mathutils, bmesh, and math modules are available.

    Args:
        code: Python source code to execute. Must pass AST validation.
        timeout: Maximum execution time in seconds (default 10, max 30).

    Returns:
        Dict with 'executed' (bool), 'lines' (int) on success,
        or 'executed' (false), 'error', 'traceback' on failure.

    Example:
        execute_python(code="bpy.ops.mesh.primitive_cube_add(location=(1,0,0))")
    """
    policy = _get_policy()
    policy.require("execute_python")

    if policy.confirm_required_for("execute_python"):
        return {
            "error": "CONFIRM_REQUIRED",
            "message": "execute_python requires user confirmation (policy)",
        }

    bl = _get_client()
    try:
        return await bl.call("exec.python", {"code": code, "timeout": timeout})
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def suggest_fix(code: str, error: str, traceback_text: str = "") -> dict:
    """Suggest a fix for failed Python code execution.

    Call this after execute_python returns executed=False.
    Sends the failed code back with the error for re-analysis.

    Args:
        code: The original code that failed.
        error: The error message.
        traceback_text: The traceback from the failure.

    Returns:
        Dict with 'suggestion', 'original_code', and 'error'.

    Example:
        suggest_fix(code="bpy.data.obejcts['Cube']", error="AttributeError: ...", traceback_text="...")
    """
    policy = _get_policy()
    policy.require("suggest_fix")

    suggestions = []
    if "NameError" in error:
        suggestions.append("Check that all names are available in the restricted environment (bpy, mathutils, bmesh, math only)")
    if "AttributeError" in error:
        suggestions.append("Verify the attribute exists in the Blender Python API for your Blender version")
    if "not defined" in error:
        suggestions.append("The restricted environment only provides: bpy, mathutils, bmesh, math")
    if "TypeError" in error:
        suggestions.append("Check the function signature — wrong number or type of arguments")
    if "KeyError" in error:
        suggestions.append("Available keys can be found via bpy.data.*.keys() or collection.keys()")
    if "IndexError" in error:
        suggestions.append("Check the collection length first with len() before indexing")
    if not suggestions:
        suggestions.append("Review the traceback and try a simpler approach")
    return {
        "suggestion": "; ".join(suggestions),
        "original_code": code,
        "error": error,
    }


@mcp.tool()
async def import_asset(
    path: str,
    format: str | None = None,
    location: list[float] | None = None,
    scale: float = 1.0,
) -> dict:
    """Import a 3D asset file into Blender.

    Args:
        path: Path to the asset file. Must be within allowed roots (policy).
        format: File format override. Auto-detected from extension if omitted.
                Supported: fbx, obj, glb, gltf, stl.
        location: [x, y, z] position for imported objects.
        scale: Scale factor for imported objects. Defaults to 1.0.

    Returns:
        Dict with 'imported_objects' (list of names), 'format', and 'path'.

    Example:
        import_asset(path="/models/chair.glb", location=[0, 0, 0], scale=1.0)
    """
    policy = _get_policy()
    policy.require("import_asset")
    resolved = policy.validate_path(path)

    bl = _get_client()
    args = {
        "path": str(resolved),
        "_allowed_roots": [str(r) for r in (policy.allowed_roots or [])],
    }
    if format is not None:
        args["format"] = format
    if location is not None:
        args["location"] = location
    if scale != 1.0:
        args["scale"] = scale

    try:
        result = await bl.call("asset.import", args)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}

    if "imported_objects" in result:
        result["imported_objects"] = [
            f"<<UNTRUSTED>>{n}<</UNTRUSTED>>" for n in result["imported_objects"]
        ]
    return result


@mcp.tool()
async def build_geonodes(
    object_name: str,
    nodes: list[dict],
    links: list[dict],
    modifier_name: str = "AI_GeoNodes",
    group_name: str | None = None,
    group_inputs: list[dict] | None = None,
    group_outputs: list[dict] | None = None,
) -> dict:
    """Build a Geometry Nodes modifier from a declarative graph description.

    Args:
        object_name: Name of the target mesh object.
        nodes: List of node definitions. Each has 'id' (str), 'type' (str, e.g. "GeometryNodeMeshCube"),
               optional 'label' (str), 'location' ([x,y]), and 'inputs' (dict of socket_name->value).
        links: List of connections. Each has 'from_node', 'from_socket', 'to_node', 'to_socket'.
               Use "group_input"/"group_output" as special node ids.
        modifier_name: Display name for the modifier. Defaults to "AI_GeoNodes".
        group_name: Name for the node group. Defaults to modifier_name.
        group_inputs: Optional group input sockets. Each has 'name' and 'type'.
        group_outputs: Optional group output sockets. Each has 'name' and 'type'.

    Returns:
        Dict with 'object', 'modifier', 'node_count', 'link_count'.

    Example:
        build_geonodes(
            object_name="Cube",
            nodes=[
                {"id": "cube", "type": "GeometryNodeMeshCube", "inputs": {"Size": [2, 2, 2]}},
                {"id": "setpos", "type": "GeometryNodeSetPosition"}
            ],
            links=[
                {"from_node": "cube", "from_socket": "Mesh", "to_node": "setpos", "to_socket": "Geometry"},
                {"from_node": "setpos", "from_socket": "Geometry", "to_node": "group_output", "to_socket": "Geometry"}
            ]
        )
    """
    policy = _get_policy()
    policy.require("build_geonodes")

    bl = _get_client()
    args = {
        "object_name": object_name,
        "modifier_name": modifier_name,
        "group_name": group_name or modifier_name,
        "nodes": nodes,
        "links": links,
    }
    if group_inputs:
        args["group_inputs"] = group_inputs
    if group_outputs:
        args["group_outputs"] = group_outputs

    try:
        return await bl.call("geonodes.build", args, timeout=60.0)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


@mcp.tool()
async def set_material_node_graph(
    material_name: str,
    nodes: list[dict],
    links: list[dict] | None = None,
    output_node: str | None = None,
    create_if_missing: bool = True,
    clear_existing: bool = True,
) -> dict:
    """Build a complete shader node graph on a material from a declarative description.

    Args:
        material_name: Name of the material. Created if it doesn't exist (when create_if_missing=True).
        nodes: List of node definitions. Each has 'id' (str), 'type' (str, e.g. "ShaderNodeBsdfPrincipled"),
               optional 'label', 'location' ([x,y]), and 'inputs' (dict of socket_name->value).
        links: List of connections. Each has 'from_node', 'from_socket', 'to_node', 'to_socket'.
               Use "material_output" as special id for the Material Output node.
        output_node: ID of the node to auto-connect to Material Output's Surface input.
        create_if_missing: Create material if it doesn't exist. Defaults to True.
        clear_existing: Clear existing nodes before building. Defaults to True.

    Returns:
        Dict with 'material', 'node_count', 'link_count', 'nodes_created'.

    Example:
        set_material_node_graph(
            material_name="ProceduralRock",
            nodes=[
                {"id": "principled", "type": "ShaderNodeBsdfPrincipled"},
                {"id": "noise", "type": "ShaderNodeTexNoise", "inputs": {"Scale": 8.0}},
                {"id": "bump", "type": "ShaderNodeBump", "inputs": {"Strength": 0.3}}
            ],
            links=[
                {"from_node": "noise", "from_socket": "Fac", "to_node": "bump", "to_socket": "Height"},
                {"from_node": "bump", "from_socket": "Normal", "to_node": "principled", "to_socket": "Normal"},
                {"from_node": "noise", "from_socket": "Color", "to_node": "principled", "to_socket": "Base Color"}
            ],
            output_node="principled"
        )
    """
    policy = _get_policy()
    policy.require("set_material_node_graph")

    bl = _get_client()
    args = {
        "material_name": material_name,
        "nodes": nodes,
        "create_if_missing": create_if_missing,
        "clear_existing": clear_existing,
    }
    if links:
        args["links"] = links
    if output_node:
        args["output_node"] = output_node

    try:
        return await bl.call("shader.set_graph", args, timeout=60.0)
    except BlenderError as e:
        return {"error": e.code, "message": str(e)}


def main():
    """Entry point for the MCP server."""
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    mcp.run()


if __name__ == "__main__":
    main()
