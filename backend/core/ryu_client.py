"""
Ryu REST API 直连客户端
后端 Windows 直接对接 Ryu 控制器（http://VM:8080），不经过 VM Agent 中转
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class RyuClient:
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

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── 连通性 ────────────────────────────────────────────
    async def ping(self) -> bool:
        try:
            c = await self._get()
            r = await c.get("/stats/switches")
            return r.status_code == 200
        except Exception as e:
            logger.warning(f"[RyuClient] ping failed: {e}")
            return False

    # ── 拓扑 ──────────────────────────────────────────────
    async def get_topology_switches(self) -> List[Dict]:
        try:
            c = await self._get()
            r = await c.get("/v1.0/topology/switches")
            r.raise_for_status()
            return r.json() or []
        except Exception as e:
            logger.error(f"[RyuClient] get_topology_switches: {e}")
            return []

    async def get_topology_links(self) -> List[Dict]:
        try:
            c = await self._get()
            r = await c.get("/v1.0/topology/links")
            r.raise_for_status()
            return r.json() or []
        except Exception as e:
            logger.error(f"[RyuClient] get_topology_links: {e}")
            return []

    async def get_topology_hosts(self) -> List[Dict]:
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

    # ── 流表 ──────────────────────────────────────────────
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

    async def add_flow(self, entry: Dict) -> bool:
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

    async def delete_flow_by_cookie(self, dpid: int, cookie: int) -> bool:
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
            logger.error(f"[RyuClient] delete_flow_by_cookie({dpid}, {cookie}): {e}")
            return False

    # ── 端口统计 ──────────────────────────────────────────
    async def get_port_stats(self, dpid: int) -> List[Dict]:
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

    # ── Meter ─────────────────────────────────────────────
    async def get_meter_config(self, dpid: int) -> List[Dict]:
        try:
            c = await self._get()
            r = await c.get(f"/stats/meterconfig/{dpid}")
            r.raise_for_status()
            data = r.json()
            return data.get(str(dpid), [])
        except Exception as e:
            logger.error(f"[RyuClient] get_meter_config({dpid}): {e}")
            return []

    async def add_meter(self, entry: Dict) -> bool:
        try:
            c = await self._get()
            r = await c.post("/stats/meterentry/add", json=entry)
            r.raise_for_status()
            logger.info(f"[RyuClient] add_meter OK dpid={entry.get('dpid')} id={entry.get('meter_id')}")
            return True
        except Exception as e:
            logger.error(f"[RyuClient] add_meter: {e}")
            return False

    async def delete_meter(self, dpid: int, meter_id: int) -> bool:
        try:
            c = await self._get()
            r = await c.post("/stats/meterentry/delete", json={"dpid": dpid, "meter_id": meter_id})
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"[RyuClient] delete_meter({dpid}, {meter_id}): {e}")
            return False


# 单例
ryu_client = RyuClient()
