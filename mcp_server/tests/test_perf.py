"""Tests for blender_mcp.perf — ring buffer, aggregation, server integration."""

from __future__ import annotations


import pytest

from blender_mcp import perf, server
from blender_mcp.policy import Policy


@pytest.fixture(autouse=True)
def _reset_perf():
    """Each test starts with an empty ring + empty snapshot cache."""
    perf.reset()
    server._snapshot_cache.clear()
    yield
    perf.reset()
    server._snapshot_cache.clear()


# ---------------------------------------------------------------------------
# Ring buffer + aggregation
# ---------------------------------------------------------------------------


def test_ring_records_and_caps_at_capacity():
    for i in range(perf.RING_CAPACITY + 50):
        perf.record("ping", 1.0, True)
    snap = perf.snapshot()
    assert len(snap) == perf.RING_CAPACITY


def test_aggregate_empty_returns_zero_calls():
    out = perf.aggregate()
    assert out["total_calls"] == 0
    assert out["ops"] == {}
    assert out["ring_used"] == 0


def test_aggregate_basic_percentiles():
    # 100 samples, 1..100 ms — easy to verify percentiles.
    for ms in range(1, 101):
        perf.record("ping", float(ms), ok=True)
    out = perf.aggregate()
    stats = out["ops"]["ping"]
    assert stats["count"] == 100
    assert stats["errors"] == 0
    # Nearest-rank: p50 of 1..100 = 50, p95 = 95, p99 = 99
    assert stats["p50_ms"] == 50.0
    assert stats["p95_ms"] == 95.0
    assert stats["p99_ms"] == 99.0
    assert stats["max_ms"] == 100.0
    assert stats["mean_ms"] == 50.5


def test_aggregate_filters_by_op():
    perf.record("ping", 1.0, True)
    perf.record("query", 2.0, True)
    perf.record("query", 3.0, True)
    out = perf.aggregate(op="query")
    assert set(out["ops"]) == {"query"}
    assert out["ops"]["query"]["count"] == 2


def test_aggregate_window_seconds():
    import time
    # Record an entry, then back-date the ring artificially via reset+append.
    perf._ring.append((time.time() - 60.0, "old", 5.0, True, 0, 0))
    perf.record("new", 1.0, True)
    out = perf.aggregate(window_seconds=10.0)
    assert "old" not in out["ops"]
    assert out["ops"]["new"]["count"] == 1


def test_aggregate_counts_errors():
    perf.record("query", 1.0, ok=True)
    perf.record("query", 2.0, ok=False)
    perf.record("query", 3.0, ok=False)
    out = perf.aggregate()
    assert out["ops"]["query"]["count"] == 3
    assert out["ops"]["query"]["errors"] == 2


# ---------------------------------------------------------------------------
# Verbose mode (env-driven)
# ---------------------------------------------------------------------------


def test_verbose_flag_default_off(monkeypatch):
    monkeypatch.delenv("BLENDER_MCP_PERF", raising=False)
    # Re-evaluate the module-level cache by calling the helper directly.
    assert perf._verbose_from_env() is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "on", "TRUE", "Yes"])
def test_verbose_flag_truthy(monkeypatch, val):
    monkeypatch.setenv("BLENDER_MCP_PERF", val)
    assert perf._verbose_from_env() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", "", "anything-else"])
def test_verbose_flag_falsy(monkeypatch, val):
    monkeypatch.setenv("BLENDER_MCP_PERF", val)
    assert perf._verbose_from_env() is False


def test_set_verbose_overrides_env():
    perf.set_verbose(True)
    try:
        assert perf.is_verbose() is True
        perf.set_verbose(False)
        assert perf.is_verbose() is False
    finally:
        # Restore env-driven default for other tests in the suite.
        perf.set_verbose(perf._verbose_from_env())


