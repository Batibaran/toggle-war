"""Runtime configuration from environment variables."""

from __future__ import annotations

import os

DEFAULT_STATS_TICK_SEC = 0.1
DEFAULT_PERSIST_INTERVAL_SEC = 5.0


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


STATS_TICK_SEC = _positive_float("STATS_TICK_SEC", DEFAULT_STATS_TICK_SEC)
PERSIST_INTERVAL_SEC = _positive_float(
    "PERSIST_INTERVAL_SEC", DEFAULT_PERSIST_INTERVAL_SEC
)
