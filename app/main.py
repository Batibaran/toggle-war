"""FastAPI entry: WebSocket sync, persistence, static UI."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.config import (
    BUCKET_CAPACITY,
    BUCKET_REFILL_RATE,
    PERSIST_INTERVAL_SEC,
    STATS_TICK_SEC,
)
from app.rate_limit import TokenBucket
from app.state import AppState
from app.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

state_lock = asyncio.Lock()
app_state = AppState.fresh()
manager = ConnectionManager()


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
        " | Bucket: capacity=%s refill_rate=%s/s",
        STATS_TICK_SEC,
        PERSIST_INTERVAL_SEC,
        BUCKET_CAPACITY,
        BUCKET_REFILL_RATE,
    )
    await db.init_db()
    row = await db.load_state_row()
    async with state_lock:
        if row is None:
            app_state = AppState.fresh()
            await persist_state()
        else:
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

    Args:
        websocket: Client WebSocket

    Returns:
        None
    """
    await manager.connect(websocket)
    bucket = TokenBucket(BUCKET_CAPACITY, BUCKET_REFILL_RATE)
    try:
        async with state_lock:
            snapshot = app_state.snapshot()
        await manager.send_snapshot(websocket, snapshot)

        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if message.get("type") != "toggle":
                continue

            if not bucket.consume():
                logger.debug("Rate-limited toggle from %s", websocket.client)
                await websocket.send_text(json.dumps({"type": "rate_limited"}))
                continue

            async with state_lock:
                app_state.toggle()
                await persist_state()
                snapshot = app_state.snapshot()

            await manager.broadcast(snapshot)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
        raise


@app.get("/")
async def index() -> FileResponse:
    """Serve the main UI."""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
