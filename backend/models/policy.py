from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from enum import Enum
import time

from models.intent import IntentAction


class PolicyType(str, Enum):
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


class ActivePolicy(BaseModel):
    """记录 IBN 系统当前已下发的自定义策略"""
    id: str                           # intent_id（唯一标识）
    policy_type: PolicyType
    
    # 匹配范围相关
    scope: str = "specific"
    source_nodes: List[str] = []
    target_nodes: List[str] = []
    exclude_nodes: List[str] = []
    target_switch: Optional[str] = None
    
    intent_action: Optional[IntentAction] = None  # 原始的 IntentAction 类型（用于重建流表分发）
    action_params: Dict[str, Any] = {}   # 保存原始完整参数
    match: Optional[Dict[str, Any]] = None # 保存完整的高级匹配条件
    
    description: str = ""
    ryu_cookies: List[int] = []       # 关联的 Ryu flow cookie，用于精准删除
    meter_ids: List[int] = []         # 关联的 Meter ID
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
