"""
Ryu 控制器 REST API 客户端。

继承 ControllerAdapter，实现拓扑查询和流表下发等接口。
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0, connect=5.0)


from core.controller_adapter import ControllerAdapter, NetworkPrimitive, PrimitiveType


class RyuClient(ControllerAdapter):
    """Ryu SDN 控制器 REST API 客户端，负责流表、Meter、Group 的下发与查询"""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def _get(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            async with self._lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(
                        base_url=settings.RYU_REST_URL,
                        timeout=TIMEOUT,
                    )
        return self._client
        
    async def connect(self):
        """建立 HTTP 客户端连接"""
        await self._get()

    async def close(self):
        """关闭 HTTP 客户端连接"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── 连通性 ────────────────────────────────────────────
    async def ping(self) -> bool:
        """测试 Ryu 控制器连通性"""
        try:
            c = await self._get()
            r = await c.get("/stats/switches")
            return r.status_code == 200
        except Exception as e:
            logger.warning(f"[RyuClient] ping failed: {e}")
            return False

    # ── 拓扑 ──────────────────────────────────────────────
    async def get_topology_switches(self) -> List[Dict]:
        """获取 Ryu 拓扑中的交换机列表"""
        try:
            c = await self._get()
            r = await c.get("/v1.0/topology/switches")
            r.raise_for_status()
            return r.json() or []
        except Exception as e:
            logger.error(f"[RyuClient] get_topology_switches: {e}")
            return []

    async def get_topology_links(self) -> List[Dict]:
        """获取 Ryu 拓扑中的链路列表"""
        try:
            c = await self._get()
            r = await c.get("/v1.0/topology/links")
            r.raise_for_status()
            return r.json() or []
        except Exception as e:
            logger.error(f"[RyuClient] get_topology_links: {e}")
            return []

    async def get_topology_hosts(self) -> List[Dict]:
        """获取 Ryu 拓扑中的主机列表"""
        try:
            c = await self._get()
            r = await c.get("/v1.0/topology/hosts")
            r.raise_for_status()
            return r.json() or []
        except Exception as e:
            logger.error(f"[RyuClient] get_topology_hosts: {e}")
            return []

    async def get_switch_dpids(self) -> List[int]:
        """获取所有交换机的 dpid 整数列表"""
        try:
            c = await self._get()
            r = await c.get("/stats/switches")
            r.raise_for_status()
            return r.json() or []
        except Exception as e:
            logger.error(f"[RyuClient] get_switch_dpids: {e}")
            return []

    # ── 原语操作 ──────────────────────────────────────────
    async def apply_primitive(self, primitive: NetworkPrimitive) -> bool:
        """根据原语类型分发到对应的下发方法"""
        if primitive.primitive_type == PrimitiveType.FLOW_ENTRY:
            entry = {
                "dpid": primitive.dpid,
                "cookie": primitive.cookie or 0,
                "priority": primitive.priority,
                "match": primitive.match,
                "actions": primitive.actions
            }
            if "table_id" in primitive.extra:
                entry["table_id"] = primitive.extra["table_id"]
            return await self._add_flow(entry)
            
        elif primitive.primitive_type == PrimitiveType.METER_ENTRY:
            entry = {
                "dpid": primitive.dpid,
                "meter_id": primitive.extra.get("meter_id", 1),
                "flags": primitive.extra.get("flags", "KBPS"),
                "bands": primitive.extra.get("bands", [])
            }
            return await self._add_meter(entry)
            
        elif primitive.primitive_type == PrimitiveType.GROUP_ENTRY:
            entry = {
                "dpid": primitive.dpid,
                "type": primitive.extra.get("type", "ALL"),
                "group_id": primitive.extra.get("group_id", 1),
                "buckets": primitive.extra.get("buckets", [])
            }
            return await self._add_group(entry)
            
        return False

    async def delete_primitive(self, primitive: NetworkPrimitive) -> bool:
        """根据原语类型分发到对应的删除方法"""
        if primitive.primitive_type == PrimitiveType.FLOW_ENTRY:
            if primitive.cookie is not None:
                return await self.delete_flows_by_cookie(primitive.dpid, primitive.cookie)
            else:
                entry = {
                    "dpid": primitive.dpid,
                    "cookie": 0,
                    "cookie_mask": 0,
                    "table_id": primitive.extra.get("table_id", 0),
                    "priority": primitive.priority,
                    "match": primitive.match,
                }
                return await self._delete_flow_strict(entry)
                
        elif primitive.primitive_type == PrimitiveType.METER_ENTRY:
            return await self._delete_meter(primitive.dpid, primitive.extra.get("meter_id", 1))
            
        elif primitive.primitive_type == PrimitiveType.GROUP_ENTRY:
            return await self._delete_group(primitive.dpid, primitive.extra.get("group_id", 1))
            
        return False

    # ── 内部具体 API ──────────────────────────────────────
    async def _add_flow(self, entry: Dict) -> bool:
        """下发流表规则"""
        try:
            c = await self._get()
            r = await c.post("/stats/flowentry/add", json=entry)
            r.raise_for_status()
            logger.info(f"[RyuClient] add_flow OK dpid={entry.get('dpid')} prio={entry.get('priority')}")
            return True
        except Exception as e:
            logger.error(f"[RyuClient] add_flow: {e}")
            return False

    async def _delete_flow_strict(self, entry: Dict) -> bool:
        """严格匹配删除单条流表"""
        try:
            c = await self._get()
            r = await c.post("/stats/flowentry/delete_strict", json=entry)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"[RyuClient] delete_flow_strict: {e}")
            return False

    async def delete_flows_by_cookie(self, dpid: int, cookie: int) -> bool:
        """通过 cookie 删除特定意图下发的所有流表"""
        try:
            c = await self._get()
            entry = {
                "dpid": dpid,
                "cookie": cookie,
                "cookie_mask": 0xFFFFFFFFFFFFFFFF,
                "table_id": 0,
                "idle_timeout": 0,
                "hard_timeout": 0,
                "priority": 0,
                "match": {},
            }
            r = await c.post("/stats/flowentry/delete", json=entry)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"[RyuClient] delete_flows_by_cookie({dpid}, {cookie}): {e}")
            return False

    async def _add_meter(self, entry: Dict) -> bool:
        """下发 Meter 表项"""
        try:
            c = await self._get()
            r = await c.post("/stats/meterentry/add", json=entry)
            r.raise_for_status()
            logger.info(f"[RyuClient] add_meter OK dpid={entry.get('dpid')} id={entry.get('meter_id')}")
            return True
        except Exception as e:
            logger.error(f"[RyuClient] add_meter: {e}")
            return False

    async def _delete_meter(self, dpid: int, meter_id: int) -> bool:
        """删除 Meter 表项"""
        try:
            c = await self._get()
            r = await c.post("/stats/meterentry/delete", json={"dpid": dpid, "meter_id": meter_id})
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"[RyuClient] delete_meter({dpid}, {meter_id}): {e}")
            return False

    async def _add_group(self, entry: Dict) -> bool:
        """下发 Group 表项"""
        try:
            c = await self._get()
            r = await c.post("/stats/groupentry/add", json=entry)
            r.raise_for_status()
            logger.info(f"[RyuClient] add_group OK dpid={entry.get('dpid')} id={entry.get('group_id')}")
            return True
        except Exception as e:
            logger.error(f"[RyuClient] add_group: {e}")
            return False

    async def _delete_group(self, dpid: int, group_id: int) -> bool:
        """删除 Group 表项"""
        try:
            c = await self._get()
            r = await c.post("/stats/groupentry/delete", json={"dpid": dpid, "group_id": group_id})
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"[RyuClient] delete_group({dpid}, {group_id}): {e}")
            return False

    # ── 流表/统计读取 ───────────────────────────────────────
    async def get_flows(self, dpid: int) -> List[Dict]:
        """获取指定交换机的所有流表条目"""
        try:
            c = await self._get()
            r = await c.get(f"/stats/flow/{dpid}")
            r.raise_for_status()
            data = r.json()
            return data.get(str(dpid), [])
        except Exception as e:
            logger.error(f"[RyuClient] get_flows({dpid}): {e}")
            return []

    async def get_port_stats(self, dpid: int) -> List[Dict]:
        """获取指定交换机的端口统计"""
        try:
            c = await self._get()
            r = await c.get(f"/stats/port/{dpid}")
            r.raise_for_status()
            data = r.json()
            return data.get(str(dpid), [])
        except Exception as e:
            logger.error(f"[RyuClient] get_port_stats({dpid}): {e}")
            return []

    async def get_port_desc(self, dpid: int) -> List[Dict]:
        """获取端口描述（接口名称等）"""
        try:
            c = await self._get()
            r = await c.get(f"/stats/portdesc/{dpid}")
            r.raise_for_status()
            data = r.json()
            return data.get(str(dpid), [])
        except Exception as e:
            logger.error(f"[RyuClient] get_port_desc({dpid}): {e}")
            return []

    async def get_meter_config(self, dpid: int) -> List[Dict]:
        """获取指定交换机的 Meter 配置"""
        try:
            c = await self._get()
            r = await c.get(f"/stats/meterconfig/{dpid}")
            r.raise_for_status()
            data = r.json()
            return data.get(str(dpid), [])
        except Exception as e:
            logger.error(f"[RyuClient] get_meter_config({dpid}): {e}")
            return []


# 单例
ryu_client = RyuClient()
