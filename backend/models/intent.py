"""意图模型 — 定义意图解析、验证、执行所需的 Pydantic 数据模型"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Union, Literal
from pydantic import BaseModel, Field
from enum import Enum


class IntentAction(str, Enum):
    """网络意图操作类型枚举"""
    QUERY_TOPOLOGY   = "query_topology"
    QUERY_FLOWS      = "query_flows"
    QUERY_PORT_STATS = "query_port_stats"
    BLOCK_TRAFFIC    = "block_traffic"
    ALLOW_TRAFFIC    = "allow_traffic"
    RATE_LIMIT       = "rate_limit"
    SET_PRIORITY     = "set_priority"
    CLEAR_FLOWS      = "clear_flows"
    ACL              = "acl"
    QOS_MARK         = "qos_mark"
    VLAN             = "vlan"
    MULTIPATH        = "multipath"


class IntentScope(str, Enum):
    """策略作用范围：特定节点或全网"""
    SPECIFIC = "specific"
    ALL = "all"


class IntentStatus(str, Enum):
    """意图处理生命周期状态"""
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
    """限速参数"""
    bandwidth_mbps: float = Field(..., description="限制带宽，单位Mbps")

class SetPriorityParams(BaseModel):
    """优先级参数"""
    priority: int = Field(..., description="流表优先级")

class QosMarkParams(BaseModel):
    """QoS 标记参数"""
    dscp: int = Field(..., description="要标记的DSCP值 (0-63)")

class VlanParams(BaseModel):
    """VLAN 划分参数"""
    vlan_id: int = Field(..., description="VLAN ID")

class MultipathParams(BaseModel):
    """多路径负载均衡参数（当前无额外参数）"""
    pass


ActionParams = Union[
    RateLimitParams,
    SetPriorityParams,
    QosMarkParams,
    VlanParams,
    MultipathParams,
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
    """澄清选项"""
    label: str = Field(description="选项简短标签，如 '选项A'")
    description: str = Field(description="选项的详细描述")
    suggested_input: str = Field(description="用户如果选择此项，应该输入的精确指令")

class ClarificationNeeded(BaseModel):
    """当用户指令语义模糊时调用，返回澄清选项"""
    reason: str = Field(description="解释为什么需要澄清（存在什么歧义）")
    options: List[ClarificationOption] = Field(description="提供给用户的几种可能选项")


class IntentRequest(BaseModel):
    """用户输入的自然语言意图请求"""
    text: str
    session_id: Optional[str] = None


class IntentRecord(BaseModel):
    """完整意图处理记录"""
    id: str
    user_text: str
    parsed_intents: List[ParsedIntent] = Field(default_factory=list)
    parsed_intent: Optional[ParsedIntent] = None
    status: IntentStatus = IntentStatus.PENDING
    llm_retries: int = 0
    execution_result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0


class ValidationLayer(str, Enum):
    """验证层级枚举"""
    TOPOLOGY_VERIFICATION = "topology_verification"
    SECURITY_POLICY = "security_policy"
    CONFLICT_DETECTION = "conflict_detection"


class ConflictSeverity(str, Enum):
    """冲突严重程度枚举"""
    DUPLICATE = "duplicate"
    OVERRIDE = "override"
    MUTUALLY_EXCLUSIVE = "mutually_exclusive"


class ConflictInfo(BaseModel):
    """策略冲突信息"""
    policy_id: str
    severity: ConflictSeverity
    description: str
    existing_action: Optional[str] = None
    existing_parameters: Dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    """单层验证结果"""
    layer: ValidationLayer
    passed: bool
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    conflicts: List[ConflictInfo] = Field(default_factory=list)

class IntentValidationReport(BaseModel):
    """意图验证综合报告"""
    overall_passed: bool
    layers: List[ValidationResult]
    requires_confirmation: bool = False
    risk_level: str = "low"
