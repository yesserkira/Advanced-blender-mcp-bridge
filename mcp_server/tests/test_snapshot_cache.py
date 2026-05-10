"""Phase 3 — SnapshotCache unit + server-integration tests.

Two layers:
1. Pure SnapshotCache: TTL expiry, epoch invalidation, error skip, key shape.
2. Server integration: read-only ops coalesce, mutating ops bump epoch,
   ``scene.changed`` notification bumps epoch, dry-run does NOT bump.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from blender_mcp import server
from blender_mcp.policy import Policy
from blender_mcp.snapshot_cache import SnapshotCache


# ---------------------------------------------------------------------------
# Pure SnapshotCache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_call_caches_within_ttl():
    cache = SnapshotCache(ttl_ms=100)
    calls = 0

    async def fetcher() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"v": calls}

    out1 = await cache.get_or_call("ping", None, fetcher)
    out2 = await cache.get_or_call("ping", None, fetcher)
    assert out1 == out2 == {"v": 1}
    assert cache.hits == 1
    assert cache.misses == 1


@pytest.mark.asyncio
async def test_get_or_call_expires_after_ttl():
    cache = SnapshotCache(ttl_ms=20)
    calls = 0

    async def fetcher() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"v": calls}

    await cache.get_or_call("ping", None, fetcher)
    await asyncio.sleep(0.05)  # past TTL
    out = await cache.get_or_call("ping", None, fetcher)
    assert out == {"v": 2}
    assert cache.misses == 2


@pytest.mark.asyncio
async def test_bump_epoch_invalidates_all():
    cache = SnapshotCache(ttl_ms=10_000)
    calls = 0

    async def fetcher() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"v": calls}

    await cache.get_or_call("ping", None, fetcher)
    cache.bump_epoch()
    out = await cache.get_or_call("ping", None, fetcher)
    assert out == {"v": 2}


@pytest.mark.asyncio
async def test_get_or_call_skips_caching_on_error():
    cache = SnapshotCache(ttl_ms=10_000)
    calls = 0

    async def fetcher() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"error": "BOOM", "message": "x"}

    await cache.get_or_call("ping", None, fetcher)
    out = await cache.get_or_call("ping", None, fetcher)
    # Both calls hit fetcher — error envelopes are NOT cached.
    assert calls == 2
    assert out == {"error": "BOOM", "message": "x"}


@pytest.mark.asyncio
async def test_get_or_call_disabled_when_ttl_zero():
    cache = SnapshotCache(ttl_ms=0)
    calls = 0

    async def fetcher() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"v": calls}

    await cache.get_or_call("ping", None, fetcher)
    await cache.get_or_call("ping", None, fetcher)
    assert calls == 2  # cache disabled, every call hits fetcher
    # Counters are not bumped on the bypass path — keep them at zero so
    # operators can clearly see "ttl=0 means no caching".
    assert cache.hits == 0
    assert cache.misses == 0


@pytest.mark.asyncio
async def test_args_are_part_of_cache_key():
    cache = SnapshotCache(ttl_ms=10_000)
    calls = 0

    async def fetcher() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"v": calls}

    await cache.get_or_call("query", {"name": "Cube"}, fetcher)
    await cache.get_or_call("query", {"name": "Sphere"}, fetcher)
    # Different args = different keys = two fetches.
    assert calls == 2


def test_args_key_is_dict_order_independent():
    cache = SnapshotCache(ttl_ms=10_000)
    k1 = cache._key("op", {"a": 1, "b": 2})
    k2 = cache._key("op", {"b": 2, "a": 1})
    assert k1 == k2


def test_stats_shape():
    cache = SnapshotCache(ttl_ms=200)
    s = cache.stats()
    for field in ("ttl_ms", "epoch", "size", "hits", "misses",
                  "invalidations", "hit_rate"):
        assert field in s


def test_ttl_from_env(monkeypatch):
    from blender_mcp import snapshot_cache

    monkeypatch.setenv("BLENDER_MCP_SNAPSHOT_TTL_MS", "500")
    assert snapshot_cache._ttl_from_env() == 500

    monkeypatch.setenv("BLENDER_MCP_SNAPSHOT_TTL_MS", "garbage")
    assert snapshot_cache._ttl_from_env() == snapshot_cache.DEFAULT_TTL_MS

    monkeypatch.delenv("BLENDER_MCP_SNAPSHOT_TTL_MS", raising=False)
    assert snapshot_cache._ttl_from_env() == snapshot_cache.DEFAULT_TTL_MS


# ---------------------------------------------------------------------------
# Server integration
# ---------------------------------------------------------------------------


class _CountingStubBL:
    """Counts WS calls per op so we can assert coalescing behaviour."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    async def call(self, op, args=None, timeout=30.0, dry_run=False):
        self.calls[op] = self.calls.get(op, 0) + 1
        # Return shapes vary; the cache only inspects "error" key.
        if op == "scene.context":
            return {"scene": "Scene", "blender_version": "4.2.0"}
        return {"name": "X"}


