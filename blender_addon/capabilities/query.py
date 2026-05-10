"""Granular scene/data introspection — replaces v1 scene.get monolith.

Tools registered:
- query: read any datablock (scene, object, material, ...) by RNA path
- list:  enumerate datablocks of a kind with optional filters
- describe_api: introspect any bpy.types.X RNA properties
- audit.read: tail the audit log
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import bpy

from . import register_capability


# ---------------------------------------------------------------------------
# JSON-safe serialization of arbitrary RNA values
# ---------------------------------------------------------------------------

_PRIMITIVE_TYPES = (bool, int, float, str, type(None))


def to_jsonable(value: Any, depth: int = 0, max_depth: int = 2) -> Any:
    """Convert any bpy/mathutils value to a JSON-serializable form."""
    if depth > max_depth:
        return f"<{type(value).__name__}>"

    if isinstance(value, _PRIMITIVE_TYPES):
        return value

    # mathutils Vector / Color / Euler / Quaternion / Matrix
    cls_name = type(value).__name__
    if cls_name in {"Vector", "Color", "Euler", "Quaternion"}:
        try:
            return list(value)
        except Exception:
            return repr(value)
    if cls_name == "Matrix":
        try:
            return [list(row) for row in value]
        except Exception:
            return repr(value)

    # bpy collection-like (CollectionProperty, IDPropertyGroup, etc.)
    if hasattr(value, "items") and hasattr(value, "keys"):
        try:
            return {str(k): to_jsonable(v, depth + 1, max_depth) for k, v in value.items()}
        except Exception:
            pass

    # Pointer to another ID datablock — return its name + type
    if hasattr(value, "bl_rna") and hasattr(value, "name"):
        return {"$ref": value.bl_rna.identifier, "name": value.name}

    # Sequence-like (bpy_prop_array, list, tuple)
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
        try:
            return [to_jsonable(v, depth + 1, max_depth) for v in value]
        except Exception:
            return repr(value)

    # Enum value (string)
    try:
        return str(value)
    except Exception:
        return repr(value)


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------

_DATA_KINDS = {
    "object": "objects",
    "objects": "objects",
    "material": "materials",
    "materials": "materials",
    "mesh": "meshes",
    "meshes": "meshes",
    "light": "lights",
    "lights": "lights",
    "camera": "cameras",
    "cameras": "cameras",
    "collection": "collections",
    "collections": "collections",
    "image": "images",
    "images": "images",
    "node_group": "node_groups",
    "node_groups": "node_groups",
    "action": "actions",
    "actions": "actions",
    "scene": "scenes",
    "scenes": "scenes",
    "world": "worlds",
    "worlds": "worlds",
    "texture": "textures",
    "textures": "textures",
    "armature": "armatures",
    "armatures": "armatures",
    "curve": "curves",
    "curves": "curves",
}


def _resolve_target(target: str):
    """Resolve a target string like 'object:Cube.modifiers[0]' to a Python object.

    Forms accepted:
        scene                            -> active scene
        scene:Scene                      -> bpy.data.scenes['Scene']
        object:Cube                      -> bpy.data.objects['Cube']
        object:Cube.modifiers            -> ...modifiers (collection)
        object:Cube.modifiers[0]         -> first modifier
        object:Cube.modifiers["Bevel"]   -> by name
        material:Gold.node_tree.nodes    -> nested attribute
        view_layer.active                -> bpy.context.view_layer attribute
        render                           -> bpy.context.scene.render
        world                            -> bpy.context.scene.world
    """
    if not target or not isinstance(target, str):
        raise ValueError("target must be a non-empty string")

    # Special root shortcuts
    if target == "scene":
        return bpy.context.scene
    if target.startswith("scene."):
        return _walk(bpy.context.scene, target[len("scene."):])
    if target == "render":
        return bpy.context.scene.render
    if target.startswith("render."):
        return _walk(bpy.context.scene.render, target[len("render."):])
    if target == "world":
        return bpy.context.scene.world
    if target.startswith("world."):
        return _walk(bpy.context.scene.world, target[len("world."):])
    if target.startswith("view_layer"):
        rest = target[len("view_layer"):].lstrip(".")
        return _walk(bpy.context.view_layer, rest) if rest else bpy.context.view_layer
    if target.startswith("context."):
        return _walk(bpy.context, target[len("context."):])

    # kind:Name[.attr...]
    if ":" in target:
        kind_part, rest = target.split(":", 1)
        kind = kind_part.strip()
        coll_name = _DATA_KINDS.get(kind)
        if coll_name is None:
            raise ValueError(
                f"Unknown target kind: '{kind}'. "
                f"Valid kinds: {sorted(set(_DATA_KINDS))}"
            )
        # Split name from attribute path. Name may be quoted "..." or end at first '.' / '['
        name, attr_path = _split_name_and_path(rest)
        coll = getattr(bpy.data, coll_name)
        item = coll.get(name)
        if item is None:
            raise ValueError(f"{kind} '{name}' not found")
        if attr_path:
            return _walk(item, attr_path)
        return item

    raise ValueError(
        f"Unrecognized target format: '{target}'. "
        f"Use 'kind:Name[.attr...]' or one of: scene, render, world, view_layer."
    )


def _split_name_and_path(rest: str) -> tuple[str, str]:
    """Parse 'Cube.modifiers[0]' -> ('Cube', 'modifiers[0]')."""
    # Find the first '.' or '[' that ends the name segment
    for i, ch in enumerate(rest):
        if ch in ".[":
            return rest[:i], rest[i:].lstrip(".")
    return rest, ""


def _walk(obj: Any, path: str) -> Any:
    """Walk an attribute path supporting .name, [int], ["name"]."""
    cur = obj
    i = 0
    n = len(path)
    while i < n:
        ch = path[i]
        if ch == ".":
            i += 1
            continue
        if ch == "[":
            end = path.index("]", i)
            key_raw = path[i + 1 : end].strip()
            if key_raw.startswith(("'", '"')):
                key = key_raw[1:-1]
                cur = cur[key]
            else:
                cur = cur[int(key_raw)]
            i = end + 1
            continue
        # attribute name
        j = i
        while j < n and path[j] not in ".[":
            j += 1
        attr = path[i:j]
        cur = getattr(cur, attr)
        i = j
    return cur


# ---------------------------------------------------------------------------
# Field projection
# ---------------------------------------------------------------------------


def _serialize_node_link(link: Any) -> dict:
    """Serialize a NodeLink as {from: 'node.socket', to: 'node.socket'}.

    This makes node-tree wiring inspectable without execute_python.
    """
    try:
        return {
            "$rna": "NodeLink",
            "from": f"{link.from_node.name}.{link.from_socket.name}",
            "to": f"{link.to_node.name}.{link.to_socket.name}",
            "from_socket_type": getattr(link.from_socket, "type", None),
            "to_socket_type": getattr(link.to_socket, "type", None),
            "is_valid": getattr(link, "is_valid", True),
            "is_muted": getattr(link, "is_muted", False),
        }
    except Exception as e:
        return {"$rna": "NodeLink", "$error": str(e)}


def _project_fields(item: Any, fields: list[str] | None) -> dict:
    """Project requested fields off an RNA-bearing object.

    If `fields` is None: enumerate all readable RNA properties (no recursion
    into pointers/collections beyond a $ref/length stub).
    """
    if fields:
        out = {}
        for f in fields:
            try:
                out[f] = to_jsonable(_walk(item, f))
            except Exception as e:
                out[f] = {"$error": str(e)}
        return out

    # NodeLink — expose from/to node + socket explicitly so users can inspect
    # the wiring of a node graph without reaching for execute_python.
    if type(item).__name__ == "NodeLink":
        return _serialize_node_link(item)

    # Items: bpy collection (modifiers, nodes, links, ...)
    if hasattr(item, "__iter__") and not hasattr(item, "bl_rna"):
        try:
            return [_project_fields(x, None) for x in item]  # type: ignore[return-value]
        except Exception:
            return {"$repr": repr(item)}

    # bpy_prop_collection (also iterable but has bl_rna sometimes)
    if type(item).__name__ == "bpy_prop_collection":
        return [_project_fields(x, None) for x in item]  # type: ignore[return-value]

    rna = getattr(item, "bl_rna", None)
    if rna is None:
        return {"$value": to_jsonable(item)}

    out: dict = {}
    out["$rna"] = rna.identifier

    for prop in rna.properties:
        name = prop.identifier
        if name in {"rna_type", "bl_rna"}:
            continue
        try:
            value = getattr(item, name)
        except Exception:
            continue

        if prop.type == "COLLECTION":
            try:
                out[name] = {"$collection": True, "length": len(value)}
            except Exception:
                out[name] = {"$collection": True}
        elif prop.type == "POINTER":
            if value is None:
                out[name] = None
            else:
                out[name] = {
                    "$ref": value.bl_rna.identifier if hasattr(value, "bl_rna") else "?",
                    "name": getattr(value, "name", None),
                }
        else:
            out[name] = to_jsonable(value, depth=0, max_depth=2)
    return out


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


def query(args: dict) -> dict | list:
    """Granular read of any RNA datablock.

    Args:
        args: {"target": str, "fields": list[str] | None}
    """
    target = args.get("target")
    fields = args.get("fields")
    item = _resolve_target(target)
    return _project_fields(item, fields)


register_capability("query", query)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def _list_collection(coll, filt: dict | None) -> list[dict]:
    out = []
    for it in coll:
        info = {"name": it.name}
        if hasattr(it, "type"):
            info["type"] = it.type
        out.append(info)
    if not filt:
        return out
    name_contains = filt.get("name_contains")
    name_prefix = filt.get("name_prefix")
    type_eq = filt.get("type")
    in_collection = filt.get("in_collection")
    if in_collection:
        coll_obj = bpy.data.collections.get(in_collection)
        coll_names = {o.name for o in coll_obj.objects} if coll_obj else set()
    else:
        coll_names = None
    result = []
    for info in out:
        if type_eq and info.get("type") != type_eq:
            continue
        if name_contains and name_contains not in info["name"]:
            continue
        if name_prefix and not info["name"].startswith(name_prefix):
            continue
        if coll_names is not None and info["name"] not in coll_names:
            continue
        result.append(info)
    return result


def list_(args: dict) -> list[dict]:
    """Enumerate datablocks of a kind.

    Args:
        args: {"kind": str, "filter": dict | None}
    """
    kind = args.get("kind")
    coll_name = _DATA_KINDS.get(kind)
    if coll_name is None:
        raise ValueError(
            f"Unknown kind: '{kind}'. Valid: {sorted(set(_DATA_KINDS))}"
        )
    coll = getattr(bpy.data, coll_name)
    return _list_collection(coll, args.get("filter"))


register_capability("list", list_)


# ---------------------------------------------------------------------------
# describe_api
# ---------------------------------------------------------------------------


def describe_api(args: dict) -> dict:
    """Introspect any bpy.types.X via bl_rna.

    Args:
        args: {"rna_path": str}  e.g. "SubsurfModifier", "ShaderNodeBsdfPrincipled"
    """
    rna_path = args.get("rna_path")
    if not rna_path:
        raise ValueError("rna_path is required")

    cls = getattr(bpy.types, rna_path, None)
    if cls is None:
        raise ValueError(f"bpy.types.{rna_path} does not exist")

    rna = cls.bl_rna
    props = []
    for prop in rna.properties:
        if prop.identifier in {"rna_type", "bl_rna"}:
            continue
        info: dict = {
            "name": prop.identifier,
            "type": prop.type,
            "description": prop.description,
        }
        if prop.type == "ENUM":
            info["items"] = [(i.identifier, i.name, i.description) for i in prop.enum_items]
        if prop.type in {"INT", "FLOAT"}:
            info["soft_min"] = getattr(prop, "soft_min", None)
            info["soft_max"] = getattr(prop, "soft_max", None)
            info["default"] = getattr(prop, "default", None)
        if prop.type == "STRING":
            info["default"] = getattr(prop, "default", "")
        if prop.type == "BOOLEAN":
            info["default"] = getattr(prop, "default", False)
        if prop.type == "POINTER":
            info["fixed_type"] = getattr(prop.fixed_type, "identifier", None)
        if prop.type == "COLLECTION":
            info["fixed_type"] = getattr(prop.fixed_type, "identifier", None)
        info["readonly"] = prop.is_readonly
        props.append(info)

    # Functions/operators on the class
    funcs = []
    for fn in rna.functions:
        funcs.append({
            "name": fn.identifier,
            "description": fn.description,
            "parameters": [p.identifier for p in fn.parameters if p.identifier != "rna_type"],
        })

    return {
        "rna": rna.identifier,
        "description": rna.description,
        "properties": props,
        "functions": funcs,
    }


register_capability("describe_api", describe_api)


# ---------------------------------------------------------------------------
# audit.read
# ---------------------------------------------------------------------------


def audit_read(args: dict) -> dict:
    """Tail the audit log JSONL file.

    Args:
        args: {"limit": int (default 50, max 500), "since_ts": str | None (ISO)}
    """
    limit = int(args.get("limit", 50))
    if limit < 1 or limit > 500:
        raise ValueError("limit must be 1..500")
    since_ts = args.get("since_ts")

    base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    log_dir = os.path.join(base, "BlenderMCP")
    if not os.path.isdir(log_dir):
        return {"entries": [], "log_dir": log_dir}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(log_dir, f"audit-{today}.log")
    if not os.path.isfile(path):
        return {"entries": [], "log_dir": log_dir}

    entries: list[dict] = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if since_ts and e.get("ts", "") <= since_ts:
                continue
            entries.append(e)

    return {"entries": entries[-limit:], "log_dir": log_dir, "file": path}


register_capability("audit.read", audit_read)