# ---------------------------------------------------------------------------
# Server integration: _call() records to the ring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_call_records_success(monkeypatch):
    """Every successful _call routes through perf.record(ok=True)."""
    class _StubBL:
        async def call(self, op, args, timeout=30.0, dry_run=False):
            return {"ok": True}

    monkeypatch.setattr(server, "_bl", _StubBL())
    monkeypatch.setattr(server, "_get_client", lambda: server._bl)

    result = await server._call("ping")
    assert result == {"ok": True}

    snap = perf.snapshot()
    assert len(snap) == 1
    ts, op, wall_ms, ok, in_b, out_b = snap[0]
    assert op == "ping"
    assert ok is True
    assert wall_ms >= 0.0


@pytest.mark.asyncio
async def test_server_call_records_blender_error(monkeypatch):
    """BlenderError → ok=False in perf, error envelope in result."""
    from blender_mcp.blender_client import BlenderError

    class _StubBL:
        async def call(self, op, args, timeout=30.0, dry_run=False):
            raise BlenderError("BOOM", "exploded")

    monkeypatch.setattr(server, "_bl", _StubBL())
    monkeypatch.setattr(server, "_get_client", lambda: server._bl)

    result = await server._call("ping")
    assert result["error"] == "BOOM"
    assert perf.snapshot()[0][3] is False


@pytest.mark.asyncio
async def test_server_call_records_timeout(monkeypatch):
    """asyncio.TimeoutError → ok=False, TIMEOUT envelope."""
    import asyncio

    class _StubBL:
        async def call(self, op, args, timeout=30.0, dry_run=False):
            raise asyncio.TimeoutError()

    monkeypatch.setattr(server, "_bl", _StubBL())
    monkeypatch.setattr(server, "_get_client", lambda: server._bl)

    result = await server._call("slow_op", timeout=0.1)
    assert result["error"] == "TIMEOUT"
    assert perf.snapshot()[0][3] is False


# ---------------------------------------------------------------------------
# perf_stats MCP tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_perf_stats_tool_returns_aggregate(monkeypatch):
    """The perf_stats tool returns the same shape as perf.aggregate()."""
    monkeypatch.setattr(server, "_policy", Policy.load(None))

    perf.record("ping", 5.0, True)
    perf.record("query", 10.0, True)

    out = await server.perf_stats()
    assert "ops" in out
    assert set(out["ops"]) == {"ping", "query"}
    assert out["ops"]["ping"]["count"] == 1
    assert out["total_calls"] == 2


@pytest.mark.asyncio
async def test_perf_stats_tool_respects_op_filter(monkeypatch):
    monkeypatch.setattr(server, "_policy", Policy.load(None))
    perf.record("ping", 1.0, True)
    perf.record("query", 2.0, True)
    out = await server.perf_stats(op="ping")
    assert set(out["ops"]) == {"ping"}


# ---------------------------------------------------------------------------
# Verbose mode actually measures payload sizes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verbose_mode_records_payload_sizes(monkeypatch):
    perf.set_verbose(True)
    try:
        class _StubBL:
            async def call(self, op, args, timeout=30.0, dry_run=False):
                return {"hello": "world", "list": [1, 2, 3]}

        monkeypatch.setattr(server, "_bl", _StubBL())
        monkeypatch.setattr(server, "_get_client", lambda: server._bl)

        await server._call("ping", {"x": 1})
        _, _, _, _, in_b, out_b = perf.snapshot()[0]
        assert in_b > 0
        assert out_b > 0
    finally:
        perf.set_verbose(perf._verbose_from_env())


@pytest.mark.asyncio
async def test_non_verbose_mode_skips_payload_measurement(monkeypatch):
    perf.set_verbose(False)

    class _StubBL:
        async def call(self, op, args, timeout=30.0, dry_run=False):
            return {"big": "x" * 10_000}

    monkeypatch.setattr(server, "_bl", _StubBL())
    monkeypatch.setattr(server, "_get_client", lambda: server._bl)

    await server._call("ping", {"x": 1})
    _, _, _, _, in_b, out_b = perf.snapshot()[0]
    assert in_b == 0
    assert out_b == 0
