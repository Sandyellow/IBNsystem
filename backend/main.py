"""FastAPI 应用入口 — IBN System v2"""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core.ryu_client import ryu_client
from core.topo_manager import topo_manager
from core.stats_manager import stats_manager
from api.websocket_manager import ws_manager
from api.routes.network import router as network_router
from api.routes.intent import router as intent_router
from api.routes.debug import router as debug_router
from api.routes.ws import router as ws_router

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
    await stats_manager.start_polling(interval=3.0)
    
    # 启动后触发一次数据平面调和，补齐丢失的流表
    from core.policy_executor import policy_executor
    import asyncio
    asyncio.create_task(policy_executor.sync_with_data_plane())
    
    logger.info("IBN 系统 v2 已启动，直连 Ryu 轮询中...")
    yield
    # 关闭：停止轮询 → 关闭 Ryu 连接
    await stats_manager.stop_polling()
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


app.include_router(ws_router)


@app.get("/api/health")
async def health():
    ryu_ok = await ryu_client.ping()
    return {
        "status": "ok",
        "ryu_connected": ryu_ok,
        **topo_manager.get_status(),
    }
