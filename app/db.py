"""SQLite persistence for toggle state."""

from __future__ import annotations

import time
from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "toggle.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    value INTEGER NOT NULL,
    total_red_ms INTEGER NOT NULL,
    total_blue_ms INTEGER NOT NULL,
    longest_red_ms INTEGER NOT NULL,
    longest_blue_ms INTEGER NOT NULL,
    segment_started_wall_ms INTEGER NOT NULL,
    updated_at_wall TEXT NOT NULL
);
"""


def _now_wall_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def init_db() -> None:
    """
    Ensure data directory and schema exist.

    Returns:
        None
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def load_state_row() -> dict | None:
    """
    Load persisted state row.

    Returns:
        Column dict for id=1, or None if no row exists.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM app_state WHERE id = 1") as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def save_state_row(
    value: int,
    total_red_ms: int,
    total_blue_ms: int,
    longest_red_ms: int,
    longest_blue_ms: int,
    segment_started_wall_ms: int,
) -> None:
    """
    Upsert committed state to SQLite.

    Args:
        value: 0 red, 1 blue
        total_red_ms: Committed red milliseconds
        total_blue_ms: Committed blue milliseconds
        longest_red_ms: Longest red stint ms
        longest_blue_ms: Longest blue stint ms
        segment_started_wall_ms: Wall ms when current segment began

    Returns:
        None
    """
    updated_at = _now_wall_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO app_state (
                id, value, total_red_ms, total_blue_ms,
                longest_red_ms, longest_blue_ms,
                segment_started_wall_ms, updated_at_wall
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                value = excluded.value,
                total_red_ms = excluded.total_red_ms,
                total_blue_ms = excluded.total_blue_ms,
                longest_red_ms = excluded.longest_red_ms,
                longest_blue_ms = excluded.longest_blue_ms,
                segment_started_wall_ms = excluded.segment_started_wall_ms,
                updated_at_wall = excluded.updated_at_wall
            """,
            (
                value,
                total_red_ms,
                total_blue_ms,
                longest_red_ms,
                longest_blue_ms,
                segment_started_wall_ms,
                updated_at,
            ),
        )
        await db.commit()
