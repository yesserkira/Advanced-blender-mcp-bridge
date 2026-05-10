"""Unified node graph builder — shaders, geometry nodes, world, compositor.

Replaces v1's three overlapping tools (create_material_pbr,
set_material_node_graph, build_geonodes) with a single declarative DSL.

Target syntax:
    "material:Gold"                     -> material.node_tree
    "material:Gold!"                    -> create if missing, then node_tree
    "world"                             -> active scene world.node_tree
    "scene.compositor"                  -> scene.node_tree (compositor)
    "object:Suzanne.modifiers.GeoNodes" -> Geometry-Nodes modifier's node_tree
                                           (modifier is created if missing)
"""

from __future__ import annotations

from typing import Any

import bpy

from . import register_capability


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


def _resolve_node_tree(target: str) -> tuple[Any, Any]:
    """Return (host_id, node_tree) for the target string.

    host_id is the datablock holding the tree (for naming the modifier etc).
    """
    if not target or not isinstance(target, str):
        raise ValueError("target must be a string")

    if target == "world" or target == "scene.world":
        scene = bpy.context.scene
        world = scene.world
        if world is None:
            world = bpy.data.worlds.new("World")
            scene.world = world
        # Blender 5.0 deprecated use_nodes (always True); kept for 4.x compat.
        if hasattr(world, "use_nodes") and not world.use_nodes:
            world.use_nodes = True
        return world, world.node_tree

    if target == "scene.compositor":
        scene = bpy.context.scene
        # Blender 5.0 deprecated use_nodes (always True); kept for 4.x compat.
        if hasattr(scene, "use_nodes") and not scene.use_nodes:
            scene.use_nodes = True
        # Blender 5.0 removed scene.node_tree; use compositing_node_group.
        if hasattr(scene, "compositing_node_group"):
            tree = scene.compositing_node_group
            if tree is None:
                tree = bpy.data.node_groups.new("Compositing", "CompositorNodeTree")
                scene.compositing_node_group = tree
            return scene, tree
        return scene, scene.node_tree

    # material:Name or material:Name!
    if target.startswith("material:"):
        rest = target[len("material:"):]
        create = rest.endswith("!")
        if create:
            rest = rest[:-1]
        name = rest
        mat = bpy.data.materials.get(name)
        if mat is None:
            if not create:
                raise ValueError(
                    f"Material '{name}' not found (use 'material:{name}!' to create)"
                )
            mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        return mat, mat.node_tree

    # object:Name.modifiers.ModifierName  (Geometry Nodes modifier)
    if target.startswith("object:"):
        rest = target[len("object:"):]
        if ".modifiers." not in rest:
            raise ValueError(
                "object target must reference a Geometry-Nodes modifier: "
                "'object:Name.modifiers.ModName'"
            )
        obj_name, mod_name = rest.split(".modifiers.", 1)
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            raise ValueError(f"Object not found: {obj_name}")
        mod = obj.modifiers.get(mod_name)
        if mod is None:
            mod = obj.modifiers.new(name=mod_name, type="NODES")
        if mod.type != "NODES":
            raise ValueError(
                f"Modifier '{mod_name}' is type {mod.type}, not NODES"
            )
        if mod.node_group is None:
            grp = bpy.data.node_groups.new(mod_name, "GeometryNodeTree")
            # Default Geometry input/output sockets
            grp.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
            grp.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
            mod.node_group = grp
        return mod, mod.node_group

    raise ValueError(
        f"Unknown node-tree target: '{target}'. "
        f"Use 'material:Name[!]', 'world', 'scene.compositor', "
        f"or 'object:Name.modifiers.ModName'."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_socket(sockets, key):
    """Find a socket by name (case-insensitive), type-qualified name, or index.

    Supported forms:
        int       — direct index, e.g. 6
        "6"       — string index
        "A"       — first socket named 'A' (case-insensitive)
        "A:Color" — first socket named 'A' whose type matches RGBA / Color
        "A:Float" — first socket named 'A' whose type is VALUE / Float
        "A:Vector"— first socket named 'A' whose type is VECTOR

    The type-qualified form is critical for nodes like ShaderNodeMix where
    Float / Vector / Color variants share socket names ('A', 'B', 'Result').
    """
    # Direct integer index
    if isinstance(key, int):
        if key < 0 or key >= len(sockets):
            raise ValueError(f"Socket index {key} out of range (0..{len(sockets) - 1})")
        return sockets[key]
    if not isinstance(key, str):
        raise ValueError(f"socket key must be int or str, got {type(key).__name__}")

    # Numeric string index ("6")
    if key.isdigit() or (key.startswith("-") and key[1:].isdigit()):
        idx = int(key)
        if -len(sockets) <= idx < len(sockets):
            return sockets[idx]
        raise ValueError(f"Socket index {idx} out of range")

    # Type-qualified ("A:Color")
    type_alias = {
        "color": {"RGBA"},
        "rgba":  {"RGBA"},
        "float": {"VALUE"},
        "value": {"VALUE"},
        "vector": {"VECTOR"},
        "vec":    {"VECTOR"},
        "int":    {"INT"},
        "bool":   {"BOOLEAN"},
        "string": {"STRING"},
        "shader": {"SHADER"},
    }
    name_part, type_part = key, None
    if ":" in key:
        name_part, type_part = key.split(":", 1)
        type_part = type_part.strip().lower()

    name_lower = name_part.strip().lower()
    candidates = [s for s in sockets if s.name.lower() == name_lower]
    if not candidates:
        # Fall back to exact-case match on full key (legacy behaviour)
        for s in sockets:
            if s.name == key:
                return s
        available = [f"{s.name}({s.type})" for s in sockets]
        raise ValueError(f"Socket '{key}' not found. Available: {available}")

    if type_part is None:
        return candidates[0]

    wanted = type_alias.get(type_part)
    if wanted is None:
        # Treat unknown qualifier as exact RNA type match
        wanted = {type_part.upper()}
    for s in candidates:
        if s.type in wanted:
            return s
    available = [f"{s.name}({s.type})" for s in candidates]
    raise ValueError(
        f"Socket '{key}' not found with that type. "
        f"Candidates with name '{name_part}': {available}"
    )


def _coerce_socket_value(socket, value):
    if value is None:
        return None
    sk_type = socket.type
    if sk_type in {"VECTOR", "RGBA", "ROTATION"} and isinstance(value, (list, tuple)):
        try:
            cur = socket.default_value
            n = len(cur)
            v = list(value)
            while len(v) < n:
                v.append(0.0 if sk_type != "RGBA" else 1.0)
            return type(cur)(v[:n])
        except Exception:
            return tuple(value)
    if sk_type == "VALUE":
        return float(value)
    if sk_type == "INT":
        return int(value)
    if sk_type == "BOOLEAN":
        return bool(value)
    if sk_type == "STRING":
        return str(value)
    if sk_type == "OBJECT" and isinstance(value, str):
        return bpy.data.objects.get(value)
    if sk_type == "MATERIAL" and isinstance(value, str):
        return bpy.data.materials.get(value)
    if sk_type == "IMAGE" and isinstance(value, str):
        return bpy.data.images.get(value)
    return value


def _set_node_property(node, key, value):
    """Set a non-socket node property (image, space, uv_map, ...)."""
    rna_props = {p.identifier: p for p in node.bl_rna.properties}
    prop = rna_props.get(key)
    if prop is None:
        return False, f"unknown property '{key}'"
    if prop.is_readonly:
        return False, f"'{key}' is readonly"
    try:
        if prop.type == "POINTER":
            fixed = getattr(prop.fixed_type, "identifier", "")
            if isinstance(value, str):
                if fixed == "Image":
                    value = bpy.data.images.get(value)
                elif fixed == "Object":
                    value = bpy.data.objects.get(value)
                elif fixed == "Material":
                    value = bpy.data.materials.get(value)
                elif fixed == "NodeTree":
                    value = bpy.data.node_groups.get(value)
        setattr(node, key, value)
        return True, None
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Deprecated / removed node types (Blender 4.x changes)
# ---------------------------------------------------------------------------

# Maps a removed/renamed node type to its closest replacement (or None).
_DEPRECATED_NODES: dict[str, dict] = {
    "ShaderNodeTexMusgrave": {
        "replacement": "ShaderNodeTexNoise",
        "note": "Musgrave was merged into Noise Texture in Blender 4.1+. "
                "Use ShaderNodeTexNoise with type='MULTIFRACTAL' (or other modes).",
    },
    "ShaderNodeBsdfHair": {
        "replacement": "ShaderNodeBsdfHairPrincipled",
        "note": "Use the Principled Hair BSDF.",
    },
}


def _check_deprecated(ntype: str) -> dict | None:
    info = _DEPRECATED_NODES.get(ntype)
    if not info:
        return None
    return {"type": ntype, **info}


# ---------------------------------------------------------------------------
# Color Ramp configuration
# ---------------------------------------------------------------------------


def _configure_color_ramp(node, spec: dict | list) -> tuple[bool, str | None]:
    """Configure a Color Ramp (ValToRGB / Map Range with ramp etc.).

    spec can be either:
        list of stops: [{"position": 0.0, "color": [r,g,b,a]}, ...]
        dict: {"interpolation": "LINEAR"|"CONSTANT"|"EASE"|"B_SPLINE"|"CARDINAL"|...,
               "color_mode": "RGB"|"HSV"|"HSL", "stops": [...]}
    """
    ramp = getattr(node, "color_ramp", None)
    if ramp is None:
        return False, f"node '{node.name}' has no color_ramp"

    if isinstance(spec, list):
        stops = spec
        config = {}
    else:
        stops = spec.get("stops") or []
        config = spec

    if "interpolation" in config:
        try:
            ramp.interpolation = config["interpolation"]
        except Exception as e:
            return False, f"interpolation: {e}"
    if "color_mode" in config:
        try:
            ramp.color_mode = config["color_mode"]
        except Exception as e:
            return False, f"color_mode: {e}"
    if "hue_interpolation" in config:
        try:
            ramp.hue_interpolation = config["hue_interpolation"]
        except Exception:
            pass

    if not stops:
        return True, None

    # Adjust element count: ramp starts with 2 elements
    elements = ramp.elements
    while len(elements) > len(stops):
        elements.remove(elements[-1])
    while len(elements) < len(stops):
        elements.new(0.5)

    for i, stop in enumerate(stops):
        try:
            elements[i].position = float(stop.get("position", i / max(1, len(stops) - 1)))
            color = stop.get("color")
            if color is not None:
                c = list(color)
                while len(c) < 4:
                    c.append(1.0)
                elements[i].color = c[:4]
        except Exception as e:
            return False, f"stop[{i}]: {e}"
    return True, None


# ---------------------------------------------------------------------------
# Curve / RGB Curves configuration
# ---------------------------------------------------------------------------


def _configure_curves(node, spec: dict) -> tuple[bool, str | None]:
    """Configure a node with curve mappings (RGBCurves, FloatCurve, VectorCurves).

    spec: {
        "curves": [
            {  # one entry per curve channel (R, G, B, Combined / X, Y, Z / value)
                "points": [{"x": 0.0, "y": 0.0, "handle_type": "AUTO"}, ...],
                "extend": "EXTRAPOLATED" | "HORIZONTAL"
            },
            ...
        ],
        "black_level": [r,g,b],   # optional, RGBCurves only
        "white_level": [r,g,b],   # optional, RGBCurves only
        "clip": {"min_x":0,"max_x":1,"min_y":0,"max_y":1}  # optional
    }
    """
    mapping = getattr(node, "mapping", None)
    if mapping is None:
        return False, f"node '{node.name}' has no curve mapping"

    curves_spec = spec.get("curves") or []
    for ci, cspec in enumerate(curves_spec):
        if ci >= len(mapping.curves):
            break
        curve = mapping.curves[ci]
        pts_spec = cspec.get("points") or []
        # Curves start with 2 points; add/remove to match
        while len(curve.points) > len(pts_spec) and len(curve.points) > 2:
            curve.points.remove(curve.points[-1])
        while len(curve.points) < len(pts_spec):
            curve.points.new(0.5, 0.5)
        for pi, p in enumerate(pts_spec):
            try:
                curve.points[pi].location = (float(p.get("x", 0)), float(p.get("y", 0)))
                ht = p.get("handle_type")
                if ht:
                    curve.points[pi].handle_type = ht
            except Exception as e:
                return False, f"curves[{ci}].points[{pi}]: {e}"
        if "extend" in cspec:
            try:
                curve.extend = cspec["extend"]
            except Exception:
                pass

    if "black_level" in spec and hasattr(mapping, "black_level"):
        try:
            mapping.black_level = spec["black_level"]
        except Exception:
            pass
    if "white_level" in spec and hasattr(mapping, "white_level"):
        try:
            mapping.white_level = spec["white_level"]
        except Exception:
            pass
    clip = spec.get("clip")
    if clip:
        for k in ("min_x", "max_x", "min_y", "max_y"):
            if k in clip and hasattr(mapping, k):
                try:
                    setattr(mapping, k, float(clip[k]))
                except Exception:
                    pass

    try:
        mapping.update()
    except Exception:
        pass
    return True, None


# ---------------------------------------------------------------------------
# build_nodes
# ---------------------------------------------------------------------------


def build_nodes(args: dict) -> dict:
    """Build a node graph declaratively.

    Args:
        args: {
            "target": str,
            "graph": {
                "nodes": [
                    {
                        "name": str (graph-local id),
                        "type": str (RNA class, e.g. ShaderNodeBsdfPrincipled),
                        "location": [x, y] (optional),
                        "label": str (optional),
                        "inputs": {socket_name_or_index: value, ...} (optional),
                        "properties": {prop_name: value, ...} (optional, for
                            non-socket attributes like image, space, uv_map),
                    },
                    ...
                ],
                "links": [
                    {"from": "node_name.socket", "to": "node_name.socket"},
                    ...
                ],
            },
            "clear": bool (default True),
        }
    """
    target = args.get("target")
    graph = args.get("graph") or {}
    clear = bool(args.get("clear", True))

    host, tree = _resolve_node_tree(target)

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:build_nodes:{cmd_id}")

    nodes_def = graph.get("nodes") or []
    links_def = graph.get("links") or []

    if clear:
        # Clear all nodes; for geometry-node trees, recreate Group I/O.
        for n in list(tree.nodes):
            tree.nodes.remove(n)
        # Re-add minimal output for materials/world to keep tree usable
        if host and host.bl_rna.identifier == "Material":
            out = tree.nodes.new("ShaderNodeOutputMaterial")
            out.location = (400, 0)
            out.name = out.label = "_default_output"
        elif host and host.bl_rna.identifier == "World":
            out = tree.nodes.new("ShaderNodeOutputWorld")
            out.location = (400, 0)
            out.name = out.label = "_default_output"
        elif tree.bl_rna.identifier == "GeometryNodeTree":
            ginp = tree.nodes.new("NodeGroupInput")
            ginp.location = (-400, 0)
            ginp.name = ginp.label = "group_input"
            gout = tree.nodes.new("NodeGroupOutput")
            gout.location = (400, 0)
            gout.name = gout.label = "group_output"

    # Map from graph-local name -> created node
    node_map: dict[str, Any] = {}
    for n in tree.nodes:
        node_map[n.name] = n
        if n.label:
            node_map[n.label] = n

    # ------------------------------------------------------------------
    # Selective removal (only meaningful when clear=False, otherwise the
    # tree was already wiped). Lets the AI surgically edit an existing
    # graph instead of rebuilding from scratch.
    # ------------------------------------------------------------------
    removed_nodes: list[str] = []
    removed_links: list[dict] = []
    if not clear:
        for nname in (graph.get("remove_nodes") or []):
            n = node_map.get(nname) or tree.nodes.get(nname)
            if n is not None:
                tree.nodes.remove(n)
                removed_nodes.append(nname)
                # Drop from map
                node_map.pop(nname, None)
        for spec in (graph.get("remove_links") or []):
            try:
                from_str = spec.get("from")
                to_str = spec.get("to")
                if not from_str or not to_str:
                    continue
                from_name, from_sock = from_str.split(".", 1)
                to_name, to_sock = to_str.split(".", 1)
                target_link = None
                for lk in tree.links:
                    if (
                        lk.from_node.name == from_name
                        and lk.to_node.name == to_name
                        and lk.from_socket.name == from_sock
                        and lk.to_socket.name == to_sock
                    ):
                        target_link = lk
                        break
                if target_link is not None:
                    tree.links.remove(target_link)
                    removed_links.append({"from": from_str, "to": to_str})
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Interface sockets (Group Input / Group Output exposed parameters).
    # Only meaningful for trees that have a tree.interface (geo nodes,
    # node groups). For materials/world/compositor this is skipped.
    # ------------------------------------------------------------------
    iface_def = graph.get("interface") or []
    iface_results: list[dict] = []
    if iface_def and hasattr(tree, "interface"):
        if clear:
            # Remove existing interface items so the spec is authoritative
            for item in list(tree.interface.items_tree):
                try:
                    tree.interface.remove(item)
                except Exception:
                    pass
        for isk in iface_def:
            try:
                name = isk["name"]
                in_out = isk.get("in_out", "INPUT").upper()
                stype = isk.get("socket_type", "NodeSocketFloat")
                sock = tree.interface.new_socket(
                    name=name, in_out=in_out, socket_type=stype,
                )
                if "default" in isk and hasattr(sock, "default_value"):
                    try:
                        sock.default_value = isk["default"]
                    except Exception:
                        pass
                if "min" in isk and hasattr(sock, "min_value"):
                    try:
                        sock.min_value = isk["min"]
                    except Exception:
                        pass
                if "max" in isk and hasattr(sock, "max_value"):
                    try:
                        sock.max_value = isk["max"]
                    except Exception:
                        pass
                if "description" in isk and hasattr(sock, "description"):
                    sock.description = isk["description"]
                iface_results.append({"ok": True, "name": name, "in_out": in_out})
            except Exception as e:
                iface_results.append({"ok": False, "name": isk.get("name"),
                                       "error": str(e)})
        # Refresh node_map for any auto-updated Group I/O nodes
        for n in tree.nodes:
            node_map.setdefault(n.name, n)
            if n.label:
                node_map.setdefault(n.label, n)

    created: list[str] = []
    skipped_props: list[dict] = []
    warnings: list[dict] = []

    for i, ndef in enumerate(nodes_def):
        ntype = ndef.get("type")
        nid = ndef.get("name") or ndef.get("id") or f"node_{i}"
        if not ntype:
            raise ValueError(f"node[{i}]: 'type' is required")

        # Deprecation check (e.g. ShaderNodeTexMusgrave -> ShaderNodeTexNoise in 4.1+)
        dep = _check_deprecated(ntype)
        if dep:
            warnings.append({
                "node": nid,
                "kind": "deprecated_type",
                "requested": ntype,
                "replacement": dep["replacement"],
                "note": dep["note"],
            })
            ntype = dep["replacement"]

        try:
            node = tree.nodes.new(ntype)
        except RuntimeError as e:
            raise ValueError(f"Unknown node type '{ntype}': {e}")

        # Rename to graph-local id (Blender may add .001 suffix on collision)
        node.name = nid
        if ndef.get("label"):
            node.label = ndef["label"]
        if "location" in ndef:
            loc = ndef["location"]
            node.location = (float(loc[0]), float(loc[1]))
        else:
            node.location = (i * 250, 0)

        # Set socket defaults
        for sk_key, sk_val in (ndef.get("inputs") or {}).items():
            try:
                socket = _find_socket(node.inputs, sk_key)
                if socket.is_linked:
                    continue
                socket.default_value = _coerce_socket_value(socket, sk_val)
            except Exception as e:
                skipped_props.append({
                    "node": nid, "kind": "input", "name": str(sk_key), "reason": str(e),
                })

        # Set non-socket node properties (image, space, uv_map, color_space, ...)
        for pk, pv in (ndef.get("properties") or {}).items():
            ok, reason = _set_node_property(node, pk, pv)
            if not ok:
                skipped_props.append({
                    "node": nid, "kind": "property", "name": pk, "reason": reason,
                })

        # Color ramp configuration (ShaderNodeValToRGB and similar)
        if "color_ramp" in ndef:
            ok, reason = _configure_color_ramp(node, ndef["color_ramp"])
            if not ok:
                skipped_props.append({
                    "node": nid, "kind": "color_ramp", "name": "color_ramp", "reason": reason,
                })

        # Curve mapping (ShaderNodeRGBCurve, ShaderNodeFloatCurve, CompositorNodeCurveRGB, ...)
        if "curves" in ndef or "curve_mapping" in ndef:
            spec = ndef.get("curve_mapping") or {"curves": ndef.get("curves")}
            ok, reason = _configure_curves(node, spec)
            if not ok:
                skipped_props.append({
                    "node": nid, "kind": "curves", "name": "mapping", "reason": reason,
                })

        node_map[nid] = node
        node_map[node.name] = node
        created.append(node.name)

    # Links
    link_results: list[dict] = []
    for li, link in enumerate(links_def):
        try:
            from_str = link.get("from")
            to_str = link.get("to")
            if not from_str or not to_str:
                raise ValueError(f"link[{li}]: 'from' and 'to' are required")
            from_name, from_sock = from_str.split(".", 1)
            to_name, to_sock = to_str.split(".", 1)
            from_node = node_map.get(from_name)
            to_node = node_map.get(to_name)
            if from_node is None:
                raise ValueError(f"from node '{from_name}' not found (have: {list(node_map.keys())[:10]}...)")
            if to_node is None:
                raise ValueError(f"to node '{to_name}' not found")
            from_s = _find_socket(from_node.outputs, from_sock)
            to_s = _find_socket(to_node.inputs, to_sock)
            tree.links.new(from_s, to_s)
            link_results.append({"ok": True, "from": from_str, "to": to_str})
        except Exception as e:
            link_results.append({"ok": False, "error": str(e), "link": link})

    return {
        "target": target,
        "tree": tree.name,
        "node_count": len(tree.nodes),
        "link_count": len(tree.links),
        "created": created,
        "removed_nodes": removed_nodes,
        "removed_links": removed_links,
        "skipped_properties": skipped_props,
        "links": link_results,
        "interface": iface_results,
        "warnings": warnings,
    }


register_capability("build_nodes", build_nodes)


# ---------------------------------------------------------------------------
# assign_material — small helper since material assignment isn't a node op
# ---------------------------------------------------------------------------


def assign_material(args: dict) -> dict:
    """Assign a material to an object slot.

    Args:
        args: {"object": str, "material": str, "slot": int (default 0)}
    """
    obj_name = args.get("object")
    mat_name = args.get("material")
    slot = int(args.get("slot", 0))
    if not obj_name or not mat_name:
        raise ValueError("'object' and 'material' are required")
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        raise ValueError(f"Object not found: {obj_name}")
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        raise ValueError(f"Material not found: {mat_name}")

    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:assign_material:{cmd_id}")

    while len(obj.material_slots) <= slot:
        obj.data.materials.append(None)
    obj.material_slots[slot].material = mat
    return {"object": obj.name, "material": mat.name, "slot": slot}


register_capability("assign_material", assign_material)
