"""
策略生成器 — 将验证通过的意图转换为可执行的网络策略
并生成对应的回滚策略
"""
from __future__ import annotations
import logging
import threading
from typing import Optional, Tuple

from models.intent import ParsedIntent, IntentAction
from models.network import Topology, NodeType
from models.policy import NetworkPolicy, PolicyType, FlowMatch, FlowAction, PolicyExecutionResult

logger = logging.getLogger(__name__)

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
        # 在本次 generate() 调用期间存储拓扑，供 handler 辅助函数使用
        self._current_topology = topology
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
        finally:
            self._current_topology = None  # 清理临时引用

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
        # ── 修复：使用拓扑动态解析端口，不再硬编码 ──
        out_port = self._resolve_port_from_topology(dpid, via) if via else "NORMAL"

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
        """
        修复：真正执行 Mininet ping 命令，而不是仅下发 ICMP 流规则。
        命令格式：{src_host} ping -c 3 {dst_ip}
        """
        src = intent.source_node or ""
        dst = dst_ip or intent.target_node or ""
        count = intent.parameters.get("count", 3)
        cmd = f"{src} ping -c {count} {dst}"

        policy = NetworkPolicy(
            policy_type=PolicyType.MININET_CMD,
            dpid=dpid or "0",
            command=cmd,
            description=f"执行 PING: {intent.source_node} → {intent.target_node} (×{count})",
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

    def _dpid_to_switch_id(self, dpid: str, topology: Topology) -> Optional[str]:
        """将 dpid 转换为节点 id（如 s1）"""
        for node in topology.nodes:
            if node.type == NodeType.SWITCH and node.dpid == dpid:
                return node.id
        # 尝试数值转换兜底
        try:
            n = int(str(dpid), 16)
            return f"s{n}"
        except (ValueError, TypeError):
            return None

    def _resolve_port_from_topology(self, dpid: str, target_node: str) -> int | str:
        """
        从拓扑链路中动态解析从 dpid 所在交换机到 target_node 的出端口号。
        若找不到则返回 "NORMAL"。
        """
        topology = self._current_topology
        if topology is None:
            return "NORMAL"

        switch_id = self._dpid_to_switch_id(dpid, topology)
        if not switch_id:
            return "NORMAL"

        for link in topology.links:
            if link.source == switch_id and link.target == target_node and link.src_port:
                return link.src_port
            if link.target == switch_id and link.source == target_node and link.dst_port:
                return link.dst_port

        logger.warning(
            f"[PolicyGenerator] 无法从拓扑解析端口: dpid={dpid} switch={switch_id} -> {target_node}，返回 NORMAL"
        )
        return "NORMAL"

    def _resolve_link_interfaces(
        self, dpid: str, src_node: str, tgt_node: str
    ) -> tuple[Optional[str], Optional[str]]:
        """
        从拓扑中找到两端的接口名。
        返回 (src侧接口名, tgt侧接口名)，均可为 None（表示未找到，请使用兜底命令）。
        """
        topology = self._current_topology
        if topology is None:
            return None, None

        switch_id = self._dpid_to_switch_id(dpid, topology)
        if not switch_id:
            return None, None

        for link in topology.links:
            # 找到连接 src_node ↔ tgt_node 的链路
            if {link.source, link.target} == {src_node, tgt_node}:
                if link.source == src_node and link.src_port:
                    iface = f"{src_node}-eth{link.src_port}"
                    rb_iface = f"{tgt_node}-eth{link.dst_port}" if link.dst_port else None
                    return iface, rb_iface
                if link.target == src_node and link.dst_port:
                    iface = f"{src_node}-eth{link.dst_port}"
                    rb_iface = f"{tgt_node}-eth{link.src_port}" if link.src_port else None
                    return iface, rb_iface

        logger.warning(
            f"[PolicyGenerator] 无法从拓扑解析链路接口: {src_node} ↔ {tgt_node}，将使用 link 命令兜底"
        )
        return None, None


policy_generator = PolicyGenerator()
