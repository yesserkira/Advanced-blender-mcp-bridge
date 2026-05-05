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
        if not world.use_nodes:
            world.use_nodes = True
        return world, world.node_tree

    if target == "scene.compositor":
        scene = bpy.context.scene
        if not scene.use_nodes:
            scene.use_nodes = True
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
    """Find a socket by name (case-insensitive) or index."""
    if isinstance(key, int):
        return sockets[key]
    for s in sockets:
        if s.name == key:
            return s
    for s in sockets:
        if s.name.lower() == str(key).lower():
            return s
    available = [s.name for s in sockets]
    raise ValueError(f"Socket '{key}' not found. Available: {available}")


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
        is_group = tree.bl_rna.identifier in {
            "GeometryNodeTree", "ShaderNodeTree", "CompositorNodeTree", "TextureNodeTree"
        } and not (host and host.bl_rna.identifier in {"Material", "World", "Scene"})
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
        for ii, isk in enumerate(iface_def):
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

    for i, ndef in enumerate(nodes_def):
        ntype = ndef.get("type")
        nid = ndef.get("name") or ndef.get("id") or f"node_{i}"
        if not ntype:
            raise ValueError(f"node[{i}]: 'type' is required")

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
        "skipped_properties": skipped_props,
        "links": link_results,
        "interface": iface_results,
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
