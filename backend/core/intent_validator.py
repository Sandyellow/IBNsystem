"""
意图策略验证器 — 负责网络状态策略层面的真正校验
三层核心验证：拓扑验证 (TOPOLOGY) -> 安全策略 (SECURITY) -> 冲突检测 (CONFLICT)
"""
from __future__ import annotations
import logging
from typing import Dict, Any, List, Union

from models.intent import (
    ParsedIntent, IntentAction, IntentValidationReport,
    ValidationResult, ValidationLayer, ConflictInfo, ConflictSeverity,
)
from models.network import Topology as TopologyModel

Topology = Union[Dict[str, Any], TopologyModel]

logger = logging.getLogger(__name__)

# ── 高危操作（需要用户二次确认）────────────────────────────────────────────
HIGH_RISK_ACTIONS = {IntentAction.BLOCK_TRAFFIC, IntentAction.ACL}

# 绝对禁止的参数组合（安全红线）
FORBIDDEN_COMBOS = [
    # 在 _validate_security_policy 中处理
]

# ── 查询类 action（不参与冲突检测）─────────────────────────────────────────
QUERY_ACTIONS = {
    IntentAction.QUERY_TOPOLOGY,
    IntentAction.QUERY_FLOWS,
    IntentAction.QUERY_PORT_STATS,
}

# ── 策略身份字段注册表 ───────────────────────────────────────────────────
POLICY_IDENTITY_FIELDS: dict[IntentAction, set[str]] = {
    IntentAction.BLOCK_TRAFFIC:    {"source_nodes", "target_nodes", "scope"},
    IntentAction.ALLOW_TRAFFIC:    {"source_nodes", "target_nodes", "scope"},
    IntentAction.REDIRECT_TRAFFIC: {"source_nodes", "target_nodes", "scope"},
    IntentAction.RATE_LIMIT:       {"source_nodes", "target_nodes", "scope"},
    IntentAction.SET_PRIORITY:     {"source_nodes", "target_nodes", "scope"},
    IntentAction.CLEAR_FLOWS:      {"target_switch"},
    IntentAction.ACL:              {"source_nodes", "target_nodes", "scope"},
    IntentAction.QOS_MARK:         {"source_nodes", "target_nodes", "scope"},
    IntentAction.PORT_MIRROR:      {"target_switch"},
    IntentAction.VLAN:             {"source_nodes"},
    IntentAction.MONITOR_ALERT:    {"source_nodes", "target_nodes", "scope"},
}

# ── Action 互斥关系注册表 ─────────────────────────────────────────────────
MUTUALLY_EXCLUSIVE_PAIRS: set[frozenset[IntentAction]] = {
    frozenset({IntentAction.BLOCK_TRAFFIC, IntentAction.ALLOW_TRAFFIC}),
    frozenset({IntentAction.BLOCK_TRAFFIC, IntentAction.REDIRECT_TRAFFIC}),
    frozenset({IntentAction.BLOCK_TRAFFIC, IntentAction.RATE_LIMIT}),
    frozenset({IntentAction.BLOCK_TRAFFIC, IntentAction.SET_PRIORITY}),
    frozenset({IntentAction.BLOCK_TRAFFIC, IntentAction.ACL}),
}

_CONFLICT_ACTIONS = set(POLICY_IDENTITY_FIELDS.keys())


