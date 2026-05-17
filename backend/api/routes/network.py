"""拓扑、网络信息、告警 API 路由"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
from core.network_manager import network_manager
from api.websocket_manager import ws_manager

# ─── 拓扑路由 ──────────────────────────────────────────────
topology_router = APIRouter(prefix="/api/topology", tags=["topology"])

@topology_router.get("")
async def get_topology():
    return network_manager.get_topology_dict()

@topology_router.post("/refresh")
async def refresh_topology():
    await network_manager.refresh_topology()
    return network_manager.get_topology_dict()


# ─── 网络信息路由 ────────────────────────────────────────────
network_router = APIRouter(prefix="/api/network", tags=["network"])

@network_router.get("/status")
async def get_status():
    return network_manager.get_status()

@network_router.get("/stats")
async def get_stats():
    from core.vm_connector import vm_connector
    return await vm_connector.get_stats()


# ─── 告警路由 ────────────────────────────────────────────────
alerts_router = APIRouter(prefix="/api/alerts", tags=["alerts"])

@alerts_router.get("")
async def get_alerts(limit: int = 50):
    return {"alerts": network_manager.get_alerts(limit)}

@alerts_router.delete("/{alert_id}")
async def resolve_alert(alert_id: str):
    for alert in network_manager.alerts:
        if alert.id == alert_id:
            alert.resolved = True
            return {"message": "已标记为已处理"}
    return {"message": "告警不存在"}


# ─── WebSocket 路由 ──────────────────────────────────────────
ws_router = APIRouter(tags=["websocket"])

@ws_router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        # 立即推送当前拓扑
        await ws.send_text(
            json.dumps({
                "type": "topology_update",
                "data": network_manager.get_topology_dict()
            }, ensure_ascii=False)
        )
        while True:
            await ws.receive_text()   # 保持连接，接收 ping
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception:
        ws_manager.disconnect(ws)
