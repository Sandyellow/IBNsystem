"""FastAPI 应用入口 — IBN System v2"""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core.ryu_client import ryu_client
from core.topo_manager import topo_manager
from api.websocket_manager import ws_manager
from api.routes.network import router as network_router
from api.routes.intent import router as intent_router
from api.routes.debug import router as debug_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：注册回调 → 启动拓扑轮询
    topo_manager.on_topology_update(ws_manager.broadcast_topology)
    await topo_manager.start_polling()
    logger.info("IBN 系统 v2 已启动，直连 Ryu 轮询中...")
    yield
    # 关闭：停止轮询 → 关闭 Ryu 连接
    await topo_manager.stop_polling()
    await ryu_client.close()
    logger.info("IBN 系统已关闭")


app = FastAPI(
    title="IBN — Intent-Based Networking System",
    version="2.0.0",
    description="基于 LLM 的网络意图驱动系统，直连 Ryu SDN 控制器",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由注册
app.include_router(network_router)
app.include_router(intent_router)
app.include_router(debug_router)


# WebSocket 端点
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
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


@app.get("/api/health")
async def health():
    ryu_ok = await ryu_client.ping()
    return {
        "status": "ok",
        "ryu_connected": ryu_ok,
        **topo_manager.get_status(),
    }