class IntentValidator:
    """意图策略验证器，执行三层验证：拓扑校验 → 安全策略 → 冲突检测"""

    async def validate(
        self,
        intent: ParsedIntent,
        topology: Topology,
        intent_id: str = "",
    ) -> IntentValidationReport:
        """执行三层验证：拓扑校验 → 安全策略 → 冲突检测"""
        layers: List[ValidationResult] = []

        l1 = self._validate_topology_verification(intent, topology)
        layers.append(l1)

        l2 = self._validate_security_policy(intent)
        layers.append(l2)

        l3 = self._validate_conflict_detection(intent, intent_id)
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
        """验证意图涉及的节点是否存在于当前拓扑中"""
        nodes_list = topology.get("nodes", []) if isinstance(topology, dict) else getattr(topology, "nodes", [])

        known_nodes = {n.get("id") if isinstance(n, dict) else getattr(n, "id", None) for n in nodes_list}
        known_nodes.discard(None)
        if not known_nodes:
            return ValidationResult(
                layer=ValidationLayer.TOPOLOGY_VERIFICATION, passed=True,
                message="拓扑暂未加载，跳过拓扑验证",
                details={"skipped": True},
            )

        missing = []
        all_nodes_to_check = intent.source_nodes + intent.target_nodes + intent.exclude_nodes
        
        # 对于 action_params 中可能出现的特定节点字段也需验证
        if isinstance(intent.action_params, dict):
            via = intent.action_params.get("via_switch")
            if via: all_nodes_to_check.append(via)
            mirror = intent.action_params.get("mirror_to_port")
            if mirror and mirror not in ("NORMAL", "CONTROLLER"): 
                # 简单处理：假设可能是一个节点
                all_nodes_to_check.append(mirror)
        elif hasattr(intent.action_params, 'via_switch'):
            all_nodes_to_check.append(intent.action_params.via_switch)

        for node_name in all_nodes_to_check:
            if node_name and node_name not in known_nodes:
                missing.append(node_name)

        if missing:
            return ValidationResult(
                layer=ValidationLayer.TOPOLOGY_VERIFICATION, passed=False,
                message=f"策略涉及的节点不存在于当前拓扑: {missing}",
                details={"missing_nodes": missing, "known_nodes": list(known_nodes)},
            )

        return ValidationResult(
            layer=ValidationLayer.TOPOLOGY_VERIFICATION, passed=True,
            message="拓扑节点验证通过",
        )

    def _validate_security_policy(self, intent: ParsedIntent) -> ValidationResult:
        """安全策略验证：检查高危操作和无目标的全局操作"""
        for check in FORBIDDEN_COMBOS:
            pass # reserved for future lambdas
            
        # 注意: FORBIDDEN_COMBOS 原本检查 source_node is None, 新版本对应 source_nodes == [] 并且 scope != all
        if intent.action in {IntentAction.BLOCK_TRAFFIC, IntentAction.ACL}:
            if not intent.source_nodes and not intent.target_nodes and intent.scope != "all" and not intent.target_switch:
                return ValidationResult(
                    layer=ValidationLayer.SECURITY_POLICY, passed=False,
                    message="安全检查失败：该操作触发了系统安全红线，可能影响全局网络，已阻止执行",
                    details={"action": intent.action, "reason": "高危的无目标全局操作"},
                )

        return ValidationResult(
            layer=ValidationLayer.SECURITY_POLICY, passed=True,
            message="安全策略验证通过"
        )

    def _validate_conflict_detection(self, intent: ParsedIntent, intent_id: str = "") -> ValidationResult:
        """冲突检测：检查新意图是否与已有活跃策略冲突"""
        if intent.action in QUERY_ACTIONS:
            return ValidationResult(
                layer=ValidationLayer.CONFLICT_DETECTION, passed=True,
                message="查询类操作，跳过冲突检测",
            )

        if set(intent.source_nodes).intersection(set(intent.target_nodes)):
            return ValidationResult(
                layer=ValidationLayer.CONFLICT_DETECTION, passed=False,
                message="策略冲突：源节点和目标节点列表存在重合",
            )

        if intent.action == IntentAction.REDIRECT_TRAFFIC:
            via = intent.action_params.get("via_switch") if isinstance(intent.action_params, dict) else getattr(intent.action_params, "via_switch", None)
            if via and (via in intent.source_nodes or via in intent.target_nodes):
                return ValidationResult(
                    layer=ValidationLayer.CONFLICT_DETECTION, passed=False,
                    message="策略冲突：中转节点 via_switch 不能与源或目的节点相同",
                )

        if intent.action not in _CONFLICT_ACTIONS:
            return ValidationResult(
                layer=ValidationLayer.CONFLICT_DETECTION, passed=True,
                message="未检测到策略冲突",
            )

        identity_fields = POLICY_IDENTITY_FIELDS[intent.action]
        new_identity = self._extract_identity(intent, identity_fields)
        if new_identity is None:
            return ValidationResult(
                layer=ValidationLayer.CONFLICT_DETECTION, passed=True,
                message="策略身份字段不完整，跳过冲突检测",
            )

        from core.policy_executor import policy_executor as _pe
        active = _pe.get_active_policies()

        conflicts: List[ConflictInfo] = []

        for pol in active:
            pol_id = pol.get("id", "")
            if pol_id == intent_id:
                continue

            pol_action_str = pol.get("intent_action")
            if pol_action_str is None:
                continue

            try:
                pol_action = IntentAction(pol_action_str)
            except ValueError:
                continue

            if pol_action not in _CONFLICT_ACTIONS:
                continue

            pol_identity_fields = POLICY_IDENTITY_FIELDS[pol_action]
            pol_identity = self._extract_policy_identity(pol, pol_identity_fields)
            if pol_identity is None:
                continue

            if new_identity != pol_identity:
                continue

            pol_params = pol.get("action_params", {})
            intent_params = intent.action_params if isinstance(intent.action_params, dict) else intent.action_params.model_dump()

            if pol_action == intent.action and pol_params == intent_params:
                conflicts.append(ConflictInfo(
                    policy_id=pol_id,
                    severity=ConflictSeverity.DUPLICATE,
                    description="已存在完全相同的策略",
                    existing_action=pol_action_str,
                    existing_parameters=pol_params,
                ))
            elif pol_action == intent.action:
                conflicts.append(ConflictInfo(
                    policy_id=pol_id,
                    severity=ConflictSeverity.OVERRIDE,
                    description=f"已存在同类型策略但参数不同（旧参数: {pol_params}）",
                    existing_action=pol_action_str,
                    existing_parameters=pol_params,
                ))
            elif frozenset({intent.action, pol_action}) in MUTUALLY_EXCLUSIVE_PAIRS:
                conflicts.append(ConflictInfo(
                    policy_id=pol_id,
                    severity=ConflictSeverity.MUTUALLY_EXCLUSIVE,
                    description=f"已存在互斥策略（旧策略类型: {pol_action_str}）",
                    existing_action=pol_action_str,
                    existing_parameters=pol_params,
                ))

        if not conflicts:
            return ValidationResult(
                layer=ValidationLayer.CONFLICT_DETECTION, passed=True,
                message="未检测到策略冲突",
            )

        conflict_ids = [c.policy_id for c in conflicts]
        return ValidationResult(
            layer=ValidationLayer.CONFLICT_DETECTION, passed=False,
            message=f"检测到 {len(conflicts)} 条策略冲突，请先撤销冲突策略后再重新下发",
            details={"conflict_policy_ids": conflict_ids},
            conflicts=conflicts,
        )

    def _extract_identity(self, intent: ParsedIntent, fields: set[str]) -> tuple | None:
        """从意图中提取策略身份特征，用于冲突检测对比"""
        values = []
        field_map = {
            "source_nodes": frozenset(intent.source_nodes) if intent.source_nodes else None,
            "target_nodes": frozenset(intent.target_nodes) if intent.target_nodes else None,
            "target_switch": intent.target_switch,
            "scope": intent.scope,
        }
        for f in fields:
            v = field_map.get(f)
            if v is None and f != "target_switch": 
                # 对于某些必填身份字段如果缺失，则视为身份不完整
                # 但由于 source_nodes 在 scope=all 时可能为空，需要允许空
                if f in ("source_nodes", "target_nodes") and intent.scope == "all":
                    values.append(frozenset())
                else:
                    return None
            else:
                values.append(v)
        return tuple(values)

    def _extract_policy_identity(self, pol: dict, fields: set[str]) -> tuple | None:
        """从已有策略字典中提取身份特征，用于冲突检测对比"""
        values = []
        field_map = {
            "source_nodes": frozenset(pol.get("source_nodes", [])),
            "target_nodes": frozenset(pol.get("target_nodes", [])),
            "target_switch": pol.get("target_switch"),
            "scope": pol.get("scope", "specific"),
        }
        for f in fields:
            v = field_map.get(f)
            # 类似处理
            if (not v) and f in ("source_nodes", "target_nodes"):
                if pol.get("scope") == "all":
                    values.append(frozenset())
                else:
                    return None
            else:
                values.append(v)
        return tuple(values)


intent_validator = IntentValidator()
