"""Headless: geonodes ops on a real Blender scene."""

from __future__ import annotations

import bpy

from conftest import call


def test_create_modifier_creates_group():
    # Use the factory-startup Cube.
    out = call("geonodes.create_modifier", {"object": "Cube", "name": "GN"})
    assert out["created_group"] is True
    cube = bpy.data.objects["Cube"]
    mod = cube.modifiers.get("GN")
    assert mod is not None and mod.type == "NODES"
    assert mod.node_group is not None


def test_describe_group_after_create():
    call("geonodes.create_modifier", {"object": "Cube", "name": "GN"})
    grp_name = bpy.data.objects["Cube"].modifiers["GN"].node_group.name
    out = call("geonodes.describe_group", {"name": grp_name})
    # Shape contract: describe_group returns lists of inputs/outputs and
    # counts. The exact default-tree socket names vary across Blender
    # 4.2/4.3/4.4, so we don't pin a specific name here.
    assert isinstance(out["inputs"], list)
    assert isinstance(out["outputs"], list)
    assert isinstance(out["node_count"], int)
    assert isinstance(out["link_count"], int)
    assert out["name"] == grp_name


def test_create_group_empty():
    out = call("geonodes.create_group", {
        "name": "MyEmptyGN",
        "inputs": [{"name": "Geometry", "socket_type": "NodeSocketGeometry"}],
        "outputs": [{"name": "Geometry", "socket_type": "NodeSocketGeometry"}],
    })
    assert out["created"] is True
    assert "MyEmptyGN" in bpy.data.node_groups


def test_realize_dry_run_keeps_modifier():
    call("geonodes.create_modifier", {"object": "Cube", "name": "GN"})
    cube = bpy.data.objects["Cube"]
    mods_before = [m.name for m in cube.modifiers]
    out = call("geonodes.realize", {"object": "Cube", "modifier": "GN"}, dry_run=True)
    assert out.get("dry_run") is True
    assert [m.name for m in cube.modifiers] == mods_before


def test_list_presets_returns_three():
    out = call("geonodes.list_presets", {})
    names = {p["name"] for p in out["presets"]}
    assert {"scatter-on-surface", "array-along-curve", "displace-noise"} <= names


def test_get_preset_payload_complete():
    out = call("geonodes.get_preset", {"name": "scatter-on-surface"})
    assert "group" in out and "graph" in out
    assert out["group"]["inputs"]


def test_apply_preset_creates_group():
    out = call("geonodes.apply_preset", {"preset": "scatter-on-surface"})
    grp = bpy.data.node_groups.get(out["group"])
    assert grp is not None and grp.bl_idname == "GeometryNodeTree"
    assert out["node_count"] >= 1
    assert out["link_count"] >= 1
    # Interface populated
    in_names = {it.name for it in grp.interface.items_tree
                if it.in_out == "INPUT"}
    assert "Geometry" in in_names and "Density" in in_names


def test_apply_preset_attaches_modifier():
    out = call("geonodes.apply_preset", {
        "preset": "array-along-curve",
        "object": "Cube",
        "modifier": "GN_Array",
    })
    cube = bpy.data.objects["Cube"]
    mod = cube.modifiers.get("GN_Array")
    assert mod is not None and mod.type == "NODES"
    assert mod.node_group is not None
    assert mod.node_group.name == out["group"]


def test_apply_preset_dry_run_no_group_created():
    before = set(bpy.data.node_groups.keys())
    out = call("geonodes.apply_preset",
               {"preset": "scatter-on-surface"}, dry_run=True)
    after = set(bpy.data.node_groups.keys())
    assert out.get("dry_run") is True
    assert before == after
