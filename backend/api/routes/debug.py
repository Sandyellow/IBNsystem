"""系统诊断与调试 API"""
from __future__ import annotations
import time
import logging
from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

from core.ryu_client import ryu_client
from core.topology_manager import topo_manager
from core.workflow import parse_intent_dry_run
from core.policy_executor import policy_executor
from api.websocket_manager import ws_manager

router = APIRouter(prefix="/api/debug", tags=["debug"])
logger = logging.getLogger(__name__)


@router.get("/health")
async def debug_health():
    """系统健康总览"""
    from config import settings
    ryu_ok = await ryu_client.ping()
    topo_status = topo_manager.get_status()
    return {
        "timestamp": time.time(),
        "overall": "ok" if ryu_ok else "degraded",
        "components": {
            "ryu": {
                "status": "ok" if ryu_ok else "unreachable",
                "url": settings.RYU_REST_URL,
            },
            "llm": {
                "status": "configured",
                "base_url": settings.LLM_BASE_URL,
                "model": settings.LLM_MODEL,
            },
            "topology": {
                "status": "ok" if topo_status["node_count"] > 0 else "empty",
                **topo_status,
            },
            "websocket": {
                "active_connections": len(ws_manager._connections),
            },
        },
        "active_policies": len(policy_executor.get_active_policies()),
    }


class DryRunRequest(BaseModel):
    text: str


@router.post("/dry-run")
async def debug_dry_run(req: DryRunRequest):
    """测试意图解析结果"""
    t0 = time.perf_counter()
    topo_ctx = topo_manager.get_llm_context()
    intent, error = await parse_intent_dry_run(req.text)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "input": req.text,
        "elapsed_ms": elapsed_ms,
        "retries": 0,
        "ok": intent is not None,
        "error": error or None,
        "parsed_intent": intent.model_dump() if intent else None,
        "topo_context": topo_ctx,
    }


@router.get("/topology")
async def debug_topology():
    """当前拓扑诊断视图"""
    topo = topo_manager.topology
    return {
        "topology": topo,
        "host_config": topo_manager.get_all_hosts(),
        "switch_dpids": topo_manager.get_all_switch_dpids(),
        "llm_context": topo_manager.get_llm_context(),
    }


class RyuFlowRequest(BaseModel):
    dpid: int
    entry: Dict[str, Any]


@router.post("/ryu/add-flow")
async def debug_add_flow(req: RyuFlowRequest):
    """直接向 Ryu 下发流表（调试用）"""
    entry = req.entry
    entry["dpid"] = req.dpid
    ok = await ryu_client._add_flow(entry)
    return {"success": ok, "entry": entry}


@router.get("/ryu/flows/{dpid}")
async def debug_get_flows(dpid: int):
    """直接从 Ryu 查询流表"""
    flows = await ryu_client.get_flows(dpid)
    return {"dpid": dpid, "flows": flows, "count": len(flows)}
