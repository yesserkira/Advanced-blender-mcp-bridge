"""Tests for the token-bucket rate limiter and policy integration."""

from __future__ import annotations

import time

import pytest

from blender_mcp.policy import (
    READ_ONLY_TOOLS,
    Policy,
    PolicyDenied,
    RateLimitDenied,
    is_mutating,
)
from blender_mcp.rate_limit import TokenBucket


# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------


def test_bucket_allows_up_to_capacity():
    b = TokenBucket(capacity=5, window_seconds=10.0)
    for _ in range(5):
        ok, _ = b.take(1)
        assert ok
    ok, retry = b.take(1)
    assert not ok
    assert retry > 0


def test_bucket_refills_over_time():
    b = TokenBucket(capacity=4, window_seconds=0.4)  # refill 10 tokens/s
    for _ in range(4):
        b.take(1)
    ok, _ = b.take(1)
    assert not ok
    time.sleep(0.25)  # ~2.5 tokens refilled
    ok, _ = b.take(1)
    assert ok
    ok, _ = b.take(1)
    assert ok


def test_bucket_capacity_cap():
    b = TokenBucket(capacity=3, window_seconds=0.1)
    time.sleep(0.5)  # would refill many tokens, but cap is 3
    for _ in range(3):
        ok, _ = b.take(1)
        assert ok
    ok, _ = b.take(1)
    assert not ok


def test_bucket_reset():
    b = TokenBucket(capacity=2, window_seconds=10.0)
    b.take(2)
    assert not b.take(1)[0]
    b.reset()
    assert b.take(1)[0]


# ---------------------------------------------------------------------------
# is_mutating / READ_ONLY_TOOLS
# ---------------------------------------------------------------------------


def test_read_only_tools_not_mutating():
    for name in READ_ONLY_TOOLS:
        assert not is_mutating(name), name


@pytest.mark.parametrize(
    "tool",
    ["create_objects", "delete_object", "transform", "execute_python", "transaction"],
)
def test_mutating_tools_are_mutating(tool: str):
    assert is_mutating(tool)


# ---------------------------------------------------------------------------
# Policy integration
# ---------------------------------------------------------------------------


def test_policy_rate_limits_mutating_tools():
    p = Policy({"rate_limit": {"mutating_ops_per_window": 3, "window_seconds": 10.0}})
    for _ in range(3):
        p.require("create_objects")
    with pytest.raises(RateLimitDenied) as exc:
        p.require("create_objects")
    assert exc.value.code == "RATE_LIMIT"
    assert exc.value.tool == "create_objects"
    assert exc.value.retry_after > 0


def test_policy_does_not_rate_limit_read_only():
    p = Policy({"rate_limit": {"mutating_ops_per_window": 2, "window_seconds": 10.0}})
    # Burn 100 read-only calls; bucket should be untouched.
    for _ in range(100):
        p.require("ping")
    # Still able to do `mutating_ops_per_window` mutating ops.
    for _ in range(2):
        p.require("create_objects")
    with pytest.raises(RateLimitDenied):
        p.require("create_objects")


def test_policy_legacy_rate_limit_key_accepted():
    p = Policy({"rate_limit": {"mutating_ops_per_10s": 2}})
    p.require("create_objects")
    p.require("create_objects")
    with pytest.raises(RateLimitDenied):
        p.require("create_objects")


def test_policy_denied_takes_precedence_over_rate_limit():
    p = Policy({"denied_tools": ["create_objects"]})
    with pytest.raises(PolicyDenied) as exc:
        p.require("create_objects")
    assert exc.value.code == "POLICY_DENIED"


def test_rate_limit_denied_is_policy_denied():
    """Existing _call() catches PolicyDenied; RateLimitDenied must inherit."""
    assert issubclass(RateLimitDenied, PolicyDenied)
