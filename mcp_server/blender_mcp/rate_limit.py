"""Token-bucket rate limiter for the MCP server.

Throttles mutating tool calls so a runaway model can't flood the Blender
add-on with thousands of edits per second. Read-only tools (ping, query,
list_*, etc.) are not rate-limited.

The limiter is a simple monotonic-clock token bucket with a configurable
refill window. It is process-local — adequate because the MCP server is
spawned per-VS-Code-instance.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock


class RateLimitExceeded(Exception):
    """Raised (or returned as an error dict by the server) when the bucket is empty."""

    def __init__(self, tool: str, capacity: int, window_seconds: float, retry_after: float):
        super().__init__(
            f"Rate limit exceeded for '{tool}': "
            f"max {capacity} mutating ops per {window_seconds:.1f}s. "
            f"Retry after ~{retry_after:.2f}s."
        )
        self.tool = tool
        self.capacity = capacity
        self.window_seconds = window_seconds
        self.retry_after = retry_after


@dataclass
class TokenBucket:
    """A standard token bucket: `capacity` tokens, refilling over `window_seconds`."""

    capacity: int
    window_seconds: float
    _tokens: float = 0.0
    _last_refill: float = 0.0
    _lock: Lock = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()
        self._lock = Lock()

    @property
    def refill_rate(self) -> float:
        """Tokens per second."""
        if self.window_seconds <= 0:
            return 0.0
        return self.capacity / self.window_seconds

    def take(self, tokens: int = 1) -> tuple[bool, float]:
        """Try to consume `tokens`. Returns (allowed, retry_after_seconds)."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            if elapsed > 0 and self.refill_rate > 0:
                self._tokens = min(
                    float(self.capacity), self._tokens + elapsed * self.refill_rate
                )
                self._last_refill = now
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True, 0.0
            shortfall = tokens - self._tokens
            retry_after = shortfall / self.refill_rate if self.refill_rate > 0 else float("inf")
            return False, retry_after

    def reset(self) -> None:
        """Refill the bucket to full capacity (for tests)."""
        with self._lock:
            self._tokens = float(self.capacity)
            self._last_refill = time.monotonic()
