"""
拓扑与主机状态管理器
从 Ryu topology API 获取网络拓扑，并动态发现主机 MAC/IP/连接端口（完全动态，无静态配置局限）
替代旧版 network_manager.py
"""
from __future__ import annotations
import asyncio
import ipaddress
import logging
import time
from typing import Any, Callable, Dict, List, Optional

import httpx

from config import settings
from core.ryu_client import ryu_client

logger = logging.getLogger(__name__)

HostInfo = Dict[str, Any]


def _dpid_to_sw_name(dpid: str) -> str:
    """将 Ryu dpid 转换为交换机名（完全来自 Ryu 数据，无静态映射）"""
    try:
        n = int(dpid, 16) if isinstance(dpid, str) else int(dpid)
        return f"s{n}"
    except Exception:
        return f"s_{dpid}"


def _build_dynamic_hosts(ryu_hosts_raw: list) -> List[HostInfo]:
    """将 Ryu /v1.0/topology/hosts 原始格式转换为 IBN 主机格式。

    命名策略：按 IP 地址升序排序后顺次编号为 h1/h2/h3/...
    完全动态，适配任何未知拓扑。
    """
    hosts: List[HostInfo] = []
    seen_macs: set = set()

    for rh in ryu_hosts_raw:
        mac = rh.get("mac", "")
        if not mac or mac in seen_macs:
            continue
        seen_macs.add(mac)
        ipv4_list = rh.get("ipv4", [])
        ip = ipv4_list[0] if ipv4_list else None
        port_info = rh.get("port", {})
        sw_dpid = port_info.get("dpid", "")
        port_no = port_info.get("port_no")
        connected_sw = _dpid_to_sw_name(sw_dpid) if sw_dpid else None
        hosts.append({
            "ip": ip, "mac": mac,
            "connected_switch": connected_sw, "port": port_no,
        })

    # 按 IP 地址升序排序，保证命名确定性
    def _ip_key(h):
        try:
            return ipaddress.ip_address(h["ip"] or "255.255.255.255")
        except Exception:
            return ipaddress.ip_address("255.255.255.255")

    hosts.sort(key=_ip_key)
    for i, h in enumerate(hosts, 1):
        h["id"] = f"h{i}"
    return hosts



def _is_placeholder_mac(mac: str) -> bool:
    """检测是否是静态占位 MAC（如 00:00:00:00:00:01）"""
    if not mac:
        return True
    # OUI 全为 00 且主机部分主要起侏手，这种 MAC 在真实网卡上几乎不存在
    parts = mac.split(":")
    if len(parts) != 6:
        return True
    return all(p == "00" for p in parts[:5])  # 前 5 组均为 00


