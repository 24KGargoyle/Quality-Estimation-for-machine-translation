"""In-process WebSocket connection manager for group chat.

Keyed by group_id. A single backend instance is assumed for this scope; a
production multi-instance deployment would back this with a pub/sub layer
(e.g. Redis) — noted in docs/DEPLOYMENT.md.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger("meeting_intel.realtime")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, group_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(group_id, set()).add(websocket)

    async def disconnect(self, group_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(group_id)
            if conns and websocket in conns:
                conns.discard(websocket)
                if not conns:
                    self._connections.pop(group_id, None)

    async def broadcast(self, group_id: str, message: dict) -> None:
        async with self._lock:
            conns = list(self._connections.get(group_id, set()))
        stale = []
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        if stale:
            async with self._lock:
                for ws in stale:
                    self._connections.get(group_id, set()).discard(ws)


ws_manager = ConnectionManager()
