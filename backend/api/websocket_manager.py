"""WebSocket 连接管理器 — 负责向前端实时推送拓扑更新和告警"""
from __future__ import annotations
import json
import logging
from typing import Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """管理所有 WebSocket 连接，提供拓扑、告警、意图更新的广播能力"""

    def __init__(self):
        self._connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        """接受 WebSocket 连接并加入连接池"""
        await ws.accept()
        self._connections.add(ws)
        logger.info(f"[WS] 新连接，当前连接数: {len(self._connections)}")

    def disconnect(self, ws: WebSocket):
        """从连接池中移除 WebSocket 连接"""
        self._connections.discard(ws)
        logger.info(f"[WS] 断开连接，当前连接数: {len(self._connections)}")

    async def broadcast(self, message: dict):
        """向所有已连接客户端广播 JSON 消息，自动清理断开的连接"""
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
        """广播拓扑更新"""
        await self.broadcast({"type": "topology_update", "data": topology})

    async def broadcast_alert(self, alert: dict):
        """广播告警信息"""
        await self.broadcast({"type": "alert", "data": alert})

    async def broadcast_intent_update(self, record: dict):
        """广播意图处理状态更新"""
        await self.broadcast({"type": "intent_update", "data": record})


ws_manager = WebSocketManager()
