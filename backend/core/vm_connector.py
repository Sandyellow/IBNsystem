"""
VM 连接器 — 负责与 Ubuntu VM 上的 Agent 通信
支持：获取拓扑、获取统计信息、下发策略、执行 Mininet 命令
"""
from __future__ import annotations
import httpx
import logging
from typing import Any, Dict, Optional

from config import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0, connect=5.0)


import asyncio

class VMConnector:
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            async with self._lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(
                        base_url=settings.VM_AGENT_URL,
                        timeout=TIMEOUT,
                    )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ───── 连通性检查 ─────────────────────────────────────
    async def ping(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get("/ping")
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"[VMConnector] ping failed: {e}")
            return False

    # ───── 拓扑获取 ──────────────────────────────────────
    async def get_topology(self) -> Dict[str, Any]:
        """从 VM Agent 获取完整网络拓扑"""
        try:
            client = await self._get_client()
            resp = await client.get("/topology")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"[VMConnector] get_topology failed: {e}")
            return {"nodes": [], "links": [], "error": str(e)}

    # ───── 统计信息 ───────────────────────────────────────
    async def get_stats(self) -> Dict[str, Any]:
        """获取所有交换机端口统计信息"""
        try:
            client = await self._get_client()
            resp = await client.get("/stats")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"[VMConnector] get_stats failed: {e}")
            return {"switches": [], "error": str(e)}

    async def get_link_stats(self) -> Dict[str, Any]:
        """获取链路级别延迟、丢包信息"""
        try:
            client = await self._get_client()
            resp = await client.get("/link-stats")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"[VMConnector] get_link_stats failed: {e}")
            return {"links": [], "error": str(e)}

    # ───── 策略执行 ───────────────────────────────────────
    async def apply_policy(self, policy: Dict[str, Any]) -> Dict[str, Any]:
        """将策略下发到 VM Agent 执行"""
        try:
            client = await self._get_client()
            resp = await client.post("/policy/apply", json=policy)
            resp.raise_for_status()
            return {"success": True, "result": resp.json()}
        except httpx.HTTPStatusError as e:
            logger.error(f"[VMConnector] apply_policy HTTP error: {e.response.text}")
            return {"success": False, "error": e.response.text}
        except Exception as e:
            logger.error(f"[VMConnector] apply_policy failed: {e}")
            return {"success": False, "error": str(e)}

    async def rollback_policy(self, policy: Dict[str, Any]) -> Dict[str, Any]:
        """回滚策略"""
        try:
            client = await self._get_client()
            resp = await client.post("/policy/rollback", json=policy)
            resp.raise_for_status()
            return {"success": True, "result": resp.json()}
        except Exception as e:
            logger.error(f"[VMConnector] rollback_policy failed: {e}")
            return {"success": False, "error": str(e)}

    # ───── Mininet 命令 ───────────────────────────────────
    async def exec_mininet_cmd(self, command: str) -> Dict[str, Any]:
        """在 Mininet 中执行命令（如 ping、iperf、link up/down）
        
        修复: HTTP 200 时若响应 JSON 缺少 success 字段，自动补全为 True，
        避免上层因 result.get('success') 返回 None 而误判为失败。
        """
        try:
            client = await self._get_client()
            resp = await client.post("/mininet/exec", json={"command": command})
            resp.raise_for_status()
            data = resp.json()
            # 规范化：确保 success 字段存在（HTTP 200 即视为成功）
            if "success" not in data:
                data["success"] = True
            return data
        except httpx.HTTPStatusError as e:
            body = e.response.text
            logger.error(f"[VMConnector] exec_mininet_cmd HTTP {e.response.status_code}: {body}")
            return {"success": False, "error": body}
        except Exception as e:
            logger.error(f"[VMConnector] exec_mininet_cmd failed: {e}")
            return {"success": False, "error": str(e)}


# 单例
vm_connector = VMConnector()
