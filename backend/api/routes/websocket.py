"""WebSocket 端点 — 接受前端连接并推送拓扑、策略等实时更新"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from api.websocket_manager import ws_manager
from core.topology_manager import topo_manager

router = APIRouter(tags=["websocket"])

@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket 端点，接受前端连接并推送实时状态更新"""
    await ws_manager.connect(ws)
    try:
        # 连接后立即推送当前状态
        await ws_manager.broadcast_topology(topo_manager.topology)
        while True:
            try:
                msg = await ws.receive_text()
                # 心跳处理
                if msg == "ping":
                    await ws.send_text("pong")
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(ws)
