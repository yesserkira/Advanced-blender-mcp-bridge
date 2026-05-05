"""Tests for the checkpoint storage manager (pure-Python parts).

Save/restore (which call bpy.ops.wm.*) are exercised at runtime inside
Blender; they are not unit-testable here. We instead test path layout,
metadata round-trips, listing, and pruning.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from blender_addon.safety import checkpoints as ck


@pytest.fixture
def tmp_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect checkpoints_root() to a temp dir."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    # Sanity: root resolves under tmp_path
    assert str(tmp_path) in str(ck.checkpoints_root())
    return tmp_path


def _create_fake_checkpoint(
    source: str | None,
    label: str,
    *,
    blend_size: int = 1024,
) -> tuple[Path, Path]:
    blend, meta, label_safe, ts = ck.build_paths(source, label)
    blend.parent.mkdir(parents=True, exist_ok=True)
    blend.write_bytes(b"\x00" * blend_size)
    ck.write_metadata(
        meta,
        label=label_safe,
        timestamp=ts,
        blend_path=blend,
        source_blend=source,
        note=None,
    )
    return blend, meta


# ---------------------------------------------------------------------------
# Path / label sanitisation
# ---------------------------------------------------------------------------


def test_safe_label_strips_unsafe_chars():
    assert ck._safe_label("hello world!@#") == "hello-world"
    assert ck._safe_label("../../etc/passwd") == "etc-passwd"
    assert ck._safe_label("") == "checkpoint"
    assert ck._safe_label(None) == "checkpoint"


def test_safe_label_truncates():
    long = "x" * 200
    assert len(ck._safe_label(long)) == ck.LABEL_MAX_LEN


def test_project_dir_stable_per_source(tmp_root: Path):
    a = ck.project_dir("/some/file.blend")
    b = ck.project_dir("/some/file.blend")
    c = ck.project_dir("/other/file.blend")
    assert a == b
    assert a != c


def test_project_dir_untitled_for_none(tmp_root: Path):
    a = ck.project_dir(None)
    b = ck.project_dir(None)
    assert a == b


def test_build_paths_unique_per_call(tmp_root: Path):
    """Different labels produce different filenames within the same second."""
    blend1, meta1, _, _ = ck.build_paths("/x.blend", "step-1")
    blend2, meta2, _, _ = ck.build_paths("/x.blend", "step-2")
    assert blend1 != blend2
    assert meta1 != meta2
    assert blend1.suffix == ".blend"
    assert meta1.suffix == ".json"


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_list_empty_when_no_dir(tmp_root: Path):
    assert ck.list_checkpoints("/nope.blend") == []


def test_list_returns_newest_first(tmp_root: Path):
    src = "/proj/a.blend"
    # Manually craft entries with controlled timestamps so test isn't flaky.
    pdir = ck.project_dir(src)
    pdir.mkdir(parents=True, exist_ok=True)
    for ts, label in [
        ("20260101T000001Z", "first"),
        ("20260101T000002Z", "second"),
        ("20260101T000003Z", "third"),
    ]:
        blend = pdir / f"{ts}-{label}.blend"
        meta = pdir / f"{ts}-{label}.json"
        blend.write_bytes(b"data")
        ck.write_metadata(
            meta,
            label=label,
            timestamp=ts,
            blend_path=blend,
            source_blend=src,
            note=None,
        )
    entries = ck.list_checkpoints(src)
    assert [e.label for e in entries] == ["third", "second", "first"]
    assert all(e.size_bytes == 4 for e in entries)


def test_list_skips_orphan_meta(tmp_root: Path):
    src = "/proj/b.blend"
    blend, meta = _create_fake_checkpoint(src, "ok")
    # Create an orphan meta whose blend is missing.
    orphan_meta = meta.parent / "20260101T000000Z-orphan.json"
    ck.write_metadata(
        orphan_meta,
        label="orphan",
        timestamp="20260101T000000Z",
        blend_path=meta.parent / "missing.blend",
        source_blend=src,
        note=None,
    )
    entries = ck.list_checkpoints(src)
    assert len(entries) == 1
    assert entries[0].label.startswith("ok")


def test_list_skips_unreadable_meta(tmp_root: Path):
    src = "/proj/c.blend"
    pdir = ck.project_dir(src)
    pdir.mkdir(parents=True, exist_ok=True)
    bad = pdir / "20260101T000000Z-bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert ck.list_checkpoints(src) == []


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------


def test_prune_keeps_n_newest(tmp_root: Path):
    src = "/proj/d.blend"
    pdir = ck.project_dir(src)
    pdir.mkdir(parents=True, exist_ok=True)
    for i in range(5):
        ts = f"2026010{i+1}T000000Z"
        blend = pdir / f"{ts}-c{i}.blend"
        meta = pdir / f"{ts}-c{i}.json"
        blend.write_bytes(b"x")
        ck.write_metadata(
            meta,
            label=f"c{i}",
            timestamp=ts,
            blend_path=blend,
            source_blend=src,
            note=None,
        )
    removed = ck.prune(src, keep=2)
    assert len(removed) == 3
    remaining = ck.list_checkpoints(src)
    assert [e.label for e in remaining] == ["c4", "c3"]


def test_prune_no_op_when_under_limit(tmp_root: Path):
    src = "/proj/e.blend"
    _create_fake_checkpoint(src, "only")
    assert ck.prune(src, keep=10) == []
    assert len(ck.list_checkpoints(src)) == 1


def test_prune_clamps_keep_to_one(tmp_root: Path):
    src = "/proj/f.blend"
    pdir = ck.project_dir(src)
    pdir.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        ts = f"2026010{i+1}T000000Z"
        blend = pdir / f"{ts}-c{i}.blend"
        meta = pdir / f"{ts}-c{i}.json"
        blend.write_bytes(b"x")
        ck.write_metadata(
            meta,
            label=f"c{i}",
            timestamp=ts,
            blend_path=blend,
            source_blend=src,
            note=None,
        )
    ck.prune(src, keep=0)  # clamps to 1
    assert len(ck.list_checkpoints(src)) == 1


# ---------------------------------------------------------------------------
# bpy-required helpers fail gracefully without bpy
# ---------------------------------------------------------------------------


def test_save_checkpoint_without_bpy(tmp_root: Path):
    out = ck.save_checkpoint("test")
    assert out["ok"] is False
    assert out["error"] == "bpy_unavailable"


def test_restore_checkpoint_without_bpy(tmp_root: Path):
    src = "/proj/g.blend"
    blend, _ = _create_fake_checkpoint(src, "ok")
    out = ck.restore_checkpoint(str(blend))
    assert out["ok"] is False
    assert out["error"] == "bpy_unavailable"


# ---------------------------------------------------------------------------
# Metadata round-trip
# ---------------------------------------------------------------------------


def test_metadata_includes_required_fields(tmp_root: Path):
    src = "/proj/h.blend"
    blend, meta = _create_fake_checkpoint(src, "round-trip")
    payload = json.loads(meta.read_text(encoding="utf-8"))
    for key in ("label", "timestamp", "blend_path", "source_blend", "created_at"):
        assert key in payload
    assert payload["source_blend"] == src
    assert payload["blend_path"] == str(blend)