@pytest.fixture
def stubbed_server(monkeypatch):
    stub = _CountingStubBL()
    monkeypatch.setattr(server, "_bl", stub)
    monkeypatch.setattr(server, "_get_client", lambda: stub)
    monkeypatch.setattr(server, "_policy", Policy.load(None))
    server._snapshot_cache.clear()
    yield stub
    server._snapshot_cache.clear()


@pytest.mark.asyncio
async def test_repeated_pings_coalesce(stubbed_server):
    # 10 sequential pings within the TTL → exactly 1 underlying scene.context.
    for _ in range(10):
        await server.ping()
    assert stubbed_server.calls.get("scene.context") == 1


@pytest.mark.asyncio
async def test_mutation_bumps_epoch_and_invalidates(stubbed_server, monkeypatch):
    # Warm cache
    await server.ping()
    epoch_before = server._snapshot_cache.epoch
    # Any mutating tool: trigger a non-cached, non-readonly op via _call.
    await server._call("set_transform", {"name": "Cube", "location": [1, 0, 0]})
    epoch_after = server._snapshot_cache.epoch
    assert epoch_after == epoch_before + 1
    # Next ping re-fetches.
    await server.ping()
    assert stubbed_server.calls.get("scene.context") == 2


@pytest.mark.asyncio
async def test_dry_run_mutation_does_not_bump_epoch(stubbed_server):
    await server.ping()
    epoch_before = server._snapshot_cache.epoch
    await server._call(
        "set_transform", {"name": "Cube"}, dry_run=True,
    )
    assert server._snapshot_cache.epoch == epoch_before
    # And ping is still cached.
    await server.ping()
    assert stubbed_server.calls.get("scene.context") == 1


@pytest.mark.asyncio
async def test_scene_changed_notification_bumps_epoch(stubbed_server):
    await server.ping()
    assert stubbed_server.calls.get("scene.context") == 1
    epoch_before = server._snapshot_cache.epoch

    await server._on_blender_notification({
        "event": "scene.changed",
        "uri": "blender://scene/current",
        "hash": "newhash",
    })
    assert server._snapshot_cache.epoch == epoch_before + 1

    await server.ping()
    assert stubbed_server.calls.get("scene.context") == 2


@pytest.mark.asyncio
async def test_unrelated_notification_does_not_bump(stubbed_server):
    await server.ping()
    epoch_before = server._snapshot_cache.epoch
    await server._on_blender_notification({"event": "something_else"})
    assert server._snapshot_cache.epoch == epoch_before


@pytest.mark.asyncio
async def test_error_response_not_cached(stubbed_server, monkeypatch):
    """Calling a cacheable op that errors does NOT poison the cache."""
    from blender_mcp.blender_client import BlenderError

    class _ErrorThenOK:
        def __init__(self):
            self.n = 0

        async def call(self, op, args=None, timeout=30.0, dry_run=False):
            self.n += 1
            if self.n == 1:
                raise BlenderError("BOOM", "first call fails")
            return {"scene": "Scene", "blender_version": "4.2.0"}

    err_stub = _ErrorThenOK()
    monkeypatch.setattr(server, "_bl", err_stub)
    monkeypatch.setattr(server, "_get_client", lambda: err_stub)

    out1 = await server.ping()
    assert out1.get("status") in ("connected", "error") or "error" in out1
    await server.ping()
    # Trace:
    #   call 1 → scene.context (n=1, BOOM) → error not cached → ping fallback (n=2)
    #   call 2 → scene.context (n=3, OK)   → cached for next time
    # Total = 3. The contract being tested: a cacheable op that errors does
    # NOT get its error envelope cached, so a subsequent call retries.
    assert err_stub.n == 3


@pytest.mark.asyncio
async def test_perf_stats_surfaces_snapshot_cache(stubbed_server):
    # Fire two pings to generate a hit, then read stats.
    await server.ping()
    await server.ping()
    out = await server.perf_stats()
    assert "snapshot_cache" in out
    s = out["snapshot_cache"]
    assert s["hits"] >= 1
    assert s["ttl_ms"] > 0
