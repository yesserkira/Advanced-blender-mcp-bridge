"""Geometry Nodes declarative DSL capability."""

import bpy

from . import register_capability


def build_geonodes(args: dict) -> dict:
    """Build a Geometry Nodes modifier from a declarative graph description.

    Args:
        args: {
            "object_name": str - target mesh object
            "modifier_name": str - modifier display name (default "AI_GeoNodes")
            "group_name": str - node group name (default same as modifier_name)
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
            "group_inputs": [{"name": str, "type": str}] - optional
            "group_outputs": [{"name": str, "type": str}] - optional
        }
    """
    object_name = args.get("object_name")
    modifier_name = args.get("modifier_name", "AI_GeoNodes")
    group_name = args.get("group_name", modifier_name)
    nodes_def = args.get("nodes", [])
    links_def = args.get("links", [])
    group_inputs = args.get("group_inputs", [])
    group_outputs = args.get("group_outputs", [])

    # Validate object
    if not object_name:
        raise ValueError("object_name is required")
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object not found: {object_name}")
    if obj.type != "MESH":
        raise ValueError(
            f"Object '{object_name}' is not a mesh (type={obj.type})"
        )

    # Push undo checkpoint
    cmd_id = args.get("_cmd_id", "unknown")
    bpy.ops.ed.undo_push(message=f"AI:geonodes.build:{cmd_id}")

    # Create node group
    group = bpy.data.node_groups.new(group_name, "GeometryNodeTree")

    # Add group interface sockets
    for sock in group_inputs:
        group.interface.new_socket(
            name=sock["name"],
            in_out="INPUT",
            socket_type=sock["type"],
        )
    for sock in group_outputs:
        group.interface.new_socket(
            name=sock["name"],
            in_out="OUTPUT",
            socket_type=sock["type"],
        )

    # Add GroupInput and GroupOutput nodes
    group_input_node = group.nodes.new("NodeGroupInput")
    group_input_node.location = (-300, 0)
    group_output_node = group.nodes.new("NodeGroupOutput")
    group_output_node.location = (300, 0)

    # Build node lookup by id (include special ids)
    node_map: dict[str, bpy.types.Node] = {
        "group_input": group_input_node,
        "group_output": group_output_node,
    }

    # Create user-defined nodes
    for i, node_def in enumerate(nodes_def):
        node_id = node_def["id"]
        node_type = node_def["type"]

        try:
            node = group.nodes.new(node_type)
        except RuntimeError:
            raise ValueError(
                f"Unknown node type: '{node_type}'. "
                f"Check Blender docs for valid GeometryNode* type names."
            )

        # Label
        label = node_def.get("label")
        if label:
            node.label = label

        # Location: use provided or auto-layout
        location = node_def.get("location")
        if location:
            node.location = (location[0], location[1])
        else:
            node.location = (i * 250, 0)

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
        group.links.new(from_socket, to_socket)

    # Add modifier to object
    modifier = obj.modifiers.new(name=modifier_name, type="NODES")
    modifier.node_group = group

    return {
        "object": obj.name,
        "modifier": modifier_name,
        "node_count": len(group.nodes),
        "link_count": len(group.links),
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


register_capability("geonodes.build", build_geonodes)
