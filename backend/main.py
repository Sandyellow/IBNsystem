"""FastAPI 应用入口"""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.network_manager import network_manager
from core.vm_connector import vm_connector
from api.websocket_manager import ws_manager
from api.routes.network import topology_router, network_router, alerts_router, ws_router
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
    # ── 启动时注册 WebSocket 回调并启动轮询
    network_manager.on_alert(ws_manager.broadcast_alert)
    network_manager.on_topology_update(ws_manager.broadcast_topology)
    await network_manager.start_polling()
    logger.info("IBN 系统已启动，网络状态轮询中...")
    yield
    # ── 关闭时清理
    await network_manager.stop_polling()
    await vm_connector.close()
    logger.info("IBN 系统已关闭")


app = FastAPI(
    title="IBN — Intent-Based Networking System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(topology_router)
app.include_router(network_router)
app.include_router(alerts_router)
app.include_router(intent_router)
app.include_router(ws_router)
app.include_router(debug_router)


@app.get("/api/health")
async def health():
    vm_ok = await vm_connector.ping()
    return {
        "status": "ok",
        "vm_connected": vm_ok,
        "network_status": network_manager.get_status(),
    }
