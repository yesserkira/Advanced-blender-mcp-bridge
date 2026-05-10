"""Geometry-Nodes deep tools.

Six ops registered:
- geonodes.create_modifier  (add NODES modifier; link or create group)
- geonodes.describe_group   (read interface inputs/outputs of a group)
- geonodes.set_input        (set a socket value on a modifier)
- geonodes.animate_input    (insert keyframes on a modifier socket)
- geonodes.create_group     (create a new group from a graph spec)
- geonodes.realize          (apply / realize the modifier; destructive)

All ops honour `args["__dry_run"]` via capabilities/_dryrun.

NOTE on the "modifier socket" identifier: Blender 4.x exposes geometry-node
group inputs on the modifier as ``modifier["Input_N"]`` (where N is the
socket's interface index) AND, since 4.0, also via the friendlier
``modifier[<name>]`` lookup. We accept name OR identifier (Input_N) OR int
index, and resolve through the group's ``interface.items_tree``.
"""

from __future__ import annotations

from typing import Any

import bpy

from . import register_capability
from . import _dryrun
from ._helpers import get_object


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_modifier(obj, name: str | None):
    """Return the named NODES modifier, or the first one if name is None."""
    nodes_mods = [m for m in obj.modifiers if m.type == "NODES"]
    if not nodes_mods:
        raise ValueError(f"Object '{obj.name}' has no Geometry Nodes modifier")
    if name is None:
        return nodes_mods[0]
    for m in nodes_mods:
        if m.name == name:
            return m
    raise ValueError(
        f"Geometry Nodes modifier '{name}' not found on '{obj.name}'. "
        f"Available: {[m.name for m in nodes_mods]}"
    )


def _resolve_input_id(group, key) -> tuple[str, Any]:
    """Resolve an input key (name | identifier | int index) to (identifier, item).

    Returns the modifier-key string (e.g. 'Input_2') and the interface item.
    """
    items = [it for it in group.interface.items_tree
             if it.item_type == "SOCKET" and it.in_out == "INPUT"]
    if isinstance(key, int):
        if not (0 <= key < len(items)):
            raise ValueError(f"Input index {key} out of range (0..{len(items) - 1})")
        item = items[key]
        return item.identifier, item
    # string: try identifier first, then name
    for it in items:
        if it.identifier == key or it.name == key:
            return it.identifier, it
    raise ValueError(
        f"Input '{key}' not found in group '{group.name}'. "
        f"Available: {[(it.name, it.identifier) for it in items]}"
    )


def _socket_summary(item) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": item.name,
        "identifier": item.identifier,
        "socket_type": item.socket_type,
        "in_out": item.in_out,
    }
    for attr in ("default_value", "min_value", "max_value", "description"):
        if hasattr(item, attr):
            try:
                v = getattr(item, attr)
                # Convert vectors / colors
                if hasattr(v, "__iter__") and not isinstance(v, str):
                    v = list(v)
                out[attr] = v
            except Exception:
                pass
    return out


# ---------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------


def create_modifier(args: dict) -> dict:
    """Add a Geometry Nodes modifier to an object.

    Args:
        object: object name (required).
        group:  existing node-group name to link; if None, a new empty group is
                created on the modifier (Blender's default behaviour).
        name:   modifier name (optional).

    Returns: {object, modifier, group, created_group: bool}
    """
    name = args.get("object")
    if not name:
        raise ValueError("'object' is required")
    obj = get_object(name)
    mod_name = args.get("name") or "GeometryNodes"
    group_name = args.get("group")

    if _dryrun.is_dry_run(args):
        return _dryrun.report(
            "geonodes.create_modifier",
            [_dryrun.would_modify(
                f"object:{name}",
                {"add_modifier": {"type": "NODES", "name": mod_name,
                                  "group": group_name}},
            )],
        )

    bpy.ops.ed.undo_push(message=f"AI:geonodes.create_modifier:{obj.name}")

    mod = obj.modifiers.new(name=mod_name, type="NODES")
    created_group = False
    if group_name:
        group = bpy.data.node_groups.get(group_name)
        if group is None:
            raise ValueError(f"Node group '{group_name}' not found")
        if group.bl_idname != "GeometryNodeTree":
            raise ValueError(
                f"Node group '{group_name}' is {group.bl_idname}, expected "
                "GeometryNodeTree"
            )
        mod.node_group = group
    else:
        # Blender auto-creates an empty group on first NODES modifier; if not,
        # create one explicitly so callers always have a group to populate.
        if mod.node_group is None:
            grp = bpy.data.node_groups.new(name=f"{obj.name}_GN", type="GeometryNodeTree")
            mod.node_group = grp
            created_group = True

    return {
        "object": obj.name,
        "modifier": mod.name,
        "group": mod.node_group.name if mod.node_group else None,
        "created_group": created_group,
    }


