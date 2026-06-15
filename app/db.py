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

CREATE TABLE IF NOT EXISTS banned_ips (
    ip TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    banned_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    username_canon TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at_wall TEXT NOT NULL,
    toggle_count INTEGER NOT NULL DEFAULT 0,
    toggles_to_red INTEGER NOT NULL DEFAULT 0,
    toggles_to_blue INTEGER NOT NULL DEFAULT 0,
    last_toggle_at_wall TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at_wall TEXT NOT NULL,
    expires_at_wall TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_users_toggle_count ON users(toggle_count DESC);
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


async def load_banned_ips() -> set[str]:
    """Load set of banned IPs from DB."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT ip FROM banned_ips") as cursor:
            rows = await cursor.fetchall()
            return {row[0] for row in rows}


async def ban_ip(ip: str, reason: str) -> None:
    """Save an IP ban to the DB."""
    banned_at = _now_wall_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO banned_ips (ip, reason, banned_at) VALUES (?, ?, ?)",
            (ip, reason, banned_at),
        )
        await db.commit()


async def unban_ip(ip: str) -> None:
    """Remove an IP ban from the DB."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM banned_ips WHERE ip = ?", (ip,))
        await db.commit()


# --- Users & sessions ---

_STAT_COLUMNS = (
    "username",
    "created_at_wall",
    "toggle_count",
    "toggles_to_red",
    "toggles_to_blue",
    "last_toggle_at_wall",
)


async def create_user(
    username: str, username_canon: str, password_hash: str
) -> int | None:
    """
    Insert a new user.

    Args:
        username: Display username (original casing)
        username_canon: Canonical (lowercased) form used for uniqueness
        password_hash: bcrypt hash string

    Returns:
        New user id, or None if the canonical username already exists.
    """
    created_at = _now_wall_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cursor = await db.execute(
                """
                INSERT INTO users (username, username_canon, password_hash, created_at_wall)
                VALUES (?, ?, ?, ?)
                """,
                (username, username_canon, password_hash, created_at),
            )
            await db.commit()
            return cursor.lastrowid
        except aiosqlite.IntegrityError:
            return None


async def get_user_by_canon(username_canon: str) -> dict | None:
    """Load a user row by canonical username, or None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE username_canon = ?", (username_canon,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_user_by_id(user_id: int) -> dict | None:
    """Load a user row by id, or None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_user_stats(user_id: int) -> dict | None:
    """Return the displayable stat columns for a user, or None."""
    columns = ", ".join(_STAT_COLUMNS)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT {columns} FROM users WHERE id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def increment_user_toggle(user_id: int, new_value: int) -> None:
    """
    Increment a user's toggle counters after a successful toggle.

    Args:
        user_id: Target user
        new_value: Color just switched to (0 red, 1 blue)
    """
    to_red = 1 if new_value == 0 else 0
    to_blue = 1 if new_value == 1 else 0
    now = _now_wall_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE users SET
                toggle_count = toggle_count + 1,
                toggles_to_red = toggles_to_red + ?,
                toggles_to_blue = toggles_to_blue + ?,
                last_toggle_at_wall = ?
            WHERE id = ?
            """,
            (to_red, to_blue, now, user_id),
        )
        await db.commit()


# Maps a leaderboard metric key to its (trusted) column name. Used to build
# the ranking SQL; values are never derived from request input.
LEADERBOARD_COLUMNS = {
    "total": "toggle_count",
    "red": "toggles_to_red",
    "blue": "toggles_to_blue",
}


async def get_leaderboard(metric: str, limit: int) -> list[dict]:
    """
    Top players ranked by a chosen metric.

    Args:
        metric: One of LEADERBOARD_COLUMNS ("total", "red", "blue")
        limit: Maximum number of rows to return

    Returns:
        List of {username, score}, highest first. Players with a score of
        zero for this metric are excluded.
    """
    column = LEADERBOARD_COLUMNS[metric]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            SELECT username, {column} AS score FROM users
            WHERE {column} > 0
            ORDER BY {column} DESC, id ASC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_user_rank(metric: str, user_id: int) -> dict | None:
    """
    A single user's standing on one leaderboard.

    Args:
        metric: One of LEADERBOARD_COLUMNS ("total", "red", "blue")
        user_id: Target user

    Returns:
        {username, score, rank} (rank is 1-based, ties share the better
        rank), or None if the user does not exist.
    """
    column = LEADERBOARD_COLUMNS[metric]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            SELECT username, {column} AS score,
                   (SELECT COUNT(*) FROM users b WHERE b.{column} > a.{column}) + 1 AS rank
            FROM users a WHERE a.id = ?
            """,
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def create_session(token: str, user_id: int, expires_at_wall: str) -> None:
    """Persist a new session token for a user."""
    created_at = _now_wall_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO sessions (token, user_id, created_at_wall, expires_at_wall)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, created_at, expires_at_wall),
        )
        await db.commit()


async def get_session(token: str) -> dict | None:
    """Load a session row by token, or None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM sessions WHERE token = ?", (token,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def delete_session(token: str) -> None:
    """Delete a session token (logout / expiry cleanup)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        await db.commit()
