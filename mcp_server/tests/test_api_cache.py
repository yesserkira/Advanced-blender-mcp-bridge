"""Phase 2 — DescribeApiCache unit tests.

Exercises the cache module in isolation (no FastMCP, no WS). Server-side
integration with `describe_api()` is already covered by
``test_error_paths.py::test_describe_api_does_not_cache_errors`` which
verifies the cache-skip-on-error contract through the real tool.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from blender_mcp.api_cache import DescribeApiCache, _sanitise_version


def _make(tmp_path: Path, **kwargs) -> DescribeApiCache:
    return DescribeApiCache(cache_dir=tmp_path, **kwargs)


# ---------------------------------------------------------------------------
# Version pinning + filename safety
# ---------------------------------------------------------------------------


def test_sanitise_version_strips_unsafe_chars():
    assert _sanitise_version("4.2.0") == "4.2.0"
    assert _sanitise_version("5.0.0 alpha") == "5.0.0_alpha"
    assert _sanitise_version("../../../etc") == ".._.._.._etc"
    assert _sanitise_version("") == "unknown"


def test_bind_version_creates_file_on_flush(tmp_path):
    c = _make(tmp_path)
    c.bind_version("4.2.0")
    c.put("X", {"name": "X"})
    c.flush()
    assert (tmp_path / "4.2.0.json").exists()


def test_bind_version_idempotent(tmp_path):
    c = _make(tmp_path)
    c.bind_version("4.2.0")
    c.put("X", {"v": 1})
    c.bind_version("4.2.0")  # same version
    # In-memory state preserved
    assert c.get("X") == {"v": 1}


def test_bind_version_switch_drops_in_memory(tmp_path):
    c = _make(tmp_path)
    c.bind_version("4.2.0")
    c.put("X", {"v": 1})
    c.bind_version("5.0.0")
    # Switched to a new version: in-memory dict cleared, the 4.2.0 file
    # was never flushed so it doesn't exist either, but the contract is
    # "old version's state doesn't bleed into the new file".
    assert c.get("X") is None
    c.put("Y", {"v": 2})
    c.flush()
    assert (tmp_path / "5.0.0.json").exists()
    assert not (tmp_path / "4.2.0.json").exists()


# ---------------------------------------------------------------------------
# Disk round-trip
# ---------------------------------------------------------------------------


def test_disk_roundtrip_repopulates_in_memory(tmp_path):
    c1 = _make(tmp_path)
    c1.bind_version("4.2.0")
    c1.put("X", {"name": "X"})
    c1.put("Y", {"name": "Y"})
    c1.flush()

    c2 = _make(tmp_path)
    c2.bind_version("4.2.0")
    assert c2.get("X") == {"name": "X"}
    assert c2.get("Y") == {"name": "Y"}


def test_corrupt_cache_file_starts_fresh(tmp_path, caplog):
    (tmp_path / "4.2.0.json").write_text("{not valid json", encoding="utf-8")
    c = _make(tmp_path)
    c.bind_version("4.2.0")
    assert len(c) == 0
    # New writes still work — the corrupt file gets overwritten on next flush.
    c.put("X", {"v": 1})
    c.flush()
    data = json.loads((tmp_path / "4.2.0.json").read_text(encoding="utf-8"))
    assert "X" in data["entries"]


# ---------------------------------------------------------------------------
# LRU + flush threshold
# ---------------------------------------------------------------------------


def test_lru_eviction_caps_in_memory(tmp_path):
    c = _make(tmp_path, max_in_memory=3, flush_threshold=999)
    c.bind_version("4.2.0")
    c.put("A", {"v": 1})
    c.put("B", {"v": 2})
    c.put("C", {"v": 3})
    # Touch A so B is the LRU victim
    assert c.get("A") == {"v": 1}
    c.put("D", {"v": 4})
    assert "B" not in c
    assert {"A", "C", "D"} == set(c._mem.keys())


def test_flush_threshold_triggers_write(tmp_path):
    c = _make(tmp_path, flush_threshold=2)
    c.bind_version("4.2.0")
    c.put("A", {"v": 1})
    assert c.writes == 0  # below threshold
    c.put("B", {"v": 2})
    assert c.writes == 1  # threshold tripped
    assert (tmp_path / "4.2.0.json").exists()


def test_flush_noop_when_clean(tmp_path):
    c = _make(tmp_path)
    c.bind_version("4.2.0")
    assert c.flush() is False  # nothing dirty
    c.put("X", {"v": 1})
    assert c.flush() is True
    assert c.flush() is False  # already clean


def test_put_existing_key_updates_value_no_dirty_bump(tmp_path):
    c = _make(tmp_path, flush_threshold=99)
    c.bind_version("4.2.0")
    c.put("X", {"v": 1})
    dirty_before = c._dirty
    c.put("X", {"v": 2})
    assert c.get("X") == {"v": 2}
    assert c._dirty == dirty_before  # refresh, not insert


# ---------------------------------------------------------------------------
# Counters / stats
# ---------------------------------------------------------------------------


def test_stats_tracks_hits_misses_hit_rate(tmp_path):
    c = _make(tmp_path)
    c.bind_version("4.2.0")
    c.put("A", {"v": 1})
    c.get("A")  # hit
    c.get("A")  # hit
    c.get("B")  # miss
    s = c.stats()
    assert s["hits"] == 2
    assert s["misses"] == 1
    assert s["hit_rate"] == round(2 / 3, 4)
    assert s["size"] == 1
    assert s["version"] == "4.2.0"


# ---------------------------------------------------------------------------
# No-version safety
# ---------------------------------------------------------------------------


def test_flush_without_bind_is_noop(tmp_path):
    c = _make(tmp_path)
    c.put("X", {"v": 1})
    assert c.flush() is False
    # No file was created — nothing was flushed because version isn't pinned.
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Atomic write: tempfile cleanup on success
# ---------------------------------------------------------------------------


def test_no_tmp_files_left_after_flush(tmp_path):
    c = _make(tmp_path)
    c.bind_version("4.2.0")
    c.put("X", {"v": 1})
    c.flush()
    leftovers = [p for p in tmp_path.iterdir() if ".tmp" in p.name]
    assert leftovers == []


# ---------------------------------------------------------------------------
# Server integration: stats surfaced via perf_stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_perf_stats_surfaces_describe_api_cache(monkeypatch, tmp_path):
    from blender_mcp import server

    fresh = DescribeApiCache(cache_dir=tmp_path)
    fresh.bind_version("4.2.0")
    fresh.put("X", {"v": 1})
    fresh.get("X")  # one hit
    monkeypatch.setattr(server, "_describe_api_cache", fresh)
    monkeypatch.setattr(server, "_policy", server.Policy.load(None))

    out = await server.perf_stats()
    assert "describe_api_cache" in out
    cache_stats = out["describe_api_cache"]
    assert cache_stats["version"] == "4.2.0"
    assert cache_stats["hits"] == 1
    assert cache_stats["size"] == 1
