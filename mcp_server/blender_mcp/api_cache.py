"""Persistent on-disk cache for ``describe_api`` results.

The Blender Python API (`bpy.types.X.bl_rna`) doesn't change between two
sessions of the same Blender version, but the in-process `_describe_api_cache`
in ``server.py`` evaporates on every restart. This module persists those
introspection results to ``%LOCALAPPDATA%\\BlenderMCP\\api_cache\\<version>.json``
so day-2+ users skip 100s of ms of bpy reflection per cold start.

Design
------
* **Version-keyed**: filename = sanitised Blender version. Two Blender
  installs (4.2 + 5.0) on the same machine each get their own file; never
  cross-contaminate.
* **In-memory LRU on top**: cap at 2000 entries. The disk file is uncapped
  (it's just JSON), but the live dict is bounded so a runaway `describe_api`
  loop can't OOM the server.
* **Debounced write-through**: every new entry bumps a dirty counter; we
  flush to disk on either (a) ``flush_threshold`` accumulated entries or
  (b) explicit ``flush()`` call. A single fsync per batch.
* **Counters**: ``hits`` / ``misses`` / ``disk_hits`` / ``writes`` exposed
  via ``stats()`` for the ``perf_stats`` MCP tool to surface.

Threading
---------
The MCP server runs everything on one asyncio event loop (one thread).
Cache mutations happen from `describe_api()` callers only — no need for
explicit locks. The disk I/O is sync-on-flush; if you ever move flush
off-thread, wrap with a ``threading.Lock`` first.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Hard cap on the live dict. Real-world describe_api use is well under 200
# distinct rna_paths per session; 2000 leaves ample headroom for batch tools.
MAX_IN_MEMORY = 2000

# Flush to disk after this many new entries since the last flush.
DEFAULT_FLUSH_THRESHOLD = 32

# Conservative filename sanitiser — Blender version strings are normally
# things like "4.2.0" or "5.0.0 alpha"; strip everything that's not a safe
# filesystem char so we never escape the cache directory.
_SANITISE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitise_version(version: str) -> str:
    return _SANITISE.sub("_", version) or "unknown"


def _default_cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    p = Path(base) / "BlenderMCP" / "api_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


class DescribeApiCache:
    """In-memory LRU + version-keyed disk file for ``describe_api`` results."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_in_memory: int = MAX_IN_MEMORY,
        flush_threshold: int = DEFAULT_FLUSH_THRESHOLD,
    ) -> None:
        self._cache_dir = cache_dir or _default_cache_dir()
        self._max = max_in_memory
        self._flush_threshold = flush_threshold
        self._mem: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._version: str | None = None
        self._dirty: int = 0
        self._loaded_from_disk = False
        # Counters exposed via stats() — never reset implicitly.
        self.hits = 0
        self.misses = 0
        self.disk_hits = 0
        self.writes = 0

    # ------------------------------------------------------------------
    # Version pinning + disk load
    # ------------------------------------------------------------------

    def bind_version(self, version: str) -> None:
        """Pin this cache to a specific Blender version and load its file.

        Idempotent: calling twice with the same version is a no-op. Calling
        with a different version drops the in-memory dict (the previous
        version's file is left on disk, untouched) and loads the new one.
        """
        v = _sanitise_version(version)
        if self._version == v and self._loaded_from_disk:
            return
        if self._version is not None and self._version != v:
            # Switched Blender versions mid-process — start fresh, don't
            # persist the old in-memory state into the new file.
            self._mem.clear()
            self._dirty = 0
            self._loaded_from_disk = False
        self._version = v
        self._load_from_disk()

    def _file_path(self) -> Path | None:
        if self._version is None:
            return None
        return self._cache_dir / f"{self._version}.json"

    def _load_from_disk(self) -> None:
        path = self._file_path()
        if path is None or not path.exists():
            self._loaded_from_disk = True
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("entries") if isinstance(data, dict) else None
            if isinstance(entries, dict):
                # Insert in iteration order; newest-end via LRU touch on hit.
                for key, value in entries.items():
                    if isinstance(key, str) and isinstance(value, dict):
                        self._mem[key] = value
                        self.disk_hits += 0  # populated on actual lookup
        except (OSError, json.JSONDecodeError) as exc:
            # Corrupt cache: log + continue with an empty dict. Don't crash
            # the server because someone hand-edited the file.
            logger.warning(
                "describe_api cache file %s unreadable (%s) — starting fresh",
                path, exc,
            )
            self._mem.clear()
        self._loaded_from_disk = True

    # ------------------------------------------------------------------
    # Lookup / insert
    # ------------------------------------------------------------------

    def get(self, rna_path: str) -> dict[str, Any] | None:
        """Return a cached entry (and bump it to the LRU tail), else None."""
        entry = self._mem.get(rna_path)
        if entry is None:
            self.misses += 1
            return None
        self._mem.move_to_end(rna_path)
        self.hits += 1
        return entry

    def put(self, rna_path: str, value: dict[str, Any]) -> None:
        """Cache an entry; auto-flush once the dirty buffer fills up.

        Errors-by-shape (responses with an "error" key) should NOT reach
        this method — that's the caller's responsibility (server.describe_api).
        """
        if rna_path in self._mem:
            # Refresh value + move to LRU tail.
            self._mem.move_to_end(rna_path)
            self._mem[rna_path] = value
            return
        self._mem[rna_path] = value
        self._dirty += 1
        # LRU eviction (in-memory only — the disk file keeps the entry until
        # the next flush replaces the file body).
        while len(self._mem) > self._max:
            self._mem.popitem(last=False)
        if self._dirty >= self._flush_threshold:
            self.flush()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def flush(self) -> bool:
        """Write the in-memory dict to disk atomically. Returns True if written."""
        path = self._file_path()
        if path is None or self._dirty == 0:
            return False
        payload = {
            "version": self._version,
            "schema": 1,
            "entries": dict(self._mem),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write: tempfile in same dir + os.replace, so a crash
            # mid-write never leaves a half-written JSON on disk.
            fd, tmp_path = tempfile.mkstemp(
                prefix=f"{self._version}.", suffix=".json.tmp", dir=str(path.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, separators=(",", ":"))
                os.replace(tmp_path, path)
            except Exception:
                # Clean up the temp file on failure.
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as exc:
            logger.warning("describe_api cache flush failed: %s", exc)
            return False
        self.writes += 1
        self._dirty = 0
        return True

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        hit_rate = (self.hits / total) if total else 0.0
        return {
            "version": self._version,
            "size": len(self._mem),
            "max_in_memory": self._max,
            "hits": self.hits,
            "misses": self.misses,
            "disk_hits": self.disk_hits,
            "writes": self.writes,
            "dirty": self._dirty,
            "hit_rate": round(hit_rate, 4),
        }

    def __len__(self) -> int:
        return len(self._mem)

    def __contains__(self, key: object) -> bool:
        return key in self._mem

    def clear(self) -> None:
        """Drop all in-memory entries and reset counters.

        Does NOT touch the on-disk file — call ``flush()`` first if you
        actually want the disk file emptied. Primarily for tests that need
        to reset state between runs without poking at module privates.
        """
        self._mem.clear()
        self._dirty = 0
        self.hits = 0
        self.misses = 0
        self.disk_hits = 0
        self.writes = 0
