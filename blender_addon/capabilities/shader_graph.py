"""Shader-graph declarative DSL capability."""

import bpy

from . import register_capability


def set_material_node_graph(args: dict) -> dict:
    """Build a complete shader node graph on a material from a declarative description.

    Args:
        args: {
            "material_name": str - material name (create if missing)
            "create_if_missing": bool - default True
            "clear_existing": bool - default True
            "nodes": [{
                "id": str,
                "type": str,
                "label": str|None,
                "location": [x, y]|None,
                "inputs": {socket_name: value}
            }]
            "links": [{
                "from_node": str, "from_socket": str,
                "to_node": str, "to_socket": str
            }]
            "output_node": str|None - id of node to auto-connect to Surface
        }
    """
    material_name = args.get("material_name")
    create_if_missing = args.get("create_if_missing", True)
    clear_existing = args.get("clear_existing", True)
    nodes_def = args.get("nodes", [])
    links_def = args.get("links", [])
    output_node_id = args.get("output_node")

    if not material_name:
        raise ValueError("material_name is required")

    # Find or create material
    mat = bpy.data.materials.get(material_name)
    if mat is None:
        if not create_if_missing:
            raise ValueError(
                f"Material not found: {material_name} "
                f"(create_if_missing=False)"
            )
        mat = bpy.data.materials.new(name=material_name)

    # Push undo checkpoint
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:shader.set_graph:{cmd_id}")

    mat.use_nodes = True
    tree = mat.node_tree

    # Clear existing nodes if requested
    if clear_existing:
        tree.nodes.clear()

    # Ensure a Material Output node exists
    mat_output = None
    for node in tree.nodes:
        if node.type == "OUTPUT_MATERIAL":
            mat_output = node
            break
    if mat_output is None:
        mat_output = tree.nodes.new("ShaderNodeOutputMaterial")
        mat_output.location = (300, 0)

    # Build node lookup (include special id)
    node_map: dict[str, bpy.types.Node] = {
        "material_output": mat_output,
    }

    nodes_created = []

    # Create user-defined nodes
    for i, node_def in enumerate(nodes_def):
        node_id = node_def["id"]
        node_type = node_def["type"]

        try:
            node = tree.nodes.new(node_type)
        except RuntimeError:
            raise ValueError(
                f"Unknown shader node type: '{node_type}'. "
                f"Check Blender docs for valid ShaderNode* type names."
            )

        nodes_created.append(node_type)

        # Label
        label = node_def.get("label")
        if label:
            node.label = label

        # Location: use provided or auto-layout
        location = node_def.get("location")
        if location:
            node.location = (location[0], location[1])
        else:
            node.location = (i * 250 - 300, 0)

        # Set input defaults
        inputs = node_def.get("inputs", {})
        for socket_name, value in inputs.items():
            socket = _find_socket(node.inputs, socket_name)
            if isinstance(value, list):
                socket.default_value = type(socket.default_value)(value)
            else:
                socket.default_value = value

        node_map[node_id] = node

    # Create links
    for link_def in links_def:
        from_id = link_def["from_node"]
        from_socket_name = link_def["from_socket"]
        to_id = link_def["to_node"]
        to_socket_name = link_def["to_socket"]

        from_node = node_map.get(from_id)
        if from_node is None:
            raise ValueError(
                f"Link from_node '{from_id}' not found. "
                f"Available node ids: {', '.join(node_map.keys())}"
            )

        to_node = node_map.get(to_id)
        if to_node is None:
            raise ValueError(
                f"Link to_node '{to_id}' not found. "
                f"Available node ids: {', '.join(node_map.keys())}"
            )

        from_socket = _find_socket(from_node.outputs, from_socket_name)
        to_socket = _find_socket(to_node.inputs, to_socket_name)
        tree.links.new(from_socket, to_socket)

    # Auto-connect output_node to Material Output Surface
    if output_node_id:
        src_node = node_map.get(output_node_id)
        if src_node is None:
            raise ValueError(
                f"output_node '{output_node_id}' not found. "
                f"Available node ids: {', '.join(node_map.keys())}"
            )
        # Find first shader/BSDF output socket
        src_socket = None
        for out in src_node.outputs:
            if out.type == "SHADER":
                src_socket = out
                break
        if src_socket is None and len(src_node.outputs) > 0:
            src_socket = src_node.outputs[0]
        if src_socket is not None:
            surface_input = _find_socket(mat_output.inputs, "Surface")
            tree.links.new(src_socket, surface_input)

    return {
        "material": mat.name,
        "node_count": len(tree.nodes),
        "link_count": len(tree.links),
        "nodes_created": nodes_created,
    }


def _find_socket(sockets, name: str):
    """Find a socket by name, raising ValueError with available names if not found."""
    for s in sockets:
        if s.name == name:
            return s
    available = [s.name for s in sockets]
    raise ValueError(
        f"Socket '{name}' not found. Available: {', '.join(available)}"
    )


register_capability("shader.set_graph", set_material_node_graph)
