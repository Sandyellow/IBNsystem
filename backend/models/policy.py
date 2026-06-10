"""策略模型 — 定义活跃策略的 Pydantic 数据模型与策略类型枚举"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from enum import Enum
import time

from models.intent import IntentAction


class PolicyType(str, Enum):
    """策略类型枚举"""
    BLOCK      = "block"
    ALLOW      = "allow"
    RATE_LIMIT = "rate_limit"
    REDIRECT   = "redirect"
    PRIORITY   = "priority"
    ACL        = "acl"
    QOS_MARK   = "qos_mark"
    PORT_MIRROR= "port_mirror"
    VLAN       = "vlan"
    MONITOR    = "monitor"
    MULTIPATH  = "multipath"


class ActivePolicy(BaseModel):
    """记录 IBN 系统当前已下发的自定义策略"""
    id: str
    policy_type: PolicyType
    scope: str = "specific"
    source_nodes: List[str] = []
    target_nodes: List[str] = []
    exclude_nodes: List[str] = []
    target_switch: Optional[str] = None
    intent_action: Optional[IntentAction] = None
    action_params: Dict[str, Any] = {}
    match: Optional[Dict[str, Any]] = None
    description: str = ""
    ryu_cookies: List[int] = []
    meter_ids: List[int] = []
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
