"""Per-session token bucket rate limiter."""

from __future__ import annotations

import time


class TokenBucket:
    """
    Classic token bucket: starts full, drains on consume, refills over time.

    Attributes:
        capacity: Maximum tokens the bucket can hold.
        refill_rate: Tokens added per second.
    """

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._tokens: float = float(capacity)
        self._last_refill: float = time.monotonic()

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now

    def consume(self) -> bool:
        """
        Try to consume one token.

        Returns:
            True if a token was available and consumed, False if rate-limited.
        """
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False
