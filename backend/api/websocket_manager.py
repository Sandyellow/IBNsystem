"""WebSocket 连接管理器 — 负责向前端实时推送拓扑更新和告警"""
from __future__ import annotations
import json
import logging
from typing import Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self):
        self._connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.add(ws)
        logger.info(f"[WS] 新连接，当前连接数: {len(self._connections)}")

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws)
        logger.info(f"[WS] 断开连接，当前连接数: {len(self._connections)}")

    async def broadcast(self, message: dict):
        if not self._connections:
            return
        text = json.dumps(message, ensure_ascii=False)
        
        import asyncio
        async def send(ws):
            try:
                await ws.send_text(text)
                return None
            except Exception:
                return ws
                
        results = await asyncio.gather(*(send(ws) for ws in self._connections.copy()))
        dead = {ws for ws in results if ws is not None}
        for ws in dead:
            self._connections.discard(ws)

    async def broadcast_topology(self, topology: dict):
        await self.broadcast({"type": "topology_update", "data": topology})

    async def broadcast_alert(self, alert: dict):
        await self.broadcast({"type": "alert", "data": alert})

    async def broadcast_intent_update(self, record: dict):
        await self.broadcast({"type": "intent_update", "data": record})


ws_manager = WebSocketManager()
