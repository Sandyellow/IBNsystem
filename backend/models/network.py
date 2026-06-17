"""网络拓扑数据模型"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, field_validator
from enum import Enum


class NodeType(str, Enum):
    """拓扑节点类型"""
    HOST = "host"
    SWITCH = "switch"
    CONTROLLER = "controller"


class LinkState(str, Enum):
    """链路状态"""
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"


class Node(BaseModel):
    """拓扑节点"""
    id: str
    type: NodeType
    label: str
    ip: Optional[str] = None
    mac: Optional[str] = None
    dpid: Optional[str] = None
    port_count: Optional[int] = None


class Link(BaseModel):
    """拓扑链路"""
    id: str
    source: str
    target: str
    state: LinkState = LinkState.UP
    bandwidth_mbps: Optional[float] = None
    latency_ms: Optional[float] = None
    packet_loss_pct: Optional[float] = None
    utilization_pct: Optional[float] = None
    src_port: Optional[int] = None
    dst_port: Optional[int] = None


class Topology(BaseModel):
    """网络拓扑"""
    nodes: List[Node] = []
    links: List[Link] = []
    timestamp: float = 0.0


class PortStats(BaseModel):
    """端口统计"""
    port_no: int
    rx_packets: int = 0
    tx_packets: int = 0
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_errors: int = 0
    tx_errors: int = 0


class SwitchStats(BaseModel):
    """交换机统计"""
    dpid: str
    ports: List[PortStats] = []


class NetworkStats(BaseModel):
    """网络统计汇总"""
    switches: List[SwitchStats] = []
    timestamp: float = 0.0


class PortStats(BaseModel):
    port_no: int
    rx_packets: int = 0
    tx_packets: int = 0
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_errors: int = 0
    tx_errors: int = 0


class SwitchStats(BaseModel):
    dpid: str
    ports: List[PortStats] = []


class NetworkStats(BaseModel):
    switches: List[SwitchStats] = []
    timestamp: float = 0.0
