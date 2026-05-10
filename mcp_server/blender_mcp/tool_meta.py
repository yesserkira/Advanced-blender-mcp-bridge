"""Single source of truth for MCP tool annotations.

Annotations are MCP-spec hints (`readOnlyHint`, `destructiveHint`,
`idempotentHint`, `openWorldHint`) that let clients (Copilot Chat, etc.) skip
or auto-approve safe tool calls. They are *hints*, not security boundaries —
real enforcement still lives in policy.py and the approval flow.

Adding a tool? Add a row to TOOL_META below. The test
test_tool_meta_covers_all_tools enforces that every @mcp.tool() in server.py
has an entry here.
"""

from __future__ import annotations

from typing import TypedDict


class ToolMeta(TypedDict, total=False):
    title: str
    readOnlyHint: bool
    destructiveHint: bool
    idempotentHint: bool
    openWorldHint: bool


# readOnlyHint=True       -> tool does not modify the scene.
# destructiveHint=True    -> tool may delete/overwrite (data loss possible).
# idempotentHint=True     -> calling twice with same args == calling once.
# openWorldHint=True      -> reaches the filesystem / network / external state.
TOOL_META: dict[str, ToolMeta] = {
    # --- Connectivity & introspection (all read-only) -----------------------
    "ping": {"title": "Ping Blender", "readOnlyHint": True, "idempotentHint": True},
    "query": {"title": "Query datablock", "readOnlyHint": True, "idempotentHint": True},
    "list": {"title": "List datablocks", "readOnlyHint": True, "idempotentHint": True},
    "describe_api": {"title": "Describe RNA type", "readOnlyHint": True, "idempotentHint": True},
    "get_audit_log": {"title": "Read audit log", "readOnlyHint": True},
    "perf_stats": {"title": "Read perf ring stats", "readOnlyHint": True, "idempotentHint": True},
    "get_property": {"title": "Read RNA property", "readOnlyHint": True, "idempotentHint": True},
    "scene_diff": {"title": "Diff scene snapshots", "readOnlyHint": True},
    "list_assets": {"title": "List assets in .blend", "readOnlyHint": True, "openWorldHint": True},
    "list_checkpoints": {"title": "List checkpoints", "readOnlyHint": True, "openWorldHint": True},
    "viewport_screenshot": {"title": "Capture viewport", "readOnlyHint": True},
    "render_region": {"title": "Render region", "readOnlyHint": True, "openWorldHint": True},
    "bake_preview": {"title": "Bake preview", "readOnlyHint": True, "openWorldHint": True},

    # --- Mutating / non-destructive (idempotent in many cases) -------------
    "add_modifier": {"title": "Add modifier"},
    "remove_modifier": {"title": "Remove modifier", "destructiveHint": True},
    "build_nodes": {"title": "Build node graph"},
    "assign_material": {"title": "Assign material"},
    "set_property": {"title": "Set RNA property", "idempotentHint": True},
    "call_operator": {"title": "Call bpy operator"},
    "create_primitive": {"title": "Create primitive"},
    "set_transform": {"title": "Set transform", "idempotentHint": True},
    "create_objects": {"title": "Create many objects"},
    "transaction": {"title": "Run atomic transaction"},
    "apply_to_selection": {"title": "Apply tool to selection"},
    "set_keyframe": {"title": "Insert keyframe"},
    "import_asset": {"title": "Import asset", "openWorldHint": True},
    "link_blend": {"title": "Link from .blend", "openWorldHint": True},

    # --- Destructive --------------------------------------------------------
    "delete_object": {"title": "Delete object", "destructiveHint": True},
    "execute_python": {
        "title": "Run Python in Blender",
        "destructiveHint": True,
        "openWorldHint": True,
    },

    # --- Checkpoints (mutating but explicitly safety-net oriented) ---------
    "create_checkpoint": {"title": "Create checkpoint", "openWorldHint": True},
    "restore_checkpoint": {
        "title": "Restore checkpoint",
        "destructiveHint": True,
        "openWorldHint": True,
    },

    # --- Geometry Nodes (v2.2) ---------------------------------------------
    "geonodes_describe_group": {
        "title": "Describe Geometry Nodes group",
        "readOnlyHint": True,
        "idempotentHint": True,
    },
    "geonodes_create_modifier": {"title": "Add Geometry Nodes modifier"},
    "geonodes_create_group": {"title": "Create Geometry Nodes group"},
    "geonodes_set_input": {"title": "Set GN modifier input", "idempotentHint": True},
    "geonodes_animate_input": {"title": "Animate GN modifier input"},
    "geonodes_realize": {
        "title": "Realize Geometry Nodes modifier",
        "destructiveHint": True,
    },
    "geonodes_list_presets": {
        "title": "List GN presets",
        "readOnlyHint": True,
        "idempotentHint": True,
    },
    "geonodes_get_preset": {
        "title": "Get GN preset JSON",
        "readOnlyHint": True,
        "idempotentHint": True,
    },
    "geonodes_apply_preset": {
        "title": "Apply GN preset (build group)",
    },

    # --- v2.4: rename + spatial helpers ------------------------------------
    "rename": {"title": "Rename datablock", "idempotentHint": True},
    "place_above": {"title": "Place above target", "idempotentHint": True},
    "align_to": {"title": "Align to target", "idempotentHint": True},
    "array_around": {"title": "Array around center"},
    "distribute": {"title": "Distribute along line", "idempotentHint": True},
    "look_at": {"title": "Look at target", "idempotentHint": True},
    "bbox_info": {
        "title": "Get bounding box",
        "readOnlyHint": True,
        "idempotentHint": True,
    },

    # --- v2.5: selection / object lifecycle / collections ------------------
    "select": {"title": "Select objects", "idempotentHint": True},
    "deselect_all": {"title": "Deselect all", "idempotentHint": True},
    "set_active": {"title": "Set active object", "idempotentHint": True},
    "select_all": {"title": "Select all (optionally by type)", "idempotentHint": True},
    "duplicate_object": {"title": "Duplicate object"},
    "set_visibility": {"title": "Set visibility flags", "idempotentHint": True},
    "set_parent": {"title": "Parent to object", "idempotentHint": True},
    "clear_parent": {"title": "Unparent object(s)", "idempotentHint": True},
    "create_collection": {"title": "Create collection"},
    "delete_collection": {"title": "Delete collection", "destructiveHint": True},
    "move_to_collection": {"title": "Move to collection", "idempotentHint": True},
    "list_collections": {
        "title": "List collections",
        "readOnlyHint": True,
        "idempotentHint": True,
    },

    # --- v3.0 Tier-1 capability batch --------------------------------------
    # Data-block creators
    "create_light": {"title": "Create light"},
    "create_camera": {"title": "Create camera"},
    "set_active_camera": {"title": "Set active scene camera", "idempotentHint": True},
    "create_empty": {"title": "Create empty"},
    "create_text": {"title": "Create 3D text"},
    "create_curve": {"title": "Create curve from points"},
    "create_armature": {"title": "Create armature with bones"},
    "load_image": {"title": "Load image from disk", "openWorldHint": True},
    "create_image": {"title": "Create blank image"},

    # Mode + edit-mode mesh DSL + read-only mesh inspection
    "set_mode": {"title": "Set interaction mode", "idempotentHint": True},
    "mesh_edit": {"title": "Apply bmesh ops to mesh"},
    "mesh_read": {
        "title": "Read mesh geometry",
        "readOnlyHint": True,
        "idempotentHint": True,
    },

    # Constraints (object + pose-bone)
    "add_constraint": {"title": "Add constraint"},
    "remove_constraint": {"title": "Remove constraint", "destructiveHint": True},
    "list_constraints": {
        "title": "List constraints",
        "readOnlyHint": True,
        "idempotentHint": True,
    },

    # Vertex groups
    "create_vertex_group": {"title": "Create vertex group"},
    "remove_vertex_group": {"title": "Remove vertex group", "destructiveHint": True},
    "list_vertex_groups": {
        "title": "List vertex groups",
        "readOnlyHint": True,
        "idempotentHint": True,
    },
    "set_vertex_weights": {"title": "Set vertex weights", "idempotentHint": True},

    # Shape keys
    "add_shape_key": {"title": "Add shape key"},
    "set_shape_key_value": {"title": "Set shape key value", "idempotentHint": True},
    "remove_shape_key": {"title": "Remove shape key", "destructiveHint": True},
    "list_shape_keys": {
        "title": "List shape keys",
        "readOnlyHint": True,
        "idempotentHint": True,
    },
}


def for_tool(name: str) -> ToolMeta:
    """Return the annotation dict for a tool. Empty dict if unknown."""
    return TOOL_META.get(name, {})


def read_only_tools() -> frozenset[str]:
    """All tool names whose meta sets readOnlyHint=True.

    Used by `policy.is_mutating()` to decide which tools bypass the
    rate-limiter token bucket.
    """
    return frozenset(n for n, m in TOOL_META.items() if m.get("readOnlyHint"))


__all__ = ["TOOL_META", "ToolMeta", "for_tool", "read_only_tools"]
