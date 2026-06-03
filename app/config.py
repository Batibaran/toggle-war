"""Runtime configuration from environment variables."""

from __future__ import annotations

import os

DEFAULT_STATS_TICK_SEC = 0.1
DEFAULT_PERSIST_INTERVAL_SEC = 5.0
DEFAULT_BUCKET_CAPACITY = 15
DEFAULT_BUCKET_REFILL_RATE = 3.0
DEFAULT_MAX_CONNS_PER_IP = 5
DEFAULT_IP_BUCKET_CAPACITY = 20
DEFAULT_IP_BUCKET_REFILL_RATE = 10.0
DEFAULT_BOT_BAN_THRESHOLD = 5
DEFAULT_BOT_MIN_REACTION_MS = 100
DEFAULT_BOT_SPAM_SPACING_MS = 150


def _positive_float(name: str, default: float) -> float:
    """
    Read a positive float from the environment.

    Args:
        name: Environment variable name
        default: Value when unset or empty

    Returns:
        Parsed positive float

    Raises:
        ValueError: If the value is not a positive number
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {raw!r}")
    return value


def _positive_int(name: str, default: int) -> int:
    """
    Read a positive integer from the environment.

    Args:
        name: Environment variable name
        default: Value when unset or empty

    Returns:
        Parsed positive int

    Raises:
        ValueError: If the value is not a positive integer
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {raw!r}")
    return value


STATS_TICK_SEC = _positive_float("STATS_TICK_SEC", DEFAULT_STATS_TICK_SEC)
PERSIST_INTERVAL_SEC = _positive_float(
    "PERSIST_INTERVAL_SEC", DEFAULT_PERSIST_INTERVAL_SEC
)
BUCKET_CAPACITY = _positive_int("BUCKET_CAPACITY", DEFAULT_BUCKET_CAPACITY)
BUCKET_REFILL_RATE = _positive_float(
    "BUCKET_REFILL_RATE", DEFAULT_BUCKET_REFILL_RATE
)
MAX_CONNS_PER_IP = _positive_int("MAX_CONNS_PER_IP", DEFAULT_MAX_CONNS_PER_IP)
IP_BUCKET_CAPACITY = _positive_int(
    "IP_BUCKET_CAPACITY", DEFAULT_IP_BUCKET_CAPACITY
)
IP_BUCKET_REFILL_RATE = _positive_float(
    "IP_BUCKET_REFILL_RATE", DEFAULT_IP_BUCKET_REFILL_RATE
)
BOT_BAN_THRESHOLD = _positive_int("BOT_BAN_THRESHOLD", DEFAULT_BOT_BAN_THRESHOLD)
BOT_MIN_REACTION_MS = _positive_int(
    "BOT_MIN_REACTION_MS", DEFAULT_BOT_MIN_REACTION_MS
)
BOT_SPAM_SPACING_MS = _positive_int(
    "BOT_SPAM_SPACING_MS", DEFAULT_BOT_SPAM_SPACING_MS
)


