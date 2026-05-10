"""Headless: scene.snapshot returns a stable hash + diff via re-run."""

from __future__ import annotations

import bpy

from conftest import call


def test_snapshot_has_hash_and_counts():
    out = call("scene.snapshot", {})
    assert "hash" in out and len(out["hash"]) == 16
    assert "counts" in out
    assert out["counts"]["objects"] >= 1  # factory startup has Cube/Light/Camera


def test_snapshot_summary_mode_omits_objects():
    out = call("scene.snapshot", {"summary": True})
    assert "counts" in out
    # Summary mode skips per-object payloads.
    assert "objects" not in out or not out["objects"]


def test_snapshot_hash_stable_across_no_op():
    h1 = call("scene.snapshot", {})["hash"]
    h2 = call("scene.snapshot", {})["hash"]
    assert h1 == h2


def test_snapshot_hash_changes_after_create():
    h1 = call("scene.snapshot", {})["hash"]
    call("create_objects", {"specs": [
        {"kind": "primitive", "primitive": "cube", "name": "DiffMarker"},
    ]})
    h2 = call("scene.snapshot", {})["hash"]
    assert h1 != h2
