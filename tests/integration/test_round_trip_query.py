"""Headless: scene.context + describe_api round-trip."""

from __future__ import annotations

from conftest import call


def test_scene_context_returns_dict():
    out = call("scene.context", {})
    assert isinstance(out, dict)
    # Factory startup ships at least one scene with a Cube/Camera/Light.
    assert "scene" in out or "objects" in out or "counts" in out


def test_describe_api_returns_props_for_known_type():
    out = call("describe_api", {"rna_path": "SubsurfModifier"})
    assert isinstance(out, dict)
    prop_names = {p["name"] for p in out["properties"]}
    assert "levels" in prop_names
