"""WebSocket connection registry and broadcast."""

from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """Track active clients and push state snapshots."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """
        Accept and register a WebSocket client.

        Args:
            websocket: Incoming connection

        Returns:
            None
        """
        await websocket.accept()
        self._connections.add(websocket)

    @property
    def connection_count(self) -> int:
        """Number of active WebSocket clients."""
        return len(self._connections)

    def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove a client from the registry.

        Args:
            websocket: Connection to drop

        Returns:
            None
        """
        self._connections.discard(websocket)

    async def send_snapshot(self, websocket: WebSocket, payload: dict[str, Any]) -> None:
        """
        Send state JSON to one client.

        Args:
            websocket: Target connection
            payload: State snapshot dict

        Returns:
            None
        """
        await websocket.send_text(json.dumps(payload))

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """
        Push state to all connected clients; drop failed sockets.

        Args:
            payload: State snapshot dict

        Returns:
            None
        """
        dead: list[WebSocket] = []
        text = json.dumps(payload)
        for websocket in self._connections:
            try:
                await websocket.send_text(text)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket)
