"""Headless: create_objects actually mutates bpy.data."""

from __future__ import annotations

import bpy

from conftest import call


def test_create_cube_appears_in_scene():
    before = {o.name for o in bpy.data.objects}
    out = call("create_objects", {"specs": [
        {"kind": "primitive", "primitive": "cube", "name": "T_Cube"},
    ]})
    after = {o.name for o in bpy.data.objects}
    assert out["count"] == 1
    assert (after - before) >= {"T_Cube"}


def test_create_objects_dry_run_does_not_mutate():
    before = {o.name for o in bpy.data.objects}
    out = call("create_objects", {"specs": [
        {"kind": "primitive", "primitive": "uv_sphere", "name": "T_DryBall"},
    ]}, dry_run=True)
    after = {o.name for o in bpy.data.objects}
    assert out.get("dry_run") is True
    assert before == after  # nothing created


def test_create_three_objects_in_one_call():
    out = call("create_objects", {"specs": [
        {"kind": "primitive", "primitive": "cube", "name": "T_A"},
        {"kind": "primitive", "primitive": "cube", "name": "T_B"},
        {"kind": "primitive", "primitive": "cube", "name": "T_C"},
    ]})
    assert out["count"] == 3
    names = {o.name for o in bpy.data.objects}
    assert {"T_A", "T_B", "T_C"} <= names
