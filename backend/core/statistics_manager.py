"""
后台端口流量采集与统计。

定时拉取各交换机的端口计数，计算实时速率并维护近期历史数据。
"""

import asyncio
import logging
import time
from datetime import datetime
from collections import deque, defaultdict
from typing import Dict, List, Any

from core.ryu_client import ryu_client
from core.topology_manager import topo_manager

logger = logging.getLogger(__name__)

# 保留最近 40 个数据点（约 2 分钟历史，轮询间隔 3s）
MAX_HISTORY_LEN = 40

class StatsManager:
    """端口流量统计管理器，定时采集各交换机端口速率并维护历史数据"""

    def __init__(self):
        # 结构: { dpid_str: deque([ { time: 'HH:MM:SS', '1_rx': 1024, '1_tx': 512, ... } ]) }
        self._history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY_LEN))
        
        # 保存上一次的绝对计数器值: { dpid_str: { port_no: { 'rx': int, 'tx': int, 'ts': float } } }
        self._prev_counters: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(dict)
        
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start_polling(self, interval: float = 3.0):
        """启动后台流量统计轮询"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(interval))
        logger.info(f"[StatsManager] 已启动端口流量历史采集，轮询间隔: {interval}s")

    async def stop_polling(self):
        """停止后台流量统计轮询"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[StatsManager] 端口流量历史采集已停止")

    async def _poll_loop(self, interval: float):
        """后台轮询循环：定时采集各交换机端口速率"""
        while self._running:
            try:
                dpids = topo_manager.get_all_switch_dpids()
                if dpids:
                    now = time.time()
                    time_str = datetime.now().strftime("%H:%M:%S")
                    
                    for dpid in dpids:
                        dpid_str = str(dpid)
                        stats = await ryu_client.get_port_stats(dpid)
                        
                        point_data = {"time": time_str}
                        
                        for port_stat in stats:
                            port_no = port_stat.get("port_no")
                            if port_no is None or port_no == "LOCAL" or port_no > 100000:
                                # 过滤内部接口
                                continue
                            
                            rx_bytes = port_stat.get("rx_bytes", 0)
                            tx_bytes = port_stat.get("tx_bytes", 0)
                            
                            prev = self._prev_counters[dpid_str].get(port_no)
                            if prev:
                                dt = now - prev["ts"]
                                if dt > 0:
                                    rx_rate = max(0, (rx_bytes - prev["rx"]) / dt)
                                    tx_rate = max(0, (tx_bytes - prev["tx"]) / dt)
                                else:
                                    rx_rate = 0
                                    tx_rate = 0
                                # 转换为 Kbps (千比特/秒)
                                point_data[f"{port_no}_rx"] = round((rx_rate * 8) / 1000, 3)
                                point_data[f"{port_no}_tx"] = round((tx_rate * 8) / 1000, 3)
                            else:
                                point_data[f"{port_no}_rx"] = 0
                                point_data[f"{port_no}_tx"] = 0

                            # 更新上一次计数器
                            self._prev_counters[dpid_str][port_no] = {
                                "rx": rx_bytes,
                                "tx": tx_bytes,
                                "ts": now
                            }
                            
                        # 如果没有端口数据，跳过
                        if len(point_data) > 1:
                            self._history[dpid_str].append(point_data)
            except Exception as e:
                logger.warning(f"[StatsManager] 采集流量历史时出错: {e}")
            
            await asyncio.sleep(interval)

    def get_history(self) -> Dict[str, List[Dict[str, Any]]]:
        """返回所有交换机的端口历史速率数据，格式 { '1': [{time, 1_rx, 1_tx...}], ... }"""
        return {dpid: list(dq) for dpid, dq in self._history.items()}

stats_manager = StatsManager()
