"""FastAPI entry: WebSocket sync, persistence, static UI."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import auth, db
from app.config import (
    BOT_BAN_THRESHOLD,
    BOT_MIN_REACTION_MS,
    BOT_SPAM_SPACING_MS,
    BUCKET_CAPACITY,
    BUCKET_REFILL_RATE,
    IP_BUCKET_CAPACITY,
    IP_BUCKET_REFILL_RATE,
    MAX_CONNS_PER_IP,
    PERSIST_INTERVAL_SEC,
    STATS_TICK_SEC,
)
from app.rate_limit import IPTracker, TokenBucket
from app.state import AppState, now_wall_ms
from app.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

state_lock = asyncio.Lock()
app_state = AppState.fresh()
manager = ConnectionManager()

# Global chat: in-memory only, never persisted. A fixed-size ring buffer caps
# memory regardless of uptime; new clients receive these as scrollback. Each
# entry is {"username", "text", "ts"}.
CHAT_HISTORY_SIZE = 200
CHAT_MAX_LEN = 280
chat_history: deque[dict] = deque(maxlen=CHAT_HISTORY_SIZE)
ip_tracker = IPTracker(
    MAX_CONNS_PER_IP,
    IP_BUCKET_CAPACITY,
    IP_BUCKET_REFILL_RATE,
    BOT_BAN_THRESHOLD,
    BOT_MIN_REACTION_MS,
    BOT_SPAM_SPACING_MS,
)


async def persist_state() -> None:
    """
    Write committed state to SQLite.

    Returns:
        None
    """
    fields = app_state.persist_fields()
    await db.save_state_row(*fields)


async def broadcast_state() -> None:
    """
    Push current snapshot to all WebSocket clients.

    Returns:
        None
    """
    async with state_lock:
        payload = app_state.snapshot()
    await manager.broadcast(payload)


async def periodic_persist_loop() -> None:
    """
    Checkpoint committed state on PERSIST_INTERVAL_SEC.

    Returns:
        None
    """
    while True:
        await asyncio.sleep(PERSIST_INTERVAL_SEC)
        async with state_lock:
            await persist_state()


async def stats_tick_loop() -> None:
    """
    Broadcast live totals on STATS_TICK_SEC for smooth UI counters.

    Returns:
        None
    """
    while True:
        await asyncio.sleep(STATS_TICK_SEC)
        if manager.connection_count:
            await broadcast_state()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Load DB on startup; run background persist and stats tasks.

    Yields:
        Control to the running application
    """
    global app_state
    logger.info(
        "Intervals: STATS_TICK_SEC=%s PERSIST_INTERVAL_SEC=%s"
        " | Bucket: capacity=%s refill_rate=%s/s"
        " | IP: max_conns=%s agg_capacity=%s agg_rate=%s/s",
        STATS_TICK_SEC,
        PERSIST_INTERVAL_SEC,
        BUCKET_CAPACITY,
        BUCKET_REFILL_RATE,
        MAX_CONNS_PER_IP,
        IP_BUCKET_CAPACITY,
        IP_BUCKET_REFILL_RATE,
    )
    await db.init_db()
    banned = await db.load_banned_ips()
    ip_tracker.set_banned_ips(banned)
    logger.info("Loaded %d banned IPs.", len(banned))
    row = await db.load_state_row()
    async with state_lock:
        if row is None:
            app_state = AppState.fresh()
            await persist_state()
        else:
            # Credit last toggler for wall time elapsed since last persist
            # (covers both clean shutdown and crash recovery).
            last_toggler = row.get("last_toggler_user_id")
            if last_toggler is not None:
                extra_wall = max(0, now_wall_ms() - int(row["segment_started_wall_ms"]))
                if extra_wall > 0:
                    await db.credit_active_time(int(last_toggler), int(row["value"]), extra_wall)
            app_state = AppState.from_row(row)

    persist_task = asyncio.create_task(periodic_persist_loop())
    tick_task = asyncio.create_task(stats_tick_loop())
    try:
        yield
    finally:
        persist_task.cancel()
        tick_task.cancel()
        async with state_lock:
            await persist_state()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    Handle toggle commands and stream authoritative state.

    Enforces per-IP connection cap (Layer 2) and per-IP aggregate
    rate limit (Layer 3) on top of per-session token bucket (Layer 1).

    Args:
        websocket: Client WebSocket

    Returns:
        None
    """
    client_ip = websocket.client.host if websocket.client else "unknown"

    if not ip_tracker.try_connect(client_ip):
        logger.info("Rejected connection from %s (IP cap reached)", client_ip)
        await websocket.close(code=1008, reason="Too many connections")
        return

    # Optional identity: a stale/invalid token resolves to None and the
    # socket simply plays anonymously — it never blocks play.
    user = await resolve_token(websocket.query_params.get("token"))
    user_id = user["id"] if user else None

    # Dedup tabs/devices: logged-in users collapse by id, anonymous by IP.
    identity = f"user:{user_id}" if user_id is not None else f"ip:{client_ip}"
    await manager.connect(websocket, identity)
    bucket = TokenBucket(BUCKET_CAPACITY, BUCKET_REFILL_RATE)
    # Separate budget for chat: ~1 msg/sec sustained, burst of 5.
    chat_bucket = TokenBucket(5, 1.0)
    try:
        async with state_lock:
            snapshot = app_state.snapshot()
        await manager.send_snapshot(websocket, snapshot)

        user_stats = await db.get_user_stats(user_id) if user_id is not None else None
        if user_stats is not None:
            await manager.send_snapshot(websocket, _stats_payload(user_stats))

        await manager.send_snapshot(
            websocket, {"type": "chat_history", "messages": list(chat_history)}
        )

        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = message.get("type")

            if msg_type == "chat":
                if user_id is None:
                    await websocket.send_text(
                        json.dumps({"type": "chat_error", "error": "Log in to chat."})
                    )
                    continue
                text = (message.get("text") or "").strip()
                if not text:
                    continue
                if not chat_bucket.consume():
                    await websocket.send_text(
                        json.dumps({"type": "chat_error", "error": "Slow down."})
                    )
                    continue
                entry = {
                    "username": user["username"],
                    "text": text[:CHAT_MAX_LEN],
                    "ts": _now_iso(),
                }
                chat_history.append(entry)
                await manager.broadcast_event({"type": "chat", **entry})
                continue

            if msg_type != "toggle":
                continue

            if not bucket.consume() or not ip_tracker.consume(client_ip):
                logger.debug("Rate-limited toggle from %s", client_ip)
                await websocket.send_text(json.dumps({"type": "rate_limited"}))
                continue

            async with state_lock:
                state_elapsed = app_state.segment_elapsed_ms()
                prev_toggler = app_state.last_toggler_user_id
                prev_color = app_state.value
                app_state.toggle()
                app_state.last_toggler_user_id = user_id
                await persist_state()
                new_value = app_state.value
                if user_id is not None:
                    await db.increment_user_toggle(user_id, new_value)
                if prev_toggler is not None and state_elapsed > 0:
                    await db.credit_active_time(prev_toggler, prev_color, state_elapsed)
                snapshot = app_state.snapshot()

            await manager.broadcast(snapshot)

            if user_stats is not None:
                user_stats = await db.get_user_stats(user_id)
                await manager.send_snapshot(websocket, _stats_payload(user_stats))

            if prev_toggler is not None and state_elapsed > 0 and prev_toggler != user_id:
                prev_stats = await db.get_user_stats(prev_toggler)
                if prev_stats:
                    payload = _stats_payload(prev_stats)
                    for ws, ident in manager._connections.items():
                        if ident == f"user:{prev_toggler}":
                            asyncio.create_task(manager.send_snapshot(ws, payload))

            if ip_tracker.record_toggle(client_ip, state_elapsed):
                logger.warning("Banning IP %s due to reactive bot detection", client_ip)
                await db.ban_ip(client_ip, "Automated reactive bot behavior")
                await manager.disconnect_ip(client_ip)
                break
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        ip_tracker.disconnect(client_ip)
    except Exception:
        manager.disconnect(websocket)
        ip_tracker.disconnect(client_ip)
        raise


# --- Auth: helpers, request models, and HTTP endpoints ---

LEADERBOARD_LIMIT = 10


def _now_iso() -> str:
    """Current UTC time in the same ISO format used for persisted timestamps."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _expiry_iso(days: int) -> str:
    """ISO UTC timestamp `days` in the future, for session expiry."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + days * 86400))


def _bearer(header: str | None) -> str | None:
    """Extract the token from an `Authorization: Bearer <token>` header."""
    if not header:
        return None
    parts = header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def _stats_payload(stats: dict) -> dict:
    """Shape user stat columns into a `user_stats` message body."""
    return {
        "type": "user_stats",
        "toggle_count": stats["toggle_count"],
        "toggles_to_red": stats["toggles_to_red"],
        "toggles_to_blue": stats["toggles_to_blue"],
        "member_since": stats["created_at_wall"],
        "last_active": stats["last_toggle_at_wall"],
        "active_time_ms": stats.get("active_time_ms", 0),
        "active_time_red_ms": stats.get("active_time_red_ms", 0),
        "active_time_blue_ms": stats.get("active_time_blue_ms", 0),
    }


async def resolve_token(token: str | None) -> dict | None:
    """
    Resolve a session token to its user row.

    Expired sessions are deleted opportunistically. Returns None for a
    missing, unknown, or expired token (callers treat this as anonymous).

    Args:
        token: Opaque session token, or None

    Returns:
        User row dict, or None.
    """
    if not token:
        return None
    session = await db.get_session(token)
    if session is None:
        return None
    if session["expires_at_wall"] <= _now_iso():
        await db.delete_session(token)
        return None
    return await db.get_user_by_id(session["user_id"])


class AuthReq(BaseModel):
    """Register/login request body."""

    username: str
    password: str


@app.post("/api/register")
async def register(req: AuthReq) -> Response:
    """Create an account and auto-login, returning a session token."""
    err = auth.validate_username(req.username) or auth.validate_password(req.password)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    username = req.username.strip()
    canon = auth.canon_username(username)
    password_hash = auth.hash_password(req.password)
    user_id = await db.create_user(username, canon, password_hash)
    if user_id is None:
        return JSONResponse({"error": "username taken"}, status_code=409)
    token = auth.new_token()
    await db.create_session(token, user_id, _expiry_iso(auth.TOKEN_TTL_DAYS))
    stats = await db.get_user_stats(user_id)
    return JSONResponse(
        {"token": token, "username": username, "stats": _stats_payload(stats)}
    )


@app.post("/api/login")
async def login(req: AuthReq) -> Response:
    """Verify credentials and return a fresh session token."""
    canon = auth.canon_username(req.username)
    user = await db.get_user_by_canon(canon)
    if user is None or not auth.verify_password(req.password, user["password_hash"]):
        return JSONResponse({"error": "invalid credentials"}, status_code=401)
    token = auth.new_token()
    await db.create_session(token, user["id"], _expiry_iso(auth.TOKEN_TTL_DAYS))
    stats = await db.get_user_stats(user["id"])
    return JSONResponse(
        {"token": token, "username": user["username"], "stats": _stats_payload(stats)}
    )


@app.post("/api/logout")
async def logout(authorization: str | None = Header(default=None)) -> Response:
    """Invalidate a session token. Idempotent."""
    token = _bearer(authorization)
    if token:
        await db.delete_session(token)
    return Response(status_code=204)


@app.get("/api/me")
async def me(authorization: str | None = Header(default=None)) -> Response:
    """Return the current user's display name and stats, or 401."""
    user = await resolve_token(_bearer(authorization))
    if user is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    stats = await db.get_user_stats(user["id"])
    return JSONResponse({"username": user["username"], "stats": _stats_payload(stats)})


@app.get("/api/leaderboard")
async def leaderboard(authorization: str | None = Header(default=None)) -> Response:
    """
    Public top players for each metric (total / red / blue switches), plus
    the caller's own rank per metric when authenticated. Anonymous callers
    get the top lists with `you` = null.
    """
    user = await resolve_token(_bearer(authorization))
    boards: dict[str, dict] = {}
    for metric in db.LEADERBOARD_COLUMNS:
        top = await db.get_leaderboard(metric, LEADERBOARD_LIMIT)
        you = None
        if user is not None:
            rank = await db.get_user_rank(metric, user["id"])
            if rank is not None and rank["score"] > 0:
                you = {
                    "username": rank["username"],
                    "rank": rank["rank"],
                    "score": rank["score"],
                }
        boards[metric] = {"top": top, "you": you}
    return JSONResponse({"boards": boards})


@app.get("/")
async def index() -> FileResponse:
    """Serve the main UI."""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
