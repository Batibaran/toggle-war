"""Token bucket rate limiter and per-IP connection/rate tracking."""

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


class IPTracker:
    """
    Per-IP connection cap and aggregate toggle rate limit.

    Enforces two constraints:
    - At most *max_conns* concurrent WebSocket sessions per IP.
    - At most *agg_refill_rate* toggles/sec across all sessions from one IP,
      with a burst allowance of *agg_capacity*.

    Attributes:
        max_conns: Maximum concurrent connections per IP.
        agg_capacity: Aggregate token bucket capacity per IP.
        agg_refill_rate: Aggregate token refill rate (tokens/sec) per IP.
    """

    def __init__(
        self, max_conns: int, agg_capacity: int, agg_refill_rate: float
    ) -> None:
        self.max_conns = max_conns
        self.agg_capacity = agg_capacity
        self.agg_refill_rate = agg_refill_rate
        self._conn_counts: dict[str, int] = {}
        self._buckets: dict[str, TokenBucket] = {}

    def try_connect(self, ip: str) -> bool:
        """
        Try to register a new connection for *ip*.

        Args:
            ip: Client IP address.

        Returns:
            True if under the cap and registered, False if rejected.
        """
        count = self._conn_counts.get(ip, 0)
        if count >= self.max_conns:
            return False
        self._conn_counts[ip] = count + 1
        if ip not in self._buckets:
            self._buckets[ip] = TokenBucket(self.agg_capacity, self.agg_refill_rate)
        return True

    def disconnect(self, ip: str) -> None:
        """
        Unregister a connection for *ip*. Clean up when the last one leaves.

        Args:
            ip: Client IP address.
        """
        count = self._conn_counts.get(ip, 0)
        if count <= 1:
            self._conn_counts.pop(ip, None)
            self._buckets.pop(ip, None)
        else:
            self._conn_counts[ip] = count - 1

    def consume(self, ip: str) -> bool:
        """
        Try to consume one token from the IP's aggregate bucket.

        Args:
            ip: Client IP address.

        Returns:
            True if allowed, False if rate-limited.
        """
        bucket = self._buckets.get(ip)
        if bucket is None:
            return False
        return bucket.consume()

    @property
    def active_ips(self) -> int:
        """Number of IPs with at least one connection."""
        return len(self._conn_counts)

