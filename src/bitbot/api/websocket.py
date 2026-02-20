"""WebSocket connection manager and event broadcaster.

The broadcaster singleton is used by main.py to emit real-time events
(signals, trades, price updates, snapshots) to all connected dashboard clients.
"""

from __future__ import annotations

import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages all active WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new WebSocket client."""
        await ws.accept()
        self._connections.append(ws)
        logger.info(
            "WebSocket client connected (total: %d)", len(self._connections)
        )

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a disconnected client."""
        if ws in self._connections:
            self._connections.remove(ws)
        logger.info(
            "WebSocket client disconnected (total: %d)", len(self._connections)
        )

    async def broadcast(self, event_type: str, data: dict) -> None:
        """Send an event to all connected WebSocket clients.

        Dead connections are silently removed.
        """
        if not self._connections:
            return

        message = json.dumps({"type": event_type, "data": data})
        dead: list[WebSocket] = []

        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            if ws in self._connections:
                self._connections.remove(ws)


# Singleton — imported by main.py to emit events and by server.py to manage connections.
broadcaster = WebSocketManager()
