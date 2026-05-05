"""Tests for the polygon estimator (Phase 5)."""

from __future__ import annotations

import pytest

from blender_mcp.policy import estimate_polys


def test_estimate_cube():
    assert estimate_polys([{"kind": "cube"}]) == 6


def test_estimate_unknown_kind_uses_default():
    # Unknown kinds get a small fixed budget so they're counted, not free.
    n = estimate_polys([{"kind": "weird-thing"}])
    assert 0 < n < 10_000


def test_estimate_zero_for_lights_cameras_empties():
    assert estimate_polys([{"kind": "light"}, {"kind": "camera"}, {"kind": "empty"}]) == 0


def test_estimate_subsurf_grows_geometrically():
    plain = estimate_polys([{"kind": "cube"}])
    sub2 = estimate_polys(
        [
            {
                "kind": "cube",
                "modifiers": [{"type": "SUBSURF", "properties": {"levels": 2}}],
            }
        ]
    )
    # 4^2 = 16x growth
    assert sub2 == plain * 16


def test_estimate_subsurf_caps_at_level_4():
    huge = estimate_polys(
        [{"kind": "cube", "modifiers": [{"type": "SUBSURF", "properties": {"levels": 100}}]}]
    )
    capped = estimate_polys(
        [{"kind": "cube", "modifiers": [{"type": "SUBSURF", "properties": {"levels": 4}}]}]
    )
    assert huge == capped


def test_estimate_array_multiplies_by_count():
    one = estimate_polys([{"kind": "cube"}])
    twenty = estimate_polys(
        [{"kind": "cube", "modifiers": [{"type": "ARRAY", "properties": {"count": 20}}]}]
    )
    assert twenty == one * 20


def test_estimate_sums_specs():
    total = estimate_polys([{"kind": "cube"}, {"kind": "uv_sphere"}])
    assert total == 6 + 960


def test_estimate_handles_invalid_input():
    assert estimate_polys([]) == 0
    assert estimate_polys([None, "x", 42]) == 0  # type: ignore[list-item]


def test_estimate_handles_kind_synonyms():
    # 'sphere' alias works the same as 'uv_sphere'
    assert estimate_polys([{"kind": "sphere"}]) == estimate_polys([{"kind": "uv_sphere"}])


@pytest.mark.parametrize(
    "kind,expected",
    [("cube", 6), ("plane", 1), ("circle", 32), ("monkey", 968)],
)
def test_estimate_known_primitives(kind: str, expected: int):
    assert estimate_polys([{"kind": kind}]) == expected
