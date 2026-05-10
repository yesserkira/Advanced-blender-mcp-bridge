"""Headless: dry-run flag never mutates state."""

from __future__ import annotations

import bpy

from conftest import call


def test_dry_run_create_objects_no_mutation():
    n_before = len(bpy.data.objects)
    out = call("create_objects", {"specs": [
        {"kind": "primitive", "primitive": "cube", "name": "X1"},
        {"kind": "primitive", "primitive": "cube", "name": "X2"},
    ]}, dry_run=True)
    assert out["dry_run"] is True
    assert "would" in out
    assert len(bpy.data.objects) == n_before


def test_dry_run_delete_object_keeps_object():
    # First create a real one
    call("create_objects", {"specs": [
        {"kind": "primitive", "primitive": "cube", "name": "Victim"},
    ]})
    assert "Victim" in bpy.data.objects
    out = call("object.delete", {"name": "Victim"}, dry_run=True)
    assert out.get("dry_run") is True
    assert "Victim" in bpy.data.objects