def describe_group(args: dict) -> dict:
    """Describe a Geometry Nodes group's interface.

    Args:
        name: group name (required).

    Returns: {name, inputs[...], outputs[...], node_count, link_count}
    """
    grp_name = args.get("name")
    if not grp_name:
        raise ValueError("'name' is required")
    grp = bpy.data.node_groups.get(grp_name)
    if grp is None:
        raise ValueError(f"Node group not found: {grp_name}")
    if grp.bl_idname != "GeometryNodeTree":
        raise ValueError(f"'{grp_name}' is {grp.bl_idname}, not a Geometry Nodes group")

    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for it in grp.interface.items_tree:
        if it.item_type != "SOCKET":
            continue
        if it.in_out == "INPUT":
            inputs.append(_socket_summary(it))
        elif it.in_out == "OUTPUT":
            outputs.append(_socket_summary(it))

    return {
        "name": grp.name,
        "inputs": inputs,
        "outputs": outputs,
        "node_count": len(grp.nodes),
        "link_count": len(grp.links),
    }


def set_input(args: dict) -> dict:
    """Set a socket value on a Geometry Nodes modifier.

    Args:
        object:    object name (required).
        modifier:  modifier name (default: first NODES modifier).
        input:     socket name | identifier | int index (required).
        value:     scalar / vector / object reference (datablock name).

    Returns: {object, modifier, input, identifier, value}
    """
    name = args.get("object")
    if not name:
        raise ValueError("'object' is required")
    obj = get_object(name)
    mod = _get_modifier(obj, args.get("modifier"))
    if mod.node_group is None:
        raise ValueError(f"Modifier '{mod.name}' has no node group")

    key = args.get("input")
    if key is None:
        raise ValueError("'input' is required")
    identifier, item = _resolve_input_id(mod.node_group, key)
    value = args.get("value")

    if _dryrun.is_dry_run(args):
        return _dryrun.report(
            "geonodes.set_input",
            [_dryrun.would_modify(
                f"object:{obj.name}.modifiers[\"{mod.name}\"]",
                {identifier: value},
            )],
        )

    bpy.ops.ed.undo_push(message=f"AI:geonodes.set_input:{obj.name}.{identifier}")

    # Object-reference socket types take a datablock; resolve by name.
    if item.socket_type in ("NodeSocketObject", "NodeSocketCollection",
                            "NodeSocketMaterial", "NodeSocketImage",
                            "NodeSocketTexture"):
        if isinstance(value, str):
            data_attr = {
                "NodeSocketObject": "objects",
                "NodeSocketCollection": "collections",
                "NodeSocketMaterial": "materials",
                "NodeSocketImage": "images",
                "NodeSocketTexture": "textures",
            }[item.socket_type]
            block = getattr(bpy.data, data_attr).get(value)
            if block is None:
                raise ValueError(f"{item.socket_type[10:]} '{value}' not found")
            mod[identifier] = block
        else:
            mod[identifier] = value
    else:
        mod[identifier] = value

    # Force depsgraph update so the change is visible.
    obj.update_tag()

    return {
        "object": obj.name,
        "modifier": mod.name,
        "input": item.name,
        "identifier": identifier,
        "value": value,
    }


def animate_input(args: dict) -> dict:
    """Insert keyframes on a modifier input across given frames.

    Args:
        object: object name (required).
        modifier: modifier name (default: first NODES modifier).
        input: socket name / identifier / index (required).
        keyframes: list of {"frame": int, "value": ...} (required, non-empty).

    Returns: {object, modifier, identifier, count}
    """
    name = args.get("object")
    if not name:
        raise ValueError("'object' is required")
    obj = get_object(name)
    mod = _get_modifier(obj, args.get("modifier"))
    if mod.node_group is None:
        raise ValueError(f"Modifier '{mod.name}' has no node group")
    keyframes = args.get("keyframes") or []
    if not keyframes:
        raise ValueError("'keyframes' must be a non-empty list")

    key = args.get("input")
    if key is None:
        raise ValueError("'input' is required")
    identifier, _item = _resolve_input_id(mod.node_group, key)

    if _dryrun.is_dry_run(args):
        return _dryrun.report(
            "geonodes.animate_input",
            [_dryrun.would_modify(
                f"object:{obj.name}.modifiers[\"{mod.name}\"]",
                {f"{identifier}@frame_{kf.get('frame')}": kf.get("value")},
            ) for kf in keyframes],
        )

    bpy.ops.ed.undo_push(
        message=f"AI:geonodes.animate_input:{obj.name}.{identifier}:n={len(keyframes)}"
    )

    inserted = 0
    data_path = f'modifiers["{mod.name}"]["{identifier}"]'
    for kf in keyframes:
        frame = int(kf["frame"])
        mod[identifier] = kf["value"]
        try:
            obj.keyframe_insert(data_path=data_path, frame=frame)
            inserted += 1
        except Exception as e:
            raise RuntimeError(f"keyframe_insert failed at frame {frame}: {e}")
    obj.update_tag()

    return {
        "object": obj.name,
        "modifier": mod.name,
        "identifier": identifier,
        "count": inserted,
    }


