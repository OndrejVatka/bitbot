"""FastAPI application — mounts all routes and the WebSocket endpoint."""

from __future__ import annotations

import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from bitbot.api.routes import portfolio, risk, trades
from bitbot.api.websocket import broadcaster

logger = logging.getLogger(__name__)

app = FastAPI(title="BitBot API", version="0.1.0", docs_url="/docs")

# Allow all origins so the Vercel frontend (and local dev) can connect.
# Restrict allow_origins to your Vercel URL in production for extra security.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(portfolio.router, prefix="/api")
app.include_router(trades.router, prefix="/api")
app.include_router(risk.router, prefix="/api")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket endpoint — push live events to the dashboard."""
    await broadcaster.connect(ws)
    try:
        # Keep the connection alive; client may send pings
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(ws)
    except Exception as exc:
        logger.debug("WebSocket closed: %s", exc)
        broadcaster.disconnect(ws)
