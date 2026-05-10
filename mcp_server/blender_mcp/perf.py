"""Lightweight server-side perf instrumentation.

Two surfaces:

* **Always-on ring buffer** (cheap ~3µs per record, ~150 KB total at full
  capacity). Every Blender op routed through ``server._call`` records
  ``(ts, op, wall_ms, ok, payload_in_b, payload_out_b)``. Read it back
  with the ``perf_stats`` MCP tool.

* **Verbose mode** — when the env var ``BLENDER_MCP_PERF`` is set to a
  truthy value (``1`` / ``true`` / ``yes``), every call additionally
  emits a structured ``logger.debug`` line. Off by default; instrumentation
  must stay free for production users.

The ring buffer is process-local. Each MCP server process has its own
buffer; restart clears history. For long-term retention use the existing
audit log (``blender_addon/safety/audit_log.py``).
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any

logger = logging.getLogger("blender_mcp.perf")

# Ring capacity: 2000 entries * ~80 bytes (tuple of small ints/strs) ≈ 160 KB.
# At a sustained 100 ops/min that's a 20-minute window — enough to debug a
# typical chat session without unbounded memory growth.
RING_CAPACITY = 2000

# tuple = (ts_unix, op, wall_ms, ok, payload_in_b, payload_out_b)
_PerfRow = tuple[float, str, float, bool, int, int]
_ring: deque[_PerfRow] = deque(maxlen=RING_CAPACITY)
_lock = Lock()


def _verbose_from_env() -> bool:
    val = os.environ.get("BLENDER_MCP_PERF", "").strip().lower()
    return val in ("1", "true", "yes", "on")


# Cached at import time. Tests can flip via `set_verbose(True)`.
_VERBOSE = _verbose_from_env()


def is_verbose() -> bool:
    """Return True if BLENDER_MCP_PERF is set (or `set_verbose(True)` was called)."""
    return _VERBOSE


def set_verbose(value: bool) -> None:
    """Override the env-driven verbose flag. Used by tests."""
    global _VERBOSE
    _VERBOSE = bool(value)


def record(
    op: str,
    wall_ms: float,
    ok: bool,
    payload_in_b: int = 0,
    payload_out_b: int = 0,
) -> None:
    """Record one call. O(1), ~3µs.

    `payload_in_b` / `payload_out_b` are recorded as-given; callers are free
    to pass 0 when not in verbose mode (computing JSON length isn't free).
    """
    ts = time.time()
    with _lock:
        _ring.append((ts, op, wall_ms, ok, payload_in_b, payload_out_b))
    if _VERBOSE:
        logger.debug(
            "perf op=%s wall_ms=%.3f ok=%s in=%d out=%d",
            op, wall_ms, ok, payload_in_b, payload_out_b,
        )


def snapshot() -> list[_PerfRow]:
    """Return a stable copy of the ring (for tests / aggregation)."""
    with _lock:
        return list(_ring)


def reset() -> None:
    """Clear the ring. Used by tests."""
    with _lock:
        _ring.clear()


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile. ``sorted_values`` must be ascending."""
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    # nearest-rank: ceil(p/100 * n) - 1, clamped to [0, n-1]
    idx = max(0, min(n - 1, int(round(pct / 100.0 * n)) - 1))
    return sorted_values[idx]


def aggregate(
    window_seconds: float | None = None,
    op: str | None = None,
) -> dict[str, Any]:
    """Compute per-op stats from the ring buffer.

    Args:
        window_seconds: only count calls within the last N seconds
                        (``None`` = every entry currently in the ring).
        op: filter to a single op name (``None`` = all ops).

    Returns a dict shaped:
        {
            "window_seconds": float | None,
            "ring_capacity": int,
            "ring_used": int,
            "total_calls": int,
            "ops": {
                "<op_name>": {
                    "count": int,
                    "errors": int,
                    "p50_ms": float, "p95_ms": float, "p99_ms": float,
                    "max_ms": float, "mean_ms": float,
                    "bytes_in_total": int, "bytes_out_total": int,
                },
                ...
            }
        }
    """
    samples = snapshot()
    cutoff = (time.time() - window_seconds) if window_seconds is not None else 0.0

    by_op: dict[str, list[_PerfRow]] = defaultdict(list)
    for row in samples:
        ts, opname, _wall, _ok, _in, _out = row
        if ts < cutoff:
            continue
        if op is not None and opname != op:
            continue
        by_op[opname].append(row)

    ops_out: dict[str, dict[str, Any]] = {}
    for opname, rows in by_op.items():
        wall_sorted = sorted(r[2] for r in rows)
        n = len(wall_sorted)
        ops_out[opname] = {
            "count": n,
            "errors": sum(1 for r in rows if not r[3]),
            "p50_ms": round(_percentile(wall_sorted, 50), 3),
            "p95_ms": round(_percentile(wall_sorted, 95), 3),
            "p99_ms": round(_percentile(wall_sorted, 99), 3),
            "max_ms": round(wall_sorted[-1], 3),
            "mean_ms": round(sum(wall_sorted) / n, 3),
            "bytes_in_total": sum(r[4] for r in rows),
            "bytes_out_total": sum(r[5] for r in rows),
        }

    return {
        "window_seconds": window_seconds,
        "ring_capacity": RING_CAPACITY,
        "ring_used": len(samples),
        "total_calls": sum(v["count"] for v in ops_out.values()),
        "ops": ops_out,
        "verbose": _VERBOSE,
    }
