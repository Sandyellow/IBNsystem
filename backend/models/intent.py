from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, model_validator
from enum import Enum


# ─────────────────────────────────────────
#  意图数据模型
# ─────────────────────────────────────────

class IntentAction(str, Enum):
    ADD_FLOW = "add_flow"
    DELETE_FLOW = "delete_flow"
    RATE_LIMIT = "rate_limit"
    BLOCK_TRAFFIC = "block_traffic"
    ALLOW_TRAFFIC = "allow_traffic"
    REDIRECT_TRAFFIC = "redirect_traffic"
    QUERY_STATS = "query_stats"
    QUERY_TOPOLOGY = "query_topology"
    PING = "ping"
    SET_PRIORITY = "set_priority"
    LOAD_BALANCE = "load_balance"


class IntentStatus(str, Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    CONFIRMED = "confirmed"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    REJECTED = "rejected"


class ParsedIntent(BaseModel):
    """LLM 解析后的结构化意图"""
    action: IntentAction
    source_node: Optional[str] = None
    target_node: Optional[str] = None
    parameters: Dict[str, Any] = {}
    explanation: str = ""

    @model_validator(mode='after')
    def validate_schema_and_params(self) -> ParsedIntent:
        action = self.action
        params = self.parameters
        
        # 1. 检查必备的 source_node
        needs_source = {
            IntentAction.ADD_FLOW, IntentAction.DELETE_FLOW,
            IntentAction.RATE_LIMIT, IntentAction.BLOCK_TRAFFIC,
            IntentAction.ALLOW_TRAFFIC, IntentAction.REDIRECT_TRAFFIC,
            IntentAction.PING, IntentAction.SET_PRIORITY,
        }
        if action in needs_source and self.source_node is None:
            raise ValueError(f"操作 {action.value} 缺少必需的 source_node")
            
        # 2. 检查特定 action 的参数范围与类型
        if action == IntentAction.RATE_LIMIT:
            bw = params.get("bandwidth_mbps")
            if bw is None:
                raise ValueError("rate_limit 操作必须提供 bandwidth_mbps 参数")
            try:
                bw = float(bw)
                self.parameters["bandwidth_mbps"] = bw
            except (ValueError, TypeError):
                raise ValueError("bandwidth_mbps 必须是数字类型")
            if not (0.1 <= bw <= 10000):
                raise ValueError(f"bandwidth_mbps ({bw}) 必须在 0.1 到 10000 之间")
                
        elif action == IntentAction.SET_PRIORITY:
            pri = params.get("priority")
            if pri is None:
                raise ValueError("set_priority 操作必须提供 priority 参数")
            try:
                pri = int(pri)
                self.parameters["priority"] = pri
            except (ValueError, TypeError):
                raise ValueError("priority 必须是整数类型")
            if not (1 <= pri <= 65535):
                raise ValueError(f"priority ({pri}) 必须在 1 到 65535 之间")
                
        elif action == IntentAction.REDIRECT_TRAFFIC:
            via = params.get("via_node")
            if via is None:
                raise ValueError("redirect_traffic 操作必须提供 via_node 参数")
            if not isinstance(via, str):
                raise ValueError("via_node 必须是字符串类型")
                
        return self


class IntentRequest(BaseModel):
    """用户输入的自然语言意图"""
    text: str
    session_id: Optional[str] = None


class ValidationLayer(str, Enum):
    TOPOLOGY_VERIFICATION = "topology_verification"
    SECURITY_POLICY = "security_policy"
    CONFLICT_DETECTION = "conflict_detection"


class ValidationResult(BaseModel):
    """单层验证结果"""
    layer: ValidationLayer
    passed: bool
    message: str = ""
    details: Dict[str, Any] = {}


class IntentValidationReport(BaseModel):
    """完整验证报告"""
    overall_passed: bool
    layers: List[ValidationResult] = []
    requires_confirmation: bool = False
    risk_level: str = "low"    # low / medium / high / critical


class IntentRecord(BaseModel):
    """完整意图处理记录"""
    id: str
    user_text: str
    parsed_intent: Optional[ParsedIntent] = None
    validation_report: Optional[IntentValidationReport] = None
    status: IntentStatus = IntentStatus.PENDING
    llm_retries: int = 0
    execution_result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0