def create_group(args: dict) -> dict:
    """Create a new Geometry Nodes group with declared inputs/outputs.

    Args:
        name: group name (required).
        inputs:  list of {"name": str, "socket_type": str, "default_value": ?}.
        outputs: list of {"name": str, "socket_type": str}.

    The actual node graph is left empty; build it via the existing
    ``build_nodes`` tool with target="node_group:Name". This keeps node-graph
    construction in one place.

    Returns: {name, input_count, output_count, created: bool}
    """
    grp_name = args.get("name")
    if not grp_name:
        raise ValueError("'name' is required")
    inputs = args.get("inputs") or []
    outputs = args.get("outputs") or []

    if _dryrun.is_dry_run(args):
        return _dryrun.report(
            "geonodes.create_group",
            [_dryrun.would_modify(
                f"node_group:{grp_name}",
                {"create": True, "inputs": len(inputs), "outputs": len(outputs)},
            )],
        )

    existing = bpy.data.node_groups.get(grp_name)
    if existing is not None:
        if existing.bl_idname != "GeometryNodeTree":
            raise ValueError(
                f"'{grp_name}' exists but is {existing.bl_idname}, not a Geometry Nodes group"
            )
        return {
            "name": grp_name,
            "input_count": sum(1 for it in existing.interface.items_tree
                               if it.item_type == "SOCKET" and it.in_out == "INPUT"),
            "output_count": sum(1 for it in existing.interface.items_tree
                                if it.item_type == "SOCKET" and it.in_out == "OUTPUT"),
            "created": False,
        }

    bpy.ops.ed.undo_push(message=f"AI:geonodes.create_group:{grp_name}")
    grp = bpy.data.node_groups.new(name=grp_name, type="GeometryNodeTree")

    for spec in inputs:
        item = grp.interface.new_socket(
            name=spec["name"],
            in_out="INPUT",
            socket_type=spec.get("socket_type", "NodeSocketGeometry"),
        )
        if "default_value" in spec and hasattr(item, "default_value"):
            try:
                item.default_value = spec["default_value"]
            except Exception:
                pass
    for spec in outputs:
        grp.interface.new_socket(
            name=spec["name"],
            in_out="OUTPUT",
            socket_type=spec.get("socket_type", "NodeSocketGeometry"),
        )

    return {
        "name": grp.name,
        "input_count": len(inputs),
        "output_count": len(outputs),
        "created": True,
    }


def realize(args: dict) -> dict:
    """Apply (realize) a Geometry Nodes modifier — destructive.

    Args:
        object: object name (required).
        modifier: modifier name (default: first NODES modifier).

    Returns: {object, applied: str}
    """
    name = args.get("object")
    if not name:
        raise ValueError("'object' is required")
    obj = get_object(name)
    mod = _get_modifier(obj, args.get("modifier"))

    if _dryrun.is_dry_run(args):
        return _dryrun.report(
            "geonodes.realize",
            [_dryrun.would_modify(
                f"object:{obj.name}",
                {"apply_modifier": mod.name, "destructive": True},
            )],
        )

    bpy.ops.ed.undo_push(message=f"AI:geonodes.realize:{obj.name}.{mod.name}")

    # Make this the active object so modifier_apply works in any context.
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.modifier_apply(modifier=mod.name)
    except RuntimeError as e:
        raise RuntimeError(f"modifier_apply failed: {e}")

    return {"object": obj.name, "applied": mod.name}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_capability("geonodes.create_modifier", create_modifier)
register_capability("geonodes.describe_group", describe_group)
register_capability("geonodes.set_input", set_input)
register_capability("geonodes.animate_input", animate_input)
register_capability("geonodes.create_group", create_group)
register_capability("geonodes.realize", realize)
