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
    PING_TEST        = "ping_test"
    CLEAR_FLOWS      = "clear_flows"


class IntentStatus(str, Enum):
    PENDING   = "pending"
    PARSING   = "parsing"
    EXECUTING = "executing"
    SUCCESS   = "success"
    FAILED    = "failed"


class ParsedIntent(BaseModel):
    """LLM 解析后的结构化意图"""
    action: IntentAction
    src_host: Optional[str] = None        # 源主机名，如 "h1"
    dst_host: Optional[str] = None        # 目标主机名，如 "h3"
    target_switch: Optional[str] = None   # 目标交换机，如 "s1"
    parameters: Dict[str, Any] = {}
    explanation: str = ""


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
