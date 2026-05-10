"""Geometry Nodes preset library.

Presets are JSON files under blender_addon/presets/geonodes/*.json. They
describe a group's interface AND a graph (nodes + links). Three tools:

- geonodes.list_presets  — index of bundled presets (read-only).
- geonodes.get_preset    — full JSON of a named preset (read-only).
- geonodes.apply_preset  — instantiate the group in bpy.data.node_groups
                           and optionally attach it as a NODES modifier on
                           a target object. Honours dry-run.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import bpy

from . import register_capability
from . import _dryrun


def _presets_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "presets" / "geonodes"


def list_presets(args: dict) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    pdir = _presets_dir()
    if not pdir.is_dir():
        return {"presets": [], "count": 0, "dir": str(pdir)}
    for path in sorted(pdir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            out.append({"name": path.stem, "error": str(e)})
            continue
        out.append({
            "name": data.get("name", path.stem),
            "title": data.get("title"),
            "description": data.get("description"),
            "input_count": len((data.get("group") or {}).get("inputs", [])),
            "output_count": len((data.get("group") or {}).get("outputs", [])),
            "node_count": len((data.get("graph") or {}).get("nodes", [])),
            "link_count": len((data.get("graph") or {}).get("links", [])),
        })
    return {"presets": out, "count": len(out), "dir": str(pdir)}


def get_preset(args: dict) -> dict[str, Any]:
    name = args.get("name")
    if not name:
        raise ValueError("'name' is required")
    # Reject path-traversal: only basename, no separators.
    if os.sep in name or "/" in name or ".." in name:
        raise ValueError("preset name must be a bare filename, not a path")
    path = _presets_dir() / f"{name}.json"
    if not path.is_file():
        raise ValueError(f"Preset '{name}' not found at {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to parse preset '{name}': {e}")


register_capability("geonodes.list_presets", list_presets)
register_capability("geonodes.get_preset", get_preset)


# ---------------------------------------------------------------------------
# apply_preset — instantiate a preset graph as a real node group (v2.3)
# ---------------------------------------------------------------------------


_INTERFACE_VALUE_ATTRS = (
    "default_value", "min_value", "max_value", "description",
)


def _load_preset(name: str) -> dict[str, Any]:
    if not name:
        raise ValueError("'preset' is required")
    if os.sep in name or "/" in name or ".." in name:
        raise ValueError("preset name must be a bare filename, not a path")
    path = _presets_dir() / f"{name}.json"
    if not path.is_file():
        raise ValueError(f"Preset '{name}' not found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _build_interface(group, sockets: list[dict], in_out: str) -> None:
    for sock in sockets:
        sname = sock.get("name")
        stype = sock.get("socket_type")
        if not sname or not stype:
            raise ValueError(f"interface socket missing name/socket_type: {sock}")
        item = group.interface.new_socket(
            name=sname, in_out=in_out, socket_type=stype,
        )
        for attr in _INTERFACE_VALUE_ATTRS:
            if attr in sock and hasattr(item, attr):
                try:
                    setattr(item, attr, sock[attr])
                except Exception:
                    # Some socket types (Geometry, Object, ...) reject
                    # default_value — that's fine, skip silently.
                    pass


def _resolve_socket(node, sock_key: str, *, side: str):
    """Return the bpy socket on ``node`` named ``sock_key``.

    Resolves NodeGroupInput/Output proxy sockets against the actual interface
    item names (which is how presets reference them, e.g. ``in.Geometry``).
    """
    coll = node.outputs if side == "out" else node.inputs
    # Direct name match
    sock = coll.get(sock_key)
    if sock is not None:
        return sock
    # Fall back to identifier match (Blender 4.x exposes both)
    for s in coll:
        if getattr(s, "identifier", None) == sock_key:
            return s
    raise ValueError(
        f"Socket '{sock_key}' not found on node '{node.name}' ({side}). "
        f"Available: {[s.name for s in coll]}"
    )


def _build_graph(group, graph: dict) -> tuple[int, int]:
    nodes_spec = graph.get("nodes") or []
    links_spec = graph.get("links") or []

    name_to_node: dict[str, Any] = {}
    for nspec in nodes_spec:
        nname = nspec.get("name")
        ntype = nspec.get("type")
        if not nname or not ntype:
            raise ValueError(f"node spec missing name/type: {nspec}")
        node = group.nodes.new(type=ntype)
        node.name = nname
        node.label = nspec.get("label", "")
        # Apply scalar properties (e.g. data_type, transform_space).
        for k, v in (nspec.get("properties") or {}).items():
            try:
                setattr(node, k, v)
            except Exception:
                # Unknown / read-only properties are non-fatal.
                pass
        if "location" in nspec and hasattr(node, "location"):
            try:
                node.location = nspec["location"]
            except Exception:
                pass
        name_to_node[nname] = node

    link_count = 0
    for lspec in links_spec:
        src = lspec.get("from")
        dst = lspec.get("to")
        if not src or not dst or "." not in src or "." not in dst:
            raise ValueError(f"link must be 'node.socket' -> 'node.socket': {lspec}")
        src_node_name, src_sock = src.split(".", 1)
        dst_node_name, dst_sock = dst.split(".", 1)
        src_node = name_to_node.get(src_node_name)
        dst_node = name_to_node.get(dst_node_name)
        if src_node is None or dst_node is None:
            raise ValueError(
                f"link references unknown node: {lspec}; known: {list(name_to_node)}"
            )
        out_sock = _resolve_socket(src_node, src_sock, side="out")
        in_sock = _resolve_socket(dst_node, dst_sock, side="in")
        group.links.new(out_sock, in_sock)
        link_count += 1

    return len(nodes_spec), link_count


def apply_preset(args: dict) -> dict[str, Any]:
    """Instantiate a Geometry-Nodes preset.

    Args:
        preset:    preset name (required, e.g. "scatter-on-surface").
        group:     name to give the created node group (default: preset's
                   built-in group name, suffixed with .NNN if it already
                   exists in bpy.data.node_groups).
        object:    if provided, attach the new group as a NODES modifier on
                   this object.
        modifier:  modifier name to use (default: "GeometryNodes").
        replace:   if True and a group with the target name already exists,
                   delete it first. Default False.
    """
    preset_name = args.get("preset")
    data = _load_preset(preset_name)
    group_spec = data.get("group") or {}
    graph_spec = data.get("graph") or {}

    target_group_name = args.get("group") or group_spec.get("name") or preset_name
    target_object = args.get("object")
    modifier_name = args.get("modifier") or "GeometryNodes"
    replace = bool(args.get("replace"))

    if _dryrun.is_dry_run(args):
        would: list[dict] = [{
            "op": "create_node_group",
            "name": target_group_name,
            "input_count": len(group_spec.get("inputs") or []),
            "output_count": len(group_spec.get("outputs") or []),
            "node_count": len(graph_spec.get("nodes") or []),
            "link_count": len(graph_spec.get("links") or []),
        }]
        if target_object:
            would.append(_dryrun.would_modify(
                f"object:{target_object}",
                {"add_modifier": {"type": "NODES", "name": modifier_name,
                                  "group": target_group_name}},
            ))
        return _dryrun.report("geonodes.apply_preset", would)

    if target_object and bpy.data.objects.get(target_object) is None:
        raise ValueError(f"Object not found: {target_object}")

    bpy.ops.ed.undo_push(message=f"AI:geonodes.apply_preset:{preset_name}")

    # Group creation (with optional replace).
    existing = bpy.data.node_groups.get(target_group_name)
    if existing is not None:
        if existing.bl_idname != "GeometryNodeTree":
            raise ValueError(
                f"Group '{target_group_name}' exists and is "
                f"{existing.bl_idname}, not GeometryNodeTree"
            )
        if replace:
            bpy.data.node_groups.remove(existing)
        # else: Blender will auto-suffix (.001) on .new()

    group = bpy.data.node_groups.new(name=target_group_name, type="GeometryNodeTree")

    _build_interface(group, group_spec.get("inputs") or [], "INPUT")
    _build_interface(group, group_spec.get("outputs") or [], "OUTPUT")
    n_nodes, n_links = _build_graph(group, graph_spec)

    out: dict[str, Any] = {
        "preset": preset_name,
        "group": group.name,
        "node_count": n_nodes,
        "link_count": n_links,
    }

    if target_object:
        obj = bpy.data.objects[target_object]
        mod = obj.modifiers.new(name=modifier_name, type="NODES")
        mod.node_group = group
        out["object"] = obj.name
        out["modifier"] = mod.name

    return out


register_capability("geonodes.apply_preset", apply_preset)
