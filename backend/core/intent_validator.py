"""
意图策略验证器 — 负责网络状态策略层面的真正校验
三层核心验证：拓扑验证 (TOPOLOGY) -> 安全策略 (SECURITY) -> 冲突检测 (CONFLICT)
"""
from __future__ import annotations
import logging
from typing import Dict, Any, List, Union

from models.intent import (
    ParsedIntent, IntentAction, IntentValidationReport,
    ValidationResult, ValidationLayer,
)
from models.network import Topology as TopologyModel

Topology = Union[Dict[str, Any], TopologyModel]

logger = logging.getLogger(__name__)

# ─── 高危操作（需要用户二次确认）────────────────────────────────────────────
HIGH_RISK_ACTIONS = {IntentAction.DELETE_FLOW, IntentAction.BLOCK_TRAFFIC}

# 绝对禁止的参数组合（安全红线）
FORBIDDEN_COMBOS = [
    # source=None + target=None + action=block_traffic → 可能封锁所有流量
    lambda i: i.action == IntentAction.BLOCK_TRAFFIC and i.source_node is None and i.target_node is None,
    # delete_flow 无任何 match 条件 → 危险的全清流表
    lambda i: i.action == IntentAction.DELETE_FLOW and i.source_node is None and i.target_node is None,
]


class IntentValidator:

    async def validate(
        self,
        intent: ParsedIntent,
        topology: Topology,
    ) -> IntentValidationReport:
        layers: List[ValidationResult] = []

        # ── Layer 1: Topology Verification (拓扑节点验证及连通性)
        l1 = self._validate_topology_verification(intent, topology)
        layers.append(l1)

        # ── Layer 2: Security Policy (安全红线验证)
        l2 = self._validate_security_policy(intent)
        layers.append(l2)

        # ── Layer 3: Conflict Detection (策略冲突检测)
        l3 = self._validate_conflict_detection(intent)
        layers.append(l3)

        overall_passed = all(l.passed for l in layers)
        requires_confirmation = intent.action in HIGH_RISK_ACTIONS and overall_passed

        risk_level = "low"
        if intent.action in HIGH_RISK_ACTIONS:
            risk_level = "high"
        elif not l1.passed:
            risk_level = "medium"

        report = IntentValidationReport(
            overall_passed=overall_passed,
            layers=layers,
            requires_confirmation=requires_confirmation,
            risk_level=risk_level,
        )
        logger.info(
            f"[Validator] action={intent.action} passed={overall_passed} "
            f"risk={risk_level} confirm={requires_confirmation}"
        )
        return report

    def _validate_topology_verification(self, intent: ParsedIntent, topology: Topology) -> ValidationResult:
        """层级 1: 拓扑节点校验 - 检查节点是否存在"""
        nodes_list = topology.get("nodes", []) if isinstance(topology, dict) else getattr(topology, "nodes", [])
        
        known_nodes = {n.get("id") if isinstance(n, dict) else getattr(n, "id", None) for n in nodes_list}
        known_nodes.discard(None)
        if not known_nodes:
            # 拓扑未加载，跳过此层（不阻断流程）
            return ValidationResult(
                layer=ValidationLayer.TOPOLOGY_VERIFICATION, passed=True,
                message="拓扑暂未加载，跳过拓扑验证",
                details={"skipped": True},
            )

        missing = []
        for node_name in [intent.source_node, intent.target_node]:
            if node_name and node_name not in known_nodes:
                missing.append(node_name)

        # redirect_traffic 的 via_node 也需要验证
        via = intent.parameters.get("via_node")
        if via and via not in known_nodes:
            missing.append(via)

        if missing:
            return ValidationResult(
                layer=ValidationLayer.TOPOLOGY_VERIFICATION, passed=False,
                message=f"策略涉及的节点不存在于当前拓扑: {missing}",
                details={"missing_nodes": missing, "known_nodes": list(known_nodes)},
            )
            
        # TODO: 未来可以增加路径连通性检查（如图算法检查 source 到 target 是否物理可达）
        
        return ValidationResult(
            layer=ValidationLayer.TOPOLOGY_VERIFICATION, passed=True,
            message="拓扑节点验证通过",
        )

    def _validate_security_policy(self, intent: ParsedIntent) -> ValidationResult:
        for check in FORBIDDEN_COMBOS:
            if check(intent):
                return ValidationResult(
                    layer=ValidationLayer.SECURITY_POLICY, passed=False,
                    message="安全检查失败：该操作触发了系统安全红线，可能影响全局网络，已阻止执行",
                    details={"action": intent.action, "reason": "高危的无目标全局操作"},
                )
        return ValidationResult(
            layer=ValidationLayer.SECURITY_POLICY, passed=True, 
            message="安全策略验证通过"
        )

    def _validate_conflict_detection(self, intent: ParsedIntent) -> ValidationResult:
        # TODO: 接入系统已下发的流表数据库进行深度冲突检测
        # 目前做一些语义层面的基本防呆设计（如自己 ping 自己，自己封锁自己）
        if intent.source_node and intent.target_node:
            if intent.source_node == intent.target_node:
                return ValidationResult(
                    layer=ValidationLayer.CONFLICT_DETECTION, passed=False,
                    message="策略冲突：源节点和目标节点不能相同",
                )
                
        # 针对不同 action 的基础防呆检测
        if intent.action == IntentAction.REDIRECT_TRAFFIC:
            via = intent.parameters.get("via_node")
            if via in (intent.source_node, intent.target_node):
                return ValidationResult(
                    layer=ValidationLayer.CONFLICT_DETECTION, passed=False,
                    message="策略冲突：中转节点 via_node 不能与源或目的节点相同",
                )

        return ValidationResult(
            layer=ValidationLayer.CONFLICT_DETECTION, passed=True, 
            message="未检测到策略冲突"
        )

intent_validator = IntentValidator()
