"""Token bucket rate limiter and per-IP connection/rate tracking."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


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
    Per-IP connection cap, aggregate toggle rate limit, and bot detection.

    Enforces constraints:
    - At most *max_conns* concurrent WebSocket sessions per IP.
    - At most *agg_refill_rate* toggles/sec across all sessions from one IP.
    - Identifies reactive bots and maintains a set of banned IPs.
    """

    def __init__(
        self,
        max_conns: int,
        agg_capacity: int,
        agg_refill_rate: float,
        bot_ban_threshold: int = 5,
        bot_min_reaction_ms: float = 100.0,
        bot_spam_spacing_ms: float = 150.0,
    ) -> None:
        self.max_conns = max_conns
        self.agg_capacity = agg_capacity
        self.agg_refill_rate = agg_refill_rate
        self.bot_ban_threshold = bot_ban_threshold
        self.bot_min_reaction_ms = bot_min_reaction_ms
        self.bot_spam_spacing_ms = bot_spam_spacing_ms

        self._conn_counts: dict[str, int] = {}
        self._buckets: dict[str, TokenBucket] = {}
        self._bot_scores: dict[str, int] = {}
        self._last_toggles: dict[str, float] = {}
        self._banned_ips: set[str] = set()

    def try_connect(self, ip: str) -> bool:
        """
        Try to register a new connection for *ip*.

        Args:
            ip: Client IP address.

        Returns:
            True if under the cap and registered, False if rejected.
        """
        if ip in self._banned_ips:
            return False
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

    def set_banned_ips(self, banned: set[str]) -> None:
        """Initialize in-memory ban list."""
        self._banned_ips = set(banned)

    def ban_ip(self, ip: str) -> None:
        """Ban an IP in memory."""
        self._banned_ips.add(ip)

    def unban_ip(self, ip: str) -> None:
        """Unban an IP in memory and reset its bot score."""
        self._banned_ips.discard(ip)
        self._bot_scores.pop(ip, None)
        self._last_toggles.pop(ip, None)

    def record_toggle(self, ip: str, state_elapsed_ms: int) -> bool:
        """
        Record a successful toggle from an IP.
        Detects reactive bots based on reaction time and click spacing.

        Returns:
            True if the IP has been banned as a result of this toggle, False otherwise.
        """
        if ip in self._banned_ips:
            return True

        now = time.monotonic()
        last_toggle = self._last_toggles.get(ip)
        self._last_toggles[ip] = now

        # If we don't have a previous toggle, we can't calculate spacing.
        if last_toggle is None:
            return False

        client_elapsed_ms = (now - last_toggle) * 1000.0

        # Bot signature: reacted extremely quickly to a state change (< bot_min_reaction_ms)
        # but didn't trigger this via rapid spam clicking (spacing between their own clicks > bot_spam_spacing_ms).
        if state_elapsed_ms < self.bot_min_reaction_ms and client_elapsed_ms > self.bot_spam_spacing_ms:
            score = self._bot_scores.get(ip, 0) + 1
            self._bot_scores[ip] = score
            logger.warning(
                "Suspicious toggle from IP %s: state_elapsed=%sms, client_elapsed=%sms. Bot score: %s/%s",
                ip, state_elapsed_ms, int(client_elapsed_ms), score, self.bot_ban_threshold
            )
            if score >= self.bot_ban_threshold:
                self.ban_ip(ip)
                return True
        else:
            # Decay score on normal clicks
            score = self._bot_scores.get(ip, 0)
            if score > 0:
                self._bot_scores[ip] = score - 1

        return False


