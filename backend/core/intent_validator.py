"""
意图验证器 — LLM 输出可靠性保障的核心
六层验证流水线：Schema → 白名单 → 节点存在 → 参数范围 → 安全检查 → 冲突检测
"""
from __future__ import annotations
import logging
from typing import Dict, List

from models.intent import (
    ParsedIntent, IntentAction, IntentValidationReport,
    ValidationResult, ValidationLayer,
)
from models.network import Topology

logger = logging.getLogger(__name__)

# ─── 参数范围约束 ─────────────────────────────────────────────────────────────
PARAM_RULES = {
    IntentAction.RATE_LIMIT: {
        "bandwidth_mbps": {"min": 0.1, "max": 10000, "required": True, "type": float},
    },
    IntentAction.SET_PRIORITY: {
        "priority": {"min": 1, "max": 65535, "required": True, "type": int},
    },
    IntentAction.REDIRECT_TRAFFIC: {
        "via_node": {"required": True, "type": str},
    },
}

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

        # ── Layer 1: Schema 完整性（Pydantic 已保障基础，此处检查业务逻辑必填）
        l1 = self._validate_schema(intent)
        layers.append(l1)

        # ── Layer 2: Action 白名单
        l2 = self._validate_action_whitelist(intent)
        layers.append(l2)

        # ── Layer 3: 节点存在性（对照当前拓扑）
        l3 = self._validate_node_existence(intent, topology)
        layers.append(l3)

        # ── Layer 4: 参数范围
        l4 = self._validate_param_range(intent)
        layers.append(l4)

        # ── Layer 5: 安全红线
        l5 = self._validate_safety(intent)
        layers.append(l5)

        # ── Layer 6: 置信度门槛
        l6 = self._validate_confidence(intent)
        layers.append(l6)

        overall_passed = all(l.passed for l in layers)
        requires_confirmation = intent.action in HIGH_RISK_ACTIONS and overall_passed

        risk_level = "low"
        if intent.action in HIGH_RISK_ACTIONS:
            risk_level = "high"
        elif not l3.passed:
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

    def _validate_schema(self, intent: ParsedIntent) -> ValidationResult:
        issues = []
        # query_stats / load_balance / ping 可以不需要节点
        needs_source = {
            IntentAction.ADD_FLOW, IntentAction.DELETE_FLOW,
            IntentAction.RATE_LIMIT, IntentAction.BLOCK_TRAFFIC,
            IntentAction.ALLOW_TRAFFIC, IntentAction.REDIRECT_TRAFFIC,
            IntentAction.PING, IntentAction.SET_PRIORITY,
        }
        if intent.action in needs_source and intent.source_node is None:
            issues.append("该操作需要 source_node")

        if issues:
            return ValidationResult(
                layer=ValidationLayer.SCHEMA, passed=False,
                message="Schema 检查失败: " + "; ".join(issues),
            )
        return ValidationResult(layer=ValidationLayer.SCHEMA, passed=True, message="Schema 合法")

    def _validate_action_whitelist(self, intent: ParsedIntent) -> ValidationResult:
        allowed = set(IntentAction.__members__.values())
        if intent.action not in allowed:
            return ValidationResult(
                layer=ValidationLayer.ACTION_WHITELIST, passed=False,
                message=f"未知操作: {intent.action}",
            )
        return ValidationResult(layer=ValidationLayer.ACTION_WHITELIST, passed=True, message="操作在白名单内")

    def _validate_node_existence(self, intent: ParsedIntent, topology: Topology) -> ValidationResult:
        known_nodes = {n.id for n in topology.nodes}
        if not known_nodes:
            # 拓扑未加载，跳过此层（不阻断流程）
            return ValidationResult(
                layer=ValidationLayer.NODE_EXISTENCE, passed=True,
                message="拓扑暂未加载，跳过节点验证",
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
                layer=ValidationLayer.NODE_EXISTENCE, passed=False,
                message=f"节点不存在于当前拓扑: {missing}",
                details={"missing_nodes": missing, "known_nodes": list(known_nodes)},
            )
        return ValidationResult(
            layer=ValidationLayer.NODE_EXISTENCE, passed=True,
            message="所有节点均存在于拓扑中",
        )

    def _validate_param_range(self, intent: ParsedIntent) -> ValidationResult:
        rules = PARAM_RULES.get(intent.action, {})
        errors = []
        for param, rule in rules.items():
            val = intent.parameters.get(param)
            if val is None:
                if rule.get("required"):
                    errors.append(f"缺少必填参数 '{param}'")
                continue
            # 类型检查
            expected_type = rule.get("type")
            if expected_type and not isinstance(val, (int, float)) and expected_type in (int, float):
                try:
                    val = expected_type(val)
                    intent.parameters[param] = val
                except (ValueError, TypeError):
                    errors.append(f"参数 '{param}' 类型错误，应为 {expected_type.__name__}")
                    continue
            # 范围检查
            if "min" in rule and val < rule["min"]:
                errors.append(f"参数 '{param}' = {val} 低于最小值 {rule['min']}")
            if "max" in rule and val > rule["max"]:
                errors.append(f"参数 '{param}' = {val} 超过最大值 {rule['max']}")

        if errors:
            return ValidationResult(
                layer=ValidationLayer.PARAM_RANGE, passed=False,
                message="参数范围校验失败: " + "; ".join(errors),
            )
        return ValidationResult(layer=ValidationLayer.PARAM_RANGE, passed=True, message="参数合法")

    def _validate_safety(self, intent: ParsedIntent) -> ValidationResult:
        for check in FORBIDDEN_COMBOS:
            if check(intent):
                return ValidationResult(
                    layer=ValidationLayer.SAFETY, passed=False,
                    message="安全检查失败：该操作可能影响全局网络，已阻止执行",
                    details={"action": intent.action, "reason": "缺少节点约束的危险操作"},
                )
        return ValidationResult(layer=ValidationLayer.SAFETY, passed=True, message="安全检查通过")

    def _validate_confidence(self, intent: ParsedIntent) -> ValidationResult:
        if intent.confidence < 0.6:
            return ValidationResult(
                layer=ValidationLayer.CONFIDENCE, passed=False,
                message=f"LLM 置信度过低 ({intent.confidence:.2f} < 0.6)，请用户澄清意图",
                details={"confidence": intent.confidence},
            )
        return ValidationResult(
            layer=ValidationLayer.CONFIDENCE, passed=True,
            message=f"置信度合格 ({intent.confidence:.2f})",
        )


intent_validator = IntentValidator()
