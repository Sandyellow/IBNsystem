from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from enum import Enum


class IntentAction(str, Enum):
    # 查询类
    QUERY_TOPOLOGY   = "query_topology"
    QUERY_FLOWS      = "query_flows"
    QUERY_PORT_STATS = "query_port_stats"
    # 控制类
    BLOCK_TRAFFIC    = "block_traffic"
    ALLOW_TRAFFIC    = "allow_traffic"
    RATE_LIMIT       = "rate_limit"
    SET_PRIORITY     = "set_priority"
    REDIRECT_TRAFFIC = "redirect_traffic"
    CLEAR_FLOWS      = "clear_flows"
    ADD_FLOW         = "add_flow"
    DELETE_FLOW      = "delete_flow"
    LOAD_BALANCE     = "load_balance"


class IntentStatus(str, Enum):
    PENDING   = "pending"
    PARSING   = "parsing"
    EXECUTING = "executing"
    SUCCESS   = "success"
    FAILED    = "failed"


from pydantic import BaseModel, Field

class ParsedIntent(BaseModel):
    """LLM 解析后的结构化意图"""
    action: IntentAction = Field(description="需要执行的网络操作指令")
    source_node: Optional[str] = Field(None, description="源节点名称，如 'h1'。如果没有指定，则为 None")
    target_node: Optional[str] = Field(None, description="目标节点名称，如 'h3'。如果没有指定，则为 None")
    target_switch: Optional[str] = Field(None, description="目标交换机，如 's1'。如果没有指定，则为 None")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="执行该操作所需的额外参数字典，例如 {'bandwidth_mbps': 5, 'via_node': 's2', 'priority': 100}")
    explanation: str = Field("", description="一句话中文解释你对用户意图的理解")


class IntentRequest(BaseModel):
    """用户输入的自然语言意图"""
    text: str
    session_id: Optional[str] = None


class IntentRecord(BaseModel):
    """完整意图处理记录"""
    id: str
    user_text: str
    parsed_intent: Optional[ParsedIntent] = None
    status: IntentStatus = IntentStatus.PENDING
    llm_retries: int = 0
    execution_result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0

class ValidationLayer(str, Enum):
    TOPOLOGY_VERIFICATION = "topology_verification"
    SECURITY_POLICY = "security_policy"
    CONFLICT_DETECTION = "conflict_detection"

class ValidationResult(BaseModel):
    layer: ValidationLayer
    passed: bool
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)

class IntentValidationReport(BaseModel):
    overall_passed: bool
    layers: List[ValidationResult]
    requires_confirmation: bool = False
    risk_level: str = "low"
