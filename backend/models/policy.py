from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from enum import Enum
import time


class PolicyType(str, Enum):
    BLOCK      = "block"
    RATE_LIMIT = "rate_limit"
    REDIRECT   = "redirect"
    PRIORITY   = "priority"


class ActivePolicy(BaseModel):
    """记录 IBN 系统当前已下发的自定义策略"""
    id: str                           # intent_id（唯一标识）
    policy_type: PolicyType
    src_host: Optional[str] = None
    dst_host: Optional[str] = None
    description: str = ""
    ryu_cookies: List[int] = []       # 关联的 Ryu flow cookie，用于精准删除
    meter_ids: List[int] = []         # 关联的 Meter ID
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
