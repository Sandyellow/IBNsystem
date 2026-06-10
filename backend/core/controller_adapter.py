import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from enum import Enum

logger = logging.getLogger(__name__)

class PrimitiveType(str, Enum):
    FLOW_ENTRY = "flow_entry"
    GROUP_ENTRY = "group_entry"
    METER_ENTRY = "meter_entry"

class NetworkPrimitive(BaseModel):
    """
    网络原语抽象：业务层只负责构造网络原语，适配器负责将其翻译并下发到对应控制器。
    """
    primitive_type: PrimitiveType
    dpid: int
    cookie: Optional[int] = None
    priority: int = 0
    match: Dict[str, Any] = {}
    actions: List[Dict[str, Any]] = []  # 抽象动作描述
    extra: Dict[str, Any] = {}          # 特定原语（如 Meter）的额外参数

class ControllerAdapter(ABC):
    """
    SDN 控制器适配器抽象基类
    """

    @abstractmethod
    async def connect(self):
        """建立控制器连接"""
        pass

    @abstractmethod
    async def close(self):
        """关闭连接"""
        pass

    @abstractmethod
    async def ping(self) -> bool:
        """测试控制器连通性"""
        pass

    # ── 拓扑 ──────────────────────────────────────────────
    @abstractmethod
    async def get_topology_switches(self) -> List[Dict]:
        pass

    @abstractmethod
    async def get_topology_links(self) -> List[Dict]:
        pass

    @abstractmethod
    async def get_topology_hosts(self) -> List[Dict]:
        pass

    @abstractmethod
    async def get_switch_dpids(self) -> List[int]:
        pass

    # ── 原语操作 ──────────────────────────────────────────
    @abstractmethod
    async def apply_primitive(self, primitive: NetworkPrimitive) -> bool:
        """下发网络原语"""
        pass

    @abstractmethod
    async def delete_primitive(self, primitive: NetworkPrimitive) -> bool:
        """删除网络原语"""
        pass

    @abstractmethod
    async def delete_flows_by_cookie(self, dpid: int, cookie: int) -> bool:
        """按 Cookie 批量删除流表"""
        pass

    # ── 统计信息 ──────────────────────────────────────────
    @abstractmethod
    async def get_flows(self, dpid: int) -> List[Dict]:
        pass

    @abstractmethod
    async def get_port_stats(self, dpid: int) -> List[Dict]:
        pass

    @abstractmethod
    async def get_port_desc(self, dpid: int) -> List[Dict]:
        pass
