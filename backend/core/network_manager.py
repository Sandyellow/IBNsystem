"""
网络状态管理器 — 维护全局网络视图，轮询 VM 状态，检测网络异常
异常类型：链路断开、高延迟、丢包率过高、带宽超限、负载不均衡
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from config import settings
from models.network import Topology, Node, Link, NodeType, LinkState, NetworkStats
from core.vm_connector import vm_connector

logger = logging.getLogger(__name__)

# ─── 告警阈值 ───────────────────────────────────────────────────
THRESHOLDS = {
    "latency_ms": 100.0,          # 延迟告警阈值
    "packet_loss_pct": 5.0,        # 丢包率告警阈值
    "utilization_pct": 80.0,       # 带宽利用率告警阈值
    "load_imbalance_pct": 30.0,    # 负载不均衡差异阈值
}

# 同类告警最小间隔（秒）—— 防抖冷却
_ALERT_COOLDOWN_SEC = 120

# 负载不均衡告警：上次告警后差异必须变化超过该阈值才重新告警
_IMBALANCE_CHANGE_THRESHOLD = 5.0


class Alert:
    def __init__(self, alert_type: str, severity: str, message: str, details: Dict):
        self.id = f"alert_{int(time.time() * 1000)}"
        self.type = alert_type
        self.severity = severity       # info / warning / critical
        self.message = message
        self.details = details
        self.timestamp = time.time()
        self.resolved = False

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": self.type,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
            "resolved": self.resolved,
        }


class NetworkManager:
    def __init__(self):
        self.topology: Topology = Topology()
        self.stats: NetworkStats = NetworkStats()
        self.alerts: List[Alert] = []
        self.vm_connected: bool = False
        self._poll_task: Optional[asyncio.Task] = None
        self._alert_callbacks: List[Callable] = []
        self._topology_callbacks: List[Callable] = []
        # 告警防抖状态
        self._active_anomalies: set = set()
        # key → 上次告警时刻（冷却用）
        self._alert_cooldown: Dict[str, float] = {}
        # 负载不均衡：上次告警时的差异値
        self._last_imbalance_gap: float = 0.0

    # ─── 订阅机制（WebSocket 推送用）────────────────────
    def on_alert(self, callback: Callable):
        self._alert_callbacks.append(callback)

    def on_topology_update(self, callback: Callable):
        self._topology_callbacks.append(callback)

    async def _notify_alert(self, alert: Alert):
        for cb in self._alert_callbacks:
            try:
                await cb(alert.to_dict())
            except Exception as e:
                logger.error(f"Alert callback error: {e}")

    async def _notify_topology(self):
        data = self.get_topology_dict()
        for cb in self._topology_callbacks:
            try:
                await cb(data)
            except Exception as e:
                logger.error(f"Topology callback error: {e}")

    # ─── 数据获取 ─────────────────────────────────────────
    async def refresh_topology(self):
        """从 VM Agent 刷新拓扑数据"""
        raw = await vm_connector.get_topology()
        if "error" in raw and not raw.get("nodes"):
            self.vm_connected = False
            return

        self.vm_connected = True
        old_links = {l.id: l.state for l in self.topology.links}

        nodes = [Node(**n) for n in raw.get("nodes", [])]
        links = [Link(**l) for l in raw.get("links", [])]
        self.topology = Topology(
            nodes=nodes,
            links=links,
            timestamp=time.time(),
        )

        # 检测链路状态变化
        for link in links:
            prev_state = old_links.get(link.id)
            if prev_state and prev_state != link.state:
                if link.state == LinkState.DOWN:
                    alert = Alert(
                        "LINK_DOWN", "critical",
                        f"链路断开: {link.source} ↔ {link.target}",
                        {"link_id": link.id, "source": link.source, "target": link.target},
                    )
                    self.alerts.append(alert)
                    await self._notify_alert(alert)
                elif link.state == LinkState.UP and prev_state == LinkState.DOWN:
                    alert = Alert(
                        "LINK_RESTORED", "info",
                        f"链路恢复: {link.source} ↔ {link.target}",
                        {"link_id": link.id},
                    )
                    self.alerts.append(alert)
                    await self._notify_alert(alert)

        await self._notify_topology()

    async def refresh_stats(self):
        """刷新统计信息并检测异常"""
        raw_stats = await vm_connector.get_stats()
        raw_links = await vm_connector.get_link_stats()

        # 更新链路指标
        link_map = {l.id: l for l in self.topology.links}
        updated = False
        for ldata in raw_links.get("links", []):
            lid = ldata.get("id", "")
            if lid in link_map:
                link = link_map[lid]
                link.latency_ms = ldata.get("latency_ms")
                link.packet_loss_pct = ldata.get("packet_loss_pct")
                link.utilization_pct = ldata.get("utilization_pct")
                updated = True

        # 有更新则推送含统计字段的拓扑（前端显示延迟/利用率依赖此推送）
        if updated:
            await self._notify_topology()

        # 检测网络异常
        await self._detect_anomalies()


    async def _detect_anomalies(self):
        utilizations = []
        current_anomalies: set = set()
        now = time.time()

        def _can_alert(key: str) -> bool:
            """检查该 key 是否已过冷却期"""
            last = self._alert_cooldown.get(key, 0.0)
            return (now - last) >= _ALERT_COOLDOWN_SEC

        def _record_alert(key: str):
            self._alert_cooldown[key] = now

        for link in self.topology.links:
            if link.state == LinkState.DOWN:
                continue

            if link.latency_ms and link.latency_ms > THRESHOLDS["latency_ms"]:
                key = f"latency_{link.id}"
                current_anomalies.add(key)
                if key not in self._active_anomalies and _can_alert(key):
                    alert = Alert(
                        "HIGH_LATENCY", "warning",
                        f"高延迟告警: {link.source}↔{link.target} = {link.latency_ms:.1f}ms",
                        {"link_id": link.id, "latency_ms": link.latency_ms},
                    )
                    self.alerts.append(alert)
                    await self._notify_alert(alert)
                    _record_alert(key)

            if link.packet_loss_pct and link.packet_loss_pct > THRESHOLDS["packet_loss_pct"]:
                key = f"loss_{link.id}"
                current_anomalies.add(key)
                if key not in self._active_anomalies and _can_alert(key):
                    alert = Alert(
                        "PACKET_LOSS", "warning",
                        f"丢包告警: {link.source}↔{link.target} = {link.packet_loss_pct:.1f}%",
                        {"link_id": link.id, "packet_loss_pct": link.packet_loss_pct},
                    )
                    self.alerts.append(alert)
                    await self._notify_alert(alert)
                    _record_alert(key)

            if link.utilization_pct is not None:
                utilizations.append(link.utilization_pct)
                if link.utilization_pct > THRESHOLDS["utilization_pct"]:
                    key = f"bw_{link.id}"
                    current_anomalies.add(key)
                    if key not in self._active_anomalies and _can_alert(key):
                        alert = Alert(
                            "BANDWIDTH_EXCEED", "warning",
                            f"带宽超限: {link.source}↔{link.target} = {link.utilization_pct:.1f}%",
                            {"link_id": link.id, "utilization_pct": link.utilization_pct},
                        )
                        self.alerts.append(alert)
                        await self._notify_alert(alert)
                        _record_alert(key)

        # 负载均衡检测：差异超阈値 且 (首次触发 或 差异变化超过_IMBALANCE_CHANGE_THRESHOLD)
        if len(utilizations) >= 2:
            max_u = max(utilizations)
            min_u = min(utilizations)
            gap = max_u - min_u
            if gap > THRESHOLDS["load_imbalance_pct"]:
                key = "load_imbalance"
                current_anomalies.add(key)
                gap_delta = abs(gap - self._last_imbalance_gap)
                first_trigger = key not in self._active_anomalies
                if (first_trigger or gap_delta >= _IMBALANCE_CHANGE_THRESHOLD) and _can_alert(key):
                    alert = Alert(
                        "LOAD_IMBALANCE", "warning",
                        f"负载不均衡: 最高 {max_u:.1f}% vs 最低 {min_u:.1f}%",
                        {"max_utilization": max_u, "min_utilization": min_u},
                    )
                    self.alerts.append(alert)
                    await self._notify_alert(alert)
                    _record_alert(key)
                    self._last_imbalance_gap = gap

        # 清理已恢复的异常状态 + 更新活跃集
        self._active_anomalies = current_anomalies

        # 保留最近 100 条告警
        self.alerts = self.alerts[-100:]

    # ─── 后台轮询 ─────────────────────────────────────────
    async def start_polling(self):
        """启动后台状态轮询"""
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(f"NetworkManager: 轮询已启动，间隔 {settings.POLL_INTERVAL}s")

    async def stop_polling(self):
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self):
        while True:
            try:
                await self.refresh_topology()
                await self.refresh_stats()
            except Exception as e:
                logger.error(f"Poll loop error: {e}")
            await asyncio.sleep(settings.POLL_INTERVAL)

    # ─── 对外接口 ─────────────────────────────────────────
    def get_topology_dict(self) -> Dict:
        return self.topology.model_dump()

    def get_alerts(self, limit: int = 50) -> List[Dict]:
        return [a.to_dict() for a in reversed(self.alerts[-limit:])]

    def get_status(self) -> Dict:
        return {
            "vm_connected": self.vm_connected,
            "node_count": len(self.topology.nodes),
            "link_count": len(self.topology.links),
            "active_alerts": sum(1 for a in self.alerts if not a.resolved),
            "timestamp": self.topology.timestamp,
        }


# 单例
network_manager = NetworkManager()
