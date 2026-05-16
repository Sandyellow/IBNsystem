from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
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
    confidence: float = 0.0
    explanation: str = ""


class IntentRequest(BaseModel):
    """用户输入的自然语言意图"""
    text: str
    session_id: Optional[str] = None


class ValidationLayer(str, Enum):
    SCHEMA = "schema"
    ACTION_WHITELIST = "action_whitelist"
    NODE_EXISTENCE = "node_existence"
    PARAM_RANGE = "param_range"
    SAFETY = "safety"
    CONFLICT = "conflict"


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
