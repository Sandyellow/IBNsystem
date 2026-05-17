from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from enum import Enum


# ─────────────────────────────────────────
#  策略数据模型
# ─────────────────────────────────────────

class PolicyType(str, Enum):
    FLOW_RULE = "flow_rule"
    METER = "meter"
    GROUP = "group"
    MININET_CMD = "mininet_cmd"


class FlowMatch(BaseModel):
    in_port: Optional[int] = None
    eth_src: Optional[str] = None
    eth_dst: Optional[str] = None
    ipv4_src: Optional[str] = None
    ipv4_dst: Optional[str] = None
    ip_proto: Optional[int] = None
    tcp_src: Optional[int] = None
    tcp_dst: Optional[int] = None


class FlowAction(BaseModel):
    type: str                         # output / meter / drop / set_field
    value: Optional[Any] = None


class NetworkPolicy(BaseModel):
    """最终要下发到 Ryu 的网络策略"""
    policy_type: PolicyType
    dpid: str                         # 交换机 datapath id
    priority: int = 100
    match: FlowMatch = FlowMatch()
    actions: List[FlowAction] = []
    idle_timeout: int = 0
    hard_timeout: int = 0
    # Meter 相关
    meter_id: Optional[int] = None
    rate_kbps: Optional[int] = None
    # Mininet 相关
    command: Optional[str] = None
    description: str = ""
    intent_id: str = ""               # 关联的意图 ID


class PolicyExecutionResult(BaseModel):
    success: bool
    policy: NetworkPolicy
    response: Dict[str, Any] = {}
    error: Optional[str] = None
    rollback_available: bool = False
    rollback_policy: Optional[NetworkPolicy] = None
