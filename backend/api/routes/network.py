"""
网络数据 API — 提供拓扑、流表、端口统计、Meter、活跃策略等真实数据
所有数据直接来自 Ryu REST API，无模拟值
"""
from __future__ import annotations
import logging
from fastapi import APIRouter

from core.ryu_client import ryu_client
from core.topology_manager import topo_manager
from core.policy_executor import policy_executor
from core.statistics_manager import stats_manager

router = APIRouter(prefix="/api", tags=["network"])
logger = logging.getLogger(__name__)


@router.get("/health")
async def health():
    """系统健康检查"""
    ryu_ok = await ryu_client.ping()
    return {
        "status": "ok",
        "ryu_connected": ryu_ok,
        **topo_manager.get_status(),
        "active_policies": len(policy_executor.get_active_policies()),
    }


# ── 拓扑 ──────────────────────────────────────────────────

@router.get("/topology")
async def get_topology():
    """获取当前网络拓扑（节点 + 链路）"""
    return topo_manager.topology


@router.post("/topology/refresh")
async def refresh_topology():
    """主动刷新拓扑"""
    await topo_manager.refresh()
    # 拓扑刷新时，触发一次状态调和
    import asyncio
    asyncio.create_task(policy_executor.sync_with_data_plane())
    return topo_manager.topology


@router.get("/hosts")
async def get_hosts():
    """获取主机列表（含 MAC、IP、连接信息）"""
    return {"hosts": topo_manager.get_all_hosts()}


# ── 流表 ──────────────────────────────────────────────────

@router.get("/flows")
async def get_all_flows():
    """获取所有交换机的流表"""
    dpids = topo_manager.get_all_switch_dpids()
    result = {}
    for dpid in dpids:
        result[str(dpid)] = await ryu_client.get_flows(dpid)
    return {
        "flows": result,
        "switch_count": len(dpids),
        "total_entries": sum(len(v) for v in result.values()),
    }


@router.get("/flows/{dpid}")
async def get_flows_for_switch(dpid: int):
    """获取指定交换机（dpid 整数）的流表"""
    flows = await ryu_client.get_flows(dpid)
    return {"dpid": dpid, "flows": flows, "count": len(flows)}


# ── 端口统计 ──────────────────────────────────────────────

@router.get("/port-stats")
async def get_port_stats():
    """获取所有交换机的端口统计及近期历史速率（包计数、字节数、错误数）"""
    dpids = topo_manager.get_all_switch_dpids()
    result = {}
    for dpid in dpids:
        result[str(dpid)] = await ryu_client.get_port_stats(dpid)
        
    history = stats_manager.get_history()
    
    return {
        "port_stats": result, 
        "history": history,
        "switch_count": len(dpids)
    }


@router.get("/port-desc")
async def get_port_desc():
    """获取所有交换机的端口描述（接口名称等）"""
    dpids = topo_manager.get_all_switch_dpids()
    result = {}
    for dpid in dpids:
        result[str(dpid)] = await ryu_client.get_port_desc(dpid)
    return {"port_desc": result}


# ── Meter ─────────────────────────────────────────────────

@router.get("/meters")
async def get_meters():
    """获取所有交换机的 Meter 配置（限速条目）"""
    dpids = topo_manager.get_all_switch_dpids()
    result = {}
    for dpid in dpids:
        result[str(dpid)] = await ryu_client.get_meter_config(dpid)
    return {"meters": result}


# ── 活跃策略 ──────────────────────────────────────────────

@router.get("/policies")
async def get_active_policies():
    """获取 IBN 系统当前已下发的所有自定义策略"""
    return {"policies": policy_executor.get_active_policies()}


@router.delete("/policies/{policy_id}")
async def delete_policy(policy_id: str):
    """撤销指定策略（通过 cookie 从所有交换机精准删除对应流表）"""
    ok, msg = await policy_executor.delete_policy(policy_id)
    return {"success": ok, "message": msg}


# ── 网络状态（兼容旧前端路由）────────────────────────────

@router.get("/network/status")
async def network_status():
    return topo_manager.get_status()


@router.get("/alerts")
async def get_alerts():
    """返回空告警列表（告警功能已简化）"""
    return {"alerts": []}
