from __future__ import annotations
from typing import Any, Dict, List, Optional, Union, Literal
from pydantic import BaseModel, Field
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
    # 扩展业务能力
    ACL              = "acl"
    QOS_MARK         = "qos_mark"
    PORT_MIRROR      = "port_mirror"
    VLAN             = "vlan"
    MONITOR_ALERT    = "monitor_alert"


class IntentScope(str, Enum):
    SPECIFIC = "specific"
    ALL = "all"


class IntentStatus(str, Enum):
    PENDING   = "pending"
    PARSING   = "parsing"
    EXECUTING = "executing"
    SUCCESS   = "success"
    FAILED    = "failed"
    CLARIFICATION = "clarification"
    CHAT      = "chat"


class MatchCondition(BaseModel):
    """精细化流表匹配条件"""
    eth_type: Optional[int] = Field(None, description="以太网类型，如 0x0800 (IPv4)")
    ip_proto: Optional[int] = Field(None, description="IP协议号，如 6 (TCP), 17 (UDP), 1 (ICMP)")
    tcp_src: Optional[int] = Field(None, description="TCP源端口")
    tcp_dst: Optional[int] = Field(None, description="TCP目的端口")
    udp_src: Optional[int] = Field(None, description="UDP源端口")
    udp_dst: Optional[int] = Field(None, description="UDP目的端口")
    dscp: Optional[int] = Field(None, description="DSCP优先级值 (0-63)")


class RateLimitParams(BaseModel):
    bandwidth_mbps: float = Field(..., description="限制带宽，单位Mbps")

class SetPriorityParams(BaseModel):
    priority: int = Field(..., description="流表优先级")

class RedirectTrafficParams(BaseModel):
    via_switch: str = Field(..., description="中转交换机名称，如 's2'")

class QosMarkParams(BaseModel):
    dscp: int = Field(..., description="要标记的DSCP值 (0-63)")

class PortMirrorParams(BaseModel):
    mirror_to_port: str = Field(..., description="镜像流量的目的端口或主机名称")

class VlanParams(BaseModel):
    vlan_id: int = Field(..., description="VLAN ID")

class MonitorAlertParams(BaseModel):
    threshold_kbps: float = Field(..., description="流量告警阈值 (Kbps)")

# 为简化大模型输出，使用 Union，Pydantic 会自动尝试匹配
ActionParams = Union[
    RateLimitParams,
    SetPriorityParams,
    RedirectTrafficParams,
    QosMarkParams,
    PortMirrorParams,
    VlanParams,
    MonitorAlertParams,
    Dict[str, Any]
]


class ParsedIntent(BaseModel):
    """LLM 解析后的结构化意图"""
    action: IntentAction = Field(description="需要执行的网络操作指令")
    scope: IntentScope = Field(default=IntentScope.SPECIFIC, description="作用范围：specific(特定节点) 或 all(所有节点)")
    source_nodes: List[str] = Field(default_factory=list, description="源节点名称列表，如 ['h1', 'h2']。若 scope 为 all，此处可为空。")
    target_nodes: List[str] = Field(default_factory=list, description="目标节点名称列表，如 ['h3']。若 scope 为 all，此处可为空。")
    exclude_nodes: List[str] = Field(default_factory=list, description="需要排除的节点名称列表，如 ['h2']")
    direction: Literal["bidirectional", "unidirectional"] = Field(default="bidirectional", description="策略方向：双向(bidirectional)或单向(unidirectional)。默认为双向。")
    target_switch: Optional[str] = Field(None, description="特定针对的交换机，如 's1'")
    
    match: Optional[MatchCondition] = Field(None, description="可选的高级匹配条件（五元组等）")
    action_params: ActionParams = Field(default_factory=dict, description="特定操作的结构化参数，如 bandwidth_mbps, via_switch, dscp, vlan_id 等")
    intent_priority: Optional[int] = Field(None, description="指定该规则的底层下发优先级（覆盖默认值）")
    
    explanation: str = Field("", description="一句话中文解释你对本条意图的理解")


class ClarificationOption(BaseModel):
    label: str = Field(description="选项简短标签，如 '选项A'")
    description: str = Field(description="选项的详细描述")
    suggested_input: str = Field(description="用户如果选择此项，应该输入的精确指令")

class ClarificationNeeded(BaseModel):
    """当用户指令语义模糊（例如方向不明、范围不清）时调用此工具，返回澄清选项"""
    reason: str = Field(description="解释为什么需要澄清（存在什么歧义）")
    options: List[ClarificationOption] = Field(description="提供给用户的几种可能选项")


class IntentRequest(BaseModel):
    """用户输入的自然语言意图"""
    text: str
    session_id: Optional[str] = None


class IntentRecord(BaseModel):
    """完整意图处理记录"""
    id: str
    user_text: str
    parsed_intents: List[ParsedIntent] = Field(default_factory=list) # 改造为列表，支持复合指令
    parsed_intent: Optional[ParsedIntent] = None # 保留此字段用于向后兼容或展示主意图
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


class ConflictSeverity(str, Enum):
    DUPLICATE = "duplicate"
    OVERRIDE = "override"
    MUTUALLY_EXCLUSIVE = "mutually_exclusive"


class ConflictInfo(BaseModel):
    policy_id: str
    severity: ConflictSeverity
    description: str
    existing_action: Optional[str] = None
    existing_parameters: Dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    layer: ValidationLayer
    passed: bool
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    conflicts: List[ConflictInfo] = Field(default_factory=list)

class IntentValidationReport(BaseModel):
    overall_passed: bool
    layers: List[ValidationResult]
    requires_confirmation: bool = False
    risk_level: str = "low"
