"""Pytest benchmarks — server-side hot path through a stub WS client.

Run with:
    uv run pytest -m bench --benchmark-only

These benchmarks **bypass the WebSocket layer** by monkey-patching
``server._get_client`` to return an in-process stub. That measures only what
the MCP server itself contributes — `_proxy` plumbing, JSON-shaping,
policy gates, perf recording — which is what changes when we tune the
server. WS-layer benchmarks (round-trip latency through ``BlenderWS``)
belong in a separate suite if/when we touch that layer.

Each benchmark uses ``benchmark.pedantic`` with ``rounds=200, iterations=1``
so we get a tight distribution without pytest-benchmark's default warmup
swallowing the result.

Baseline JSON: re-record with
    uv run pytest -m bench --benchmark-only --benchmark-save=baseline
and compare with
    uv run pytest -m bench --benchmark-only --benchmark-compare=baseline
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from blender_mcp import perf, server
from blender_mcp.policy import Policy

pytestmark = pytest.mark.bench


# ---------------------------------------------------------------------------
# Canned responses — match the shapes from tests/conftest.py FakeBlenderServer.
# Kept tiny to isolate server-side cost from response-size effects.
# ---------------------------------------------------------------------------


_CANNED: dict[str, Any] = {
    "ping": "pong",
    "scene.context": {
        "scene": "Scene", "frame": 1, "active_camera": "Camera",
        "active_object": "Cube", "blender_version": "4.2.0",
        "units": "METRIC", "render_engine": "CYCLES",
        "counts": {"objects": 3, "materials": 1},
    },
    "query": {
        "$rna": "Object", "name": "Cube", "location": [0.0, 0.0, 0.0],
    },
    "list": [{"name": "Cube", "type": "MESH"}],
    "bbox_info": {
        "min": [-1, -1, -1], "max": [1, 1, 1],
        "size": [2, 2, 2], "center": [0, 0, 0],
    },
    "object.transform": {
        "name": "Cube", "location": [1, 2, 3],
        "rotation_euler": [0, 0, 0], "scale": [1, 1, 1],
    },
    "mesh.create_primitive": {
        "name": "Cube", "kind": "cube", "polys": 6, "vertices": 8,
        "location": [0, 0, 0],
    },
    "render.viewport_screenshot": {
        "image_base64": "iVBORw0KGgo=", "mime": "image/png",
        "width": 1024, "height": 1024, "size_bytes": 0,
    },
    "build_nodes": {
        "target": "material:M", "tree": "fake", "node_count": 2,
        "link_count": 1, "created": ["bsdf", "out"], "skipped_properties": [],
        "links": [],
    },
}


class _StubBL:
    """Replaces BlenderWS — returns canned responses with zero latency."""

    async def call(
        self, op: str, args: dict[str, Any] | None = None,
        timeout: float = 30.0, dry_run: bool = False,
    ) -> Any:
        return _CANNED[op]


@pytest.fixture(autouse=True)
def _stub_client(monkeypatch):
    """Bypass the WS layer for every benchmark in this module."""
    stub = _StubBL()
    monkeypatch.setattr(server, "_bl", stub)
    monkeypatch.setattr(server, "_get_client", lambda: stub)
    # Use a permissive policy: no allowlist, very high rate limit, so 200
    # rapid-fire iterations of mutating ops aren't capped by the token bucket.
    pol = Policy.load(None)
    pol.rate_limit = {"mutating_ops_per_window": 1_000_000, "window_seconds": 1.0}
    pol._rate_limiter = None  # noqa  -- legacy attr
    pol._bucket = None  # force re-creation with the new cap
    monkeypatch.setattr(server, "_policy", pol)
    perf.reset()
    yield
    perf.reset()


def _run(coro_factory):
    """Run an async coroutine to completion on a fresh event loop.

    A fresh loop per call avoids pytest-asyncio interference and makes
    the per-iteration cost roughly constant (~50µs loop overhead, fixed
    across baseline + comparison so the delta stays meaningful).
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Hot-path benchmarks — 8 ops chosen by the codebase map as most-used
# ---------------------------------------------------------------------------


def test_bench_ping(benchmark):
    benchmark.pedantic(_run, args=(server.ping,), rounds=200, iterations=1)


def test_bench_query(benchmark):
    benchmark.pedantic(
        _run, args=(lambda: server.query(target="object:Cube"),),
        rounds=200, iterations=1,
    )


def test_bench_list(benchmark):
    benchmark.pedantic(
        _run, args=(lambda: server.list_(kind="objects"),),
        rounds=200, iterations=1,
    )


def test_bench_bbox_info(benchmark):
    benchmark.pedantic(
        _run, args=(lambda: server.bbox_info(object="Cube"),),
        rounds=200, iterations=1,
    )


def test_bench_set_transform(benchmark):
    benchmark.pedantic(
        _run,
        args=(lambda: server.set_transform(object="Cube", location=[1, 2, 3]),),
        rounds=200, iterations=1,
    )


def test_bench_create_primitive(benchmark):
    benchmark.pedantic(
        _run,
        args=(lambda: server.create_primitive(kind="cube", name="Cube"),),
        rounds=200, iterations=1,
    )


def test_bench_viewport_screenshot(benchmark):
    benchmark.pedantic(
        _run,
        args=(lambda: server.viewport_screenshot(width=1024, height=1024),),
        rounds=200, iterations=1,
    )


def test_bench_build_nodes(benchmark):
    graph = {
        "nodes": [
            {"name": "bsdf", "type": "ShaderNodeBsdfPrincipled"},
            {"name": "out", "type": "ShaderNodeOutputMaterial"},
        ],
        "links": [{"from": "bsdf.BSDF", "to": "out.Surface"}],
    }
    benchmark.pedantic(
        _run,
        args=(lambda: server.build_nodes(target="material:M", graph=graph),),
        rounds=200, iterations=1,
    )


# ---------------------------------------------------------------------------
# Overhead micro-benchmark — measure perf.record() in isolation
# ---------------------------------------------------------------------------


def test_bench_perf_record_overhead(benchmark):
    """Sanity: perf.record() must stay ≤10µs per call (always-on cost)."""
    perf.set_verbose(False)

    def _one():
        for _ in range(1000):
            perf.record("ping", 1.5, True)

    benchmark.pedantic(_one, rounds=20, iterations=1)
