"""Verify bundled Geometry Nodes presets parse and have valid shape."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


PRESETS_DIR = (
    Path(__file__).resolve().parents[2]
    / "blender_addon" / "presets" / "geonodes"
)

EXPECTED_PRESETS = {"scatter-on-surface", "array-along-curve", "displace-noise"}


def test_presets_dir_exists():
    assert PRESETS_DIR.is_dir(), f"missing presets dir: {PRESETS_DIR}"


@pytest.mark.parametrize("name", sorted(EXPECTED_PRESETS))
def test_preset_shape(name):
    path = PRESETS_DIR / f"{name}.json"
    assert path.is_file(), f"missing preset: {path}"
    data = json.loads(path.read_text(encoding="utf-8"))

    # Top-level required keys
    for k in ("name", "title", "description", "group", "graph"):
        assert k in data, f"{name}: missing key '{k}'"
    assert data["name"] == name

    # Group shape
    grp = data["group"]
    assert "name" in grp and grp["name"]
    assert isinstance(grp.get("inputs"), list) and grp["inputs"]
    assert isinstance(grp.get("outputs"), list) and grp["outputs"]
    for sock in grp["inputs"] + grp["outputs"]:
        assert "name" in sock and "socket_type" in sock

    # Graph shape — every link target must reference a declared node
    g = data["graph"]
    nodes = g.get("nodes") or []
    links = g.get("links") or []
    assert nodes, f"{name}: graph has no nodes"
    declared = {n["name"] for n in nodes}
    # NodeGroupInput / NodeGroupOutput pseudo-sources are by node name "in"/"out"
    for link in links:
        src = link["from"].split(".", 1)[0]
        dst = link["to"].split(".", 1)[0]
        assert src in declared, f"{name}: link source '{src}' not in nodes"
        assert dst in declared, f"{name}: link target '{dst}' not in nodes"
