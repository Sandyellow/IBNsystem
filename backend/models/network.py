from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, field_validator
from enum import Enum


# ─────────────────────────────────────────
#  网络数据模型
# ─────────────────────────────────────────

class NodeType(str, Enum):
    HOST = "host"
    SWITCH = "switch"
    CONTROLLER = "controller"


class LinkState(str, Enum):
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"


class Node(BaseModel):
    id: str
    type: NodeType
    label: str
    ip: Optional[str] = None
    mac: Optional[str] = None
    dpid: Optional[str] = None       # 交换机 datapath id
    port_count: Optional[int] = None


class Link(BaseModel):
    id: str
    source: str
    target: str
    state: LinkState = LinkState.UP
    bandwidth_mbps: Optional[float] = None
    latency_ms: Optional[float] = None
    packet_loss_pct: Optional[float] = None
    utilization_pct: Optional[float] = None


class Topology(BaseModel):
    nodes: List[Node] = []
    links: List[Link] = []
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
