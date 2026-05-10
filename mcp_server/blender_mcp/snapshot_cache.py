"""Per-process TTL cache for repeated read-only Blender ops.

Phase 3 — coalesces the ``ping``/``scene.context``/``scene.snapshot`` storm at
the start of every model turn. The model is instructed (via the workspace
``copilot-instructions.md``) to call ``ping`` first every conversation, and
typical turns then issue 1-3 more read-only ``query``/``list`` calls before
doing any work. Each one currently round-trips to Blender even though the
scene state didn't change.

This module wraps any read-only op with a tiny TTL cache (default 200ms,
tunable via ``BLENDER_MCP_SNAPSHOT_TTL_MS``). The cache key includes a
``scene_epoch`` counter that the dispatcher bumps on every mutating tool
call and that ``_on_blender_notification`` bumps on every ``scene.changed``
event from the add-on. So:

* Three ``ping`` calls in a 100ms window → 1 round-trip + 2 cache hits.
* ``ping`` → ``set_transform`` → ``ping``: epoch changes, second ``ping``
  re-fetches.
* External user moves a cube in the Blender UI: add-on broadcasts
  ``scene.changed`` → epoch bumps → next ``ping`` re-fetches.

Design notes
------------
* **Per-process**: each MCP server has its own cache. Multiple clients each
  get their own MCP server, so no cross-client coherence is needed.
* **No locks**: everything runs on the asyncio event loop (single thread).
* **TTL safety net**: even if the epoch invalidator misses an edge case,
  entries expire after ``ttl_ms``. 200ms feels live to the user.
* **Cache key = (op, args-hash, epoch)**: same op + different args = different
  entries. Bumping epoch invalidates everything for free (old entries simply
  miss on lookup; they'll be GC'd next time their slot is overwritten).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Awaitable

# Default TTL: short enough to feel live, long enough to coalesce a 3-call
# burst at the start of a turn. Override via env for ops who need different
# slack (e.g. CI may want 0 to disable; interactive use may want 500).
DEFAULT_TTL_MS = 200


def _ttl_from_env(default_ms: int = DEFAULT_TTL_MS) -> int:
    raw = os.environ.get("BLENDER_MCP_SNAPSHOT_TTL_MS")
    if raw is None:
        return default_ms
    try:
        v = int(raw)
        return max(0, v)
    except ValueError:
        return default_ms


class SnapshotCache:
    """TTL + epoch-tagged cache for read-only Blender op responses.

    Use ``get_or_call(op, args, fetcher)`` from the dispatcher: it returns
    a cached value if (op, args, current epoch) is fresh, else awaits
    ``fetcher()``, stores, and returns. Mutating tool calls must invoke
    ``bump_epoch()`` to invalidate everything. ``scene.changed`` notifications
    do the same.
    """

    def __init__(self, ttl_ms: int | None = None) -> None:
        self._ttl_ms = ttl_ms if ttl_ms is not None else _ttl_from_env()
        self._epoch: int = 0
        # key -> (epoch, expires_monotonic_seconds, value)
        self._entries: dict[str, tuple[int, float, Any]] = {}
        # Counters for perf_stats
        self.hits = 0
        self.misses = 0
        self.invalidations = 0

    # --- Public API ----------------------------------------------------

    @property
    def ttl_ms(self) -> int:
        return self._ttl_ms

    @property
    def epoch(self) -> int:
        return self._epoch

    def bump_epoch(self) -> None:
        """Invalidate every entry. Call on any mutating op or scene.changed."""
        self._epoch += 1
        self.invalidations += 1
        # Don't clear ``_entries`` — old keys just won't match the new epoch
        # on lookup, and they'll be overwritten as fresh values come in.
        # Saves a dict allocation under load.

    async def get_or_call(
        self,
        op: str,
        args: dict[str, Any] | None,
        fetcher: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Return a cached value or await ``fetcher()`` and cache its result.

        ``fetcher`` is the closure that does the real work (e.g. a wrapped
        ``_call`` invocation). Errors are NOT cached — if ``fetcher`` raises
        or returns an error envelope (``{"error": ...}``), the cache stays
        untouched and the next call re-fetches.
        """
        if self._ttl_ms <= 0:
            # TTL disabled — bypass the cache entirely.
            return await fetcher()

        key = self._key(op, args)
        now = time.monotonic()
        entry = self._entries.get(key)
        if entry is not None:
            cached_epoch, expires_at, value = entry
            if cached_epoch == self._epoch and expires_at > now:
                self.hits += 1
                return value
        self.misses += 1
        result = await fetcher()
        # Don't cache error envelopes — the next caller deserves a fresh try.
        if not (isinstance(result, dict) and "error" in result):
            self._entries[key] = (
                self._epoch, now + self._ttl_ms / 1000.0, result,
            )
        return result

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        hit_rate = (self.hits / total) if total else 0.0
        return {
            "ttl_ms": self._ttl_ms,
            "epoch": self._epoch,
            "size": len(self._entries),
            "hits": self.hits,
            "misses": self.misses,
            "invalidations": self.invalidations,
            "hit_rate": round(hit_rate, 4),
        }

    def clear(self) -> None:
        """Reset everything (counters + entries + epoch). Test helper."""
        self._entries.clear()
        self._epoch = 0
        self.hits = 0
        self.misses = 0
        self.invalidations = 0

    # --- Internals -----------------------------------------------------

    @staticmethod
    def _key(op: str, args: dict[str, Any] | None) -> str:
        """Stable serialisation of (op, args). ``sort_keys`` so dict order
        from the model client doesn't fragment the cache."""
        if not args:
            return op
        try:
            args_str = json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            # Args contains something weird; fall back to repr (non-canonical
            # but at least stable within a single Python process).
            args_str = repr(sorted(args.items()))
        return f"{op}|{args_str}"