class TopoManager:
    def __init__(self):
        self._topology: Dict[str, Any] = {"nodes": [], "links": [], "timestamp": 0.0}
        self._hosts: List[HostInfo] = []  # 初始为空，等待动态发现
        self._ryu_connected: bool = False
        self._poll_task: Optional[asyncio.Task] = None
        self._callbacks: List[Callable] = []
        self._agent_client: Optional[httpx.AsyncClient] = None

    # ── VM Agent 客户端 ────────────────────────────────────
    def _agent(self) -> httpx.AsyncClient:
        if self._agent_client is None or self._agent_client.is_closed:
            self._agent_client = httpx.AsyncClient(
                base_url=settings.VM_AGENT_URL,
                timeout=httpx.Timeout(8.0, connect=3.0),
            )
        return self._agent_client

    # ── 主机配置 ───────────────────────────────────────────────────
    async def fetch_host_config(self):
        """从 VM Agent /hosts 动态获取真实主机配置（Ryu PacketIn 学习结果）。
        若获取失败或返回空列表，保持当前 _hosts 不变，而非回退到假 MAC。"""
        try:
            r = await self._agent().get("/hosts")
            r.raise_for_status()
            data = r.json()
            hosts = data.get("hosts", [])
            discovered = data.get("discovered", False)
            if hosts and discovered:
                self._hosts = hosts
                logger.info(
                    f"[TopoManager] 动态主机已发现: "
                    f"{[(h['id'], h['mac']) for h in hosts]}"
                )
            elif not discovered:
                logger.warning(
                    "[TopoManager] VM Agent 返回 discovered=False，"
                    f"warning: {data.get('warning', '')}。"
                    f"当前 _hosts 共 {len(self._hosts)} 条，保持不变。"
                )
        except Exception as e:
            logger.warning(f"[TopoManager] 无法获取动态主机配置: {e}。当前 _hosts 保持不变。")

    def get_host(self, host_id: Optional[str]) -> Optional[HostInfo]:
        if not host_id:
            return None
        for h in self._hosts:
            if h["id"] == host_id:
                return h
        return None

    def get_all_hosts(self) -> List[HostInfo]:
        return list(self._hosts)

    # ── 交换机 dpid 解析 ───────────────────────────────────
    def get_switch_dpid(self, switch_id: Optional[str]) -> Optional[int]:
        """将交换机名（如 s1）转换为整数 dpid"""
        if not switch_id:
            return None
        # 先从拓扑节点中查找
        for node in self._topology.get("nodes", []):
            if node.get("id") == switch_id and node.get("type") == "switch":
                dpid_str = node.get("dpid", "")
                try:
                    return int(dpid_str, 16) if isinstance(dpid_str, str) else int(dpid_str)
                except (ValueError, TypeError):
                    pass
        # 兜底：s1→1, s2→2, s3→3
        try:
            return int(switch_id.lstrip("s"))
        except (ValueError, TypeError):
            return None

    def get_all_switch_dpids(self) -> List[int]:
        """获取所有交换机的整数 dpid 列表"""
        dpids = []
        for node in self._topology.get("nodes", []):
            if node.get("type") == "switch" and node.get("dpid"):
                try:
                    dpid_str = node["dpid"]
                    dpid = int(dpid_str, 16) if isinstance(dpid_str, str) else int(dpid_str)
                    dpids.append(dpid)
                except Exception:
                    pass
        return dpids if dpids else [1, 2, 3]  # 兜底

    @property
    def topology(self) -> Dict[str, Any]:
        return self._topology

    @property
    def ryu_connected(self) -> bool:
        return self._ryu_connected

    # ── LLM 上下文 ─────────────────────────────────────────
    def get_llm_context(self) -> str:
        """生成给 LLM 的完整网络上下文字符串，包含真实的节点/MAC/IP信息"""
        lines = ["[当前网络拓扑]"]

        switches = [n for n in self._topology.get("nodes", []) if n.get("type") == "switch"]
        if switches:
            sw_list = ", ".join(f"{n['id']}(dpid={n.get('dpid','')})" for n in switches)
            lines.append(f"交换机: {sw_list}")
        else:
            lines.append("交换机: s1, s2, s3 (默认拓扑)")

        if self._hosts:
            lines.append("主机（完整信息）:")
            for h in self._hosts:
                lines.append(
                    f"  {h['id']}: IP={h['ip']}, MAC={h['mac']}, "
                    f"连接={h['connected_switch']} 端口{h.get('port', '?')}"
                )

        sw_links = [
            l for l in self._topology.get("links", [])
            if not l["source"].startswith("h") and not l["target"].startswith("h")
        ]
        if sw_links:
            link_str = ", ".join(f"{l['source']}↔{l['target']}" for l in sw_links)
            lines.append(f"交换机间链路: {link_str}")

        return "\n".join(lines)

    # ── 拓扑刷新 ───────────────────────────────────────────
    async def refresh(self):
        """从 Ryu topology API 刷新拓扑数据"""
        try:
            sw_list = await ryu_client.get_topology_switches()
            if not sw_list:
                self._ryu_connected = False
                return

            self._ryu_connected = True

            # 构建交换机节点
            dpid_to_id: Dict[str, str] = {}
            nodes = []
            for sw in sw_list:
                dpid = sw.get("dpid", "")
                try:
                    n = int(dpid, 16) if isinstance(dpid, str) else int(dpid)
                    node_id = f"s{n}"
                except Exception:
                    node_id = f"s_{dpid}"
                dpid_to_id[dpid] = node_id
                nodes.append({
                    "id": node_id,
                    "type": "switch",
                    "label": node_id,
                    "dpid": dpid,
                    "port_count": len(sw.get("ports", [])),
                })

            # 等待 LLDP 链路发现（最多重试3次）
            links_raw = []
            for _ in range(3):
                links_raw = await ryu_client.get_topology_links()
                if len(links_raw) >= max(1, (len(sw_list) - 1) * 2):
                    break
                await asyncio.sleep(1)

            seen = set()
            links = []
            for lk in links_raw:
                src_dpid = lk.get("src", {}).get("dpid", "")
                dst_dpid = lk.get("dst", {}).get("dpid", "")
                src_port = lk.get("src", {}).get("port_no")
                dst_port = lk.get("dst", {}).get("port_no")
                src_id = dpid_to_id.get(src_dpid, f"s_{src_dpid}")
                dst_id = dpid_to_id.get(dst_dpid, f"s_{dst_dpid}")
                key = tuple(sorted([src_id, dst_id]))
                if key in seen:
                    continue
                seen.add(key)
                links.append({
                    "id": f"{src_id}-{dst_id}",
                    "source": src_id,
                    "target": dst_id,
                    "state": "up",
                    "src_port": src_port,
                    "dst_port": dst_port,
                })

            # 添加主机节点和主机-交换机链路
            # 优先使用 Ryu 动态学习的真实 MAC，如果 Ryu 已有主机数据则同步更新 _hosts
            ryu_hosts_raw = await ryu_client.get_topology_hosts()
            if ryu_hosts_raw:
                dynamic_hosts = _build_dynamic_hosts(ryu_hosts_raw)
                if dynamic_hosts:
                    self._hosts = dynamic_hosts
                    logger.debug(f"[TopoManager] 已从 Ryu 同步 {len(self._hosts)} 个主机 MAC")

            for h in self._hosts:
                nodes.append({
                    "id": h["id"],
                    "type": "host",
                    "label": h["id"],
                    "ip": h["ip"],
                    "mac": h["mac"],
                })
                sw = h.get("connected_switch")
                if sw:
                    links.append({
                        "id": f"{h['id']}-{sw}",
                        "source": h["id"],
                        "target": sw,
                        "state": "up",
                        "src_port": None,
                        "dst_port": h.get("port"),
                    })

            self._topology = {
                "nodes": nodes,
                "links": links,
                "timestamp": time.time(),
            }

            # 推送拓扑更新
            for cb in self._callbacks:
                try:
                    await cb(self._topology)
                except Exception as e:
                    logger.error(f"[TopoManager] topology callback error: {e}")

        except Exception as e:
            logger.error(f"[TopoManager] refresh error: {e}", exc_info=True)
            self._ryu_connected = False

    def on_topology_update(self, cb: Callable):
        self._callbacks.append(cb)

    # ── 后台轮询 ───────────────────────────────────────────
    async def start_polling(self):
        await self.fetch_host_config()
        await self.refresh()
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(f"[TopoManager] 轮询已启动，间隔 {settings.POLL_INTERVAL}s")

    async def stop_polling(self):
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._agent_client and not self._agent_client.is_closed:
            await self._agent_client.aclose()

    async def _poll_loop(self):
        while True:
            try:
                await self.refresh()
            except Exception as e:
                logger.error(f"[TopoManager] poll error: {e}")
            await asyncio.sleep(settings.POLL_INTERVAL)

    def get_status(self) -> Dict:
        return {
            "ryu_connected": self._ryu_connected,
            "node_count": len(self._topology.get("nodes", [])),
            "link_count": len(self._topology.get("links", [])),
            "host_count": len(self._hosts),
            "timestamp": self._topology.get("timestamp", 0),
        }


# 单例
topo_manager = TopoManager()
