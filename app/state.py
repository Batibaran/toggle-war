"""Authoritative toggle state and timing logic."""

from __future__ import annotations

import time
from dataclasses import dataclass

RED = 0
BLUE = 1

COLOR_RED = "#c62828"
COLOR_BLUE = "#1565c0"


def now_mono_ms() -> float:
    """Monotonic time in milliseconds for segment duration."""
    return time.monotonic() * 1000.0


def now_wall_ms() -> int:
    """Wall-clock milliseconds for persistence across restarts."""
    return int(time.time() * 1000)


@dataclass
class AppState:
    """Shared bool and committed timing aggregates."""

    value: int
    total_red_ms: int
    total_blue_ms: int
    longest_red_ms: int
    longest_blue_ms: int
    segment_started_mono_ms: float
    segment_started_wall_ms: int

    @classmethod
    def fresh(cls) -> AppState:
        """
        Create default state (red, zero totals).

        Returns:
            New AppState instance
        """
        mono = now_mono_ms()
        wall = now_wall_ms()
        return cls(
            value=RED,
            total_red_ms=0,
            total_blue_ms=0,
            longest_red_ms=0,
            longest_blue_ms=0,
            segment_started_mono_ms=mono,
            segment_started_wall_ms=wall,
        )

    @classmethod
    def from_row(cls, row: dict) -> AppState:
        """
        Build state from DB row and reconcile wall time since last segment start.

        Args:
            row: Persisted app_state columns

        Returns:
            AppState with in-progress wall time folded into committed totals
        """
        wall_now = now_wall_ms()
        extra_wall = max(0, wall_now - int(row["segment_started_wall_ms"]))
        total_red = int(row["total_red_ms"])
        total_blue = int(row["total_blue_ms"])
        value = int(row["value"])
        if value == RED:
            total_red += extra_wall
        else:
            total_blue += extra_wall
        mono = now_mono_ms()
        return cls(
            value=value,
            total_red_ms=total_red,
            total_blue_ms=total_blue,
            longest_red_ms=int(row["longest_red_ms"]),
            longest_blue_ms=int(row["longest_blue_ms"]),
            segment_started_mono_ms=mono,
            segment_started_wall_ms=wall_now,
        )

    def segment_elapsed_ms(self) -> int:
        """
        Milliseconds in the current color stint (monotonic).

        Returns:
            Non-negative elapsed ms
        """
        return max(0, int(now_mono_ms() - self.segment_started_mono_ms))

    def toggle(self) -> None:
        """
        Close current segment, update totals/longest, flip color.

        Returns:
            None
        """
        elapsed = self.segment_elapsed_ms()
        if self.value == RED:
            self.total_red_ms += elapsed
            if elapsed > self.longest_red_ms:
                self.longest_red_ms = elapsed
            self.value = BLUE
        else:
            self.total_blue_ms += elapsed
            if elapsed > self.longest_blue_ms:
                self.longest_blue_ms = elapsed
            self.value = RED
        self.segment_started_mono_ms = now_mono_ms()
        self.segment_started_wall_ms = now_wall_ms()

    def snapshot(self) -> dict:
        """
        Build WebSocket payload with live display totals.

        Returns:
            JSON-serializable state dict
        """
        extra = self.segment_elapsed_ms()
        total_red = self.total_red_ms + (extra if self.value == RED else 0)
        total_blue = self.total_blue_ms + (extra if self.value == BLUE else 0)
        return {
            "type": "state",
            "value": self.value,
            "total_red_ms": total_red,
            "total_blue_ms": total_blue,
            "longest_red_ms": self.longest_red_ms,
            "longest_blue_ms": self.longest_blue_ms,
            "current_streak_ms": extra,
        }

    def persist_fields(self) -> tuple[int, int, int, int, int, int]:
        """
        Committed fields for SQLite (excludes in-progress segment).

        Returns:
            Tuple of value, totals, longest, segment_started_wall_ms
        """
        return (
            self.value,
            self.total_red_ms,
            self.total_blue_ms,
            self.longest_red_ms,
            self.longest_blue_ms,
            self.segment_started_wall_ms,
        )
