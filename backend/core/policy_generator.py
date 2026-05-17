"""
策略生成器 — 将验证通过的意图转换为可执行的网络策略
并生成对应的回滚策略
"""
from __future__ import annotations
import logging
from typing import Optional, Tuple

from models.intent import ParsedIntent, IntentAction
from models.network import Topology, NodeType
from models.policy import NetworkPolicy, PolicyType, FlowMatch, FlowAction, PolicyExecutionResult

logger = logging.getLogger(__name__)

import threading

# 默认 meter id 起始值（避免冲突）
_METER_ID_COUNTER = 100
_METER_LOCK = threading.Lock()


def _next_meter_id() -> int:
    global _METER_ID_COUNTER
    with _METER_LOCK:
        _METER_ID_COUNTER += 1
        return _METER_ID_COUNTER


class PolicyGenerator:

    def generate(
        self,
        intent: ParsedIntent,
        topology: Topology,
        intent_id: str,
    ) -> Tuple[Optional[NetworkPolicy], Optional[NetworkPolicy], str]:
        """
        生成执行策略和回滚策略
        返回: (policy, rollback_policy, error_message)
        """
        try:
            dpid = self._find_dpid(intent.source_node, intent.target_node, topology)
            if dpid is None:
                dpid = self._first_switch_dpid(topology)
            if dpid is None:
                return None, None, "拓扑中未找到任何交换机"

            src_ip = self._node_ip(intent.source_node, topology)
            dst_ip = self._node_ip(intent.target_node, topology)

            handler = {
                IntentAction.RATE_LIMIT: self._gen_rate_limit,
                IntentAction.BLOCK_TRAFFIC: self._gen_block,
                IntentAction.ALLOW_TRAFFIC: self._gen_allow,
                IntentAction.ADD_FLOW: self._gen_add_flow,
                IntentAction.DELETE_FLOW: self._gen_delete_flow,
                IntentAction.REDIRECT_TRAFFIC: self._gen_redirect,
                IntentAction.SET_PRIORITY: self._gen_set_priority,
                IntentAction.LOAD_BALANCE: self._gen_load_balance,
                IntentAction.PING: self._gen_ping,
            }.get(intent.action)

            if handler is None:
                return None, None, f"不支持生成策略的操作: {intent.action}"

            policy, rollback = handler(intent, dpid, src_ip, dst_ip, intent_id)
            return policy, rollback, ""

        except Exception as e:
            logger.error(f"[PolicyGenerator] 生成失败: {e}", exc_info=True)
            return None, None, str(e)

    # ─── 各操作策略生成 ──────────────────────────────────

    def _gen_rate_limit(self, intent, dpid, src_ip, dst_ip, intent_id):
        bw_mbps = intent.parameters.get("bandwidth_mbps", 10)
        rate_kbps = int(bw_mbps * 1000)
        meter_id = _next_meter_id()

        policy = NetworkPolicy(
            policy_type=PolicyType.METER,
            dpid=dpid,
            priority=200,
            match=FlowMatch(ipv4_src=src_ip, ipv4_dst=dst_ip),
            actions=[FlowAction(type="meter", value=meter_id)],
            meter_id=meter_id,
            rate_kbps=rate_kbps,
            description=f"限速 {intent.source_node}→{intent.target_node} 至 {bw_mbps}Mbps",
            intent_id=intent_id,
        )
        rollback = NetworkPolicy(
            policy_type=PolicyType.METER,
            dpid=dpid,
            priority=200,
            match=FlowMatch(ipv4_src=src_ip, ipv4_dst=dst_ip),
            actions=[FlowAction(type="delete", value=meter_id)],
            meter_id=meter_id,
            description=f"回滚: 删除限速 meter {meter_id}",
            intent_id=intent_id,
        )
        return policy, rollback

    def _gen_block(self, intent, dpid, src_ip, dst_ip, intent_id):
        policy = NetworkPolicy(
            policy_type=PolicyType.FLOW_RULE,
            dpid=dpid,
            priority=300,
            match=FlowMatch(ipv4_src=src_ip, ipv4_dst=dst_ip),
            actions=[FlowAction(type="drop")],
            description=f"封锁 {intent.source_node}→{intent.target_node}",
            intent_id=intent_id,
        )
        rollback = NetworkPolicy(
            policy_type=PolicyType.FLOW_RULE,
            dpid=dpid,
            priority=300,
            match=FlowMatch(ipv4_src=src_ip, ipv4_dst=dst_ip),
            actions=[FlowAction(type="delete")],
            description=f"回滚: 删除封锁规则",
            intent_id=intent_id,
        )
        return policy, rollback

    def _gen_allow(self, intent, dpid, src_ip, dst_ip, intent_id):
        policy = NetworkPolicy(
            policy_type=PolicyType.FLOW_RULE,
            dpid=dpid,
            priority=300,
            match=FlowMatch(ipv4_src=src_ip, ipv4_dst=dst_ip),
            actions=[FlowAction(type="output", value="NORMAL")],
            description=f"允许 {intent.source_node}→{intent.target_node}",
            intent_id=intent_id,
        )
        return policy, None

    def _gen_add_flow(self, intent, dpid, src_ip, dst_ip, intent_id):
        policy = NetworkPolicy(
            policy_type=PolicyType.FLOW_RULE,
            dpid=dpid,
            priority=intent.parameters.get("priority", 100),
            match=FlowMatch(ipv4_src=src_ip, ipv4_dst=dst_ip),
            actions=[FlowAction(type="output", value="FLOOD")],
            description=f"添加流表: {intent.source_node}→{intent.target_node}",
            intent_id=intent_id,
        )
        rollback = NetworkPolicy(
            policy_type=PolicyType.FLOW_RULE,
            dpid=dpid,
            priority=0,
            match=FlowMatch(ipv4_src=src_ip, ipv4_dst=dst_ip),
            actions=[FlowAction(type="delete")],
            description="回滚: 删除添加的流表",
            intent_id=intent_id,
        )
        return policy, rollback

    def _gen_delete_flow(self, intent, dpid, src_ip, dst_ip, intent_id):
        policy = NetworkPolicy(
            policy_type=PolicyType.FLOW_RULE,
            dpid=dpid,
            priority=0,
            match=FlowMatch(ipv4_src=src_ip, ipv4_dst=dst_ip),
            actions=[FlowAction(type="delete")],
            description=f"删除流表: {intent.source_node}→{intent.target_node}",
            intent_id=intent_id,
        )
        return policy, None

    def _gen_redirect(self, intent, dpid, src_ip, dst_ip, intent_id):
        via = intent.parameters.get("via_node", "")
        out_port = self._resolve_port(dpid, via) if via else "NORMAL"
        
        policy = NetworkPolicy(
            policy_type=PolicyType.FLOW_RULE,
            dpid=dpid,
            priority=250,
            match=FlowMatch(ipv4_src=src_ip, ipv4_dst=dst_ip),
            actions=[FlowAction(type="output", value=out_port)],
            description=f"重定向 {intent.source_node}→{intent.target_node} 经由 {via} (端口 {out_port})",
            intent_id=intent_id,
        )
        rollback = NetworkPolicy(
            policy_type=PolicyType.FLOW_RULE,
            dpid=dpid,
            priority=250,
            match=FlowMatch(ipv4_src=src_ip, ipv4_dst=dst_ip),
            actions=[FlowAction(type="delete")],
            description="回滚: 删除重定向规则",
            intent_id=intent_id,
        )
        return policy, rollback

    def _gen_set_priority(self, intent, dpid, src_ip, dst_ip, intent_id):
        priority = intent.parameters.get("priority", 100)
        policy = NetworkPolicy(
            policy_type=PolicyType.FLOW_RULE,
            dpid=dpid,
            priority=priority,
            match=FlowMatch(ipv4_src=src_ip, ipv4_dst=dst_ip),
            actions=[FlowAction(type="output", value="NORMAL")],
            description=f"设置优先级 {priority}: {intent.source_node}→{intent.target_node}",
            intent_id=intent_id,
        )
        return policy, None

    def _gen_load_balance(self, intent, dpid, src_ip, dst_ip, intent_id):
        policy = NetworkPolicy(
            policy_type=PolicyType.GROUP,
            dpid=dpid,
            priority=150,
            match=FlowMatch(ipv4_dst=dst_ip),
            actions=[FlowAction(type="group", value="load_balance")],
            description=f"负载均衡到 {intent.target_node}",
            intent_id=intent_id,
        )
        return policy, None

    def _gen_ping(self, intent, dpid, src_ip, dst_ip, intent_id):
        policy = NetworkPolicy(
            policy_type=PolicyType.FLOW_RULE,
            dpid=dpid,
            priority=300,
            match=FlowMatch(ipv4_src=src_ip, ipv4_dst=dst_ip, ip_proto=1),
            actions=[FlowAction(type="output", value="NORMAL")],
            description=f"放行 PING (ICMP): {intent.source_node}↔{intent.target_node}",
            intent_id=intent_id,
        )
        return policy, None

    # ─── 辅助函数 ────────────────────────────────────────

    def _find_dpid(self, src_node, dst_node, topology: Topology) -> Optional[str]:
        """找到连接源/目节点的交换机 dpid"""
        for node in topology.nodes:
            if node.type == NodeType.SWITCH and node.dpid:
                if node.id in [src_node, dst_node]:
                    return node.dpid
                    
        for link in topology.links:
            connected_target = None
            if link.source in [src_node, dst_node]:
                connected_target = link.target
            elif link.target in [src_node, dst_node]:
                connected_target = link.source
                
            if connected_target:
                for node in topology.nodes:
                    if node.id == connected_target and node.type == NodeType.SWITCH and node.dpid:
                        return node.dpid
        return None

    def _first_switch_dpid(self, topology: Topology) -> Optional[str]:
        for node in topology.nodes:
            if node.type == NodeType.SWITCH and node.dpid:
                return node.dpid
        return None

    def _node_ip(self, node_name: Optional[str], topology: Topology) -> Optional[str]:
        if node_name is None:
            return None
        for node in topology.nodes:
            if node.id == node_name:
                return node.ip
        return None

    def _resolve_port(self, dpid: str, target: str):
        """根据已知拓扑结构将节点名称解析为出端口"""
        try:
            dpid_int = str(int(str(dpid), 16))
        except (ValueError, TypeError):
            dpid_int = str(dpid)
            
        if dpid_int == "1":
            return 1 if target in ("s2", "h1", "h2") else 2
        elif dpid_int == "2":
            if target == "h1": return 2
            if target == "h2": return 3
            return 1
        elif dpid_int == "3":
            if target == "h3": return 2
            if target == "h4": return 3
            return 1
        return "NORMAL"

policy_generator = PolicyGenerator()
