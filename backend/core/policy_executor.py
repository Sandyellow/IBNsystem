"""
策略执行器 — 将解析好的 ParsedIntent 映射到 NetworkPrimitive 并通过 ControllerAdapter 下发
"""
from __future__ import annotations
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Set

from core.ryu_client import ryu_client
from core.topology_manager import topo_manager, _is_placeholder_mac
from models.intent import ParsedIntent, IntentAction, IntentScope, MatchCondition
from models.policy import ActivePolicy, PolicyType
from core.controller_adapter import NetworkPrimitive, PrimitiveType
from core.policy_store import load_policies, save_policies

logger = logging.getLogger(__name__)

# 从本地加载持久化策略和计数器
_active_policies, _meter_counter = load_policies()


def _next_meter_id() -> int:
    global _meter_counter
    _meter_counter += 1
    return _meter_counter


def _make_cookie(intent_id: str) -> int:
    """从 intent_id 生成稳定的 64-bit cookie"""
    h = hashlib.md5(intent_id.encode()).hexdigest()[:15]
    return int(h, 16)


def _build_match(src_mac: str, dst_mac: str, src_ip: Optional[str], dst_ip: Optional[str], custom_match: Optional[MatchCondition] = None) -> dict:
    match = {}
    if src_mac and src_mac != "any": match["eth_src"] = src_mac
    if dst_mac and dst_mac != "any": match["eth_dst"] = dst_mac
    
    if src_ip or dst_ip or custom_match:
        match["eth_type"] = 0x0800
        if src_ip and src_ip != "any": match["ipv4_src"] = src_ip
        if dst_ip and dst_ip != "any": match["ipv4_dst"] = dst_ip
        
        if custom_match:
            if custom_match.eth_type is not None: match["eth_type"] = custom_match.eth_type
            if custom_match.ip_proto is not None: match["ip_proto"] = custom_match.ip_proto
            if custom_match.tcp_src is not None: match["tcp_src"] = custom_match.tcp_src
            if custom_match.tcp_dst is not None: match["tcp_dst"] = custom_match.tcp_dst
            if custom_match.udp_src is not None: match["udp_src"] = custom_match.udp_src
            if custom_match.udp_dst is not None: match["udp_dst"] = custom_match.udp_dst
            if custom_match.dscp is not None: match["ip_dscp"] = custom_match.dscp
    return match


class PolicyExecutor:
    """策略执行器，将 ParsedIntent 映射为网络原语并通过 Ryu 客户端下发到交换机"""

    async def execute(self, intent: ParsedIntent, intent_id: str) -> Dict[str, Any]:
        """根据意图类型分发到对应的处理器执行"""
        action = intent.action
        try:
            handlers = {
                IntentAction.QUERY_TOPOLOGY:   self._query_topology,
                IntentAction.QUERY_FLOWS:      self._query_flows,
                IntentAction.QUERY_PORT_STATS: self._query_port_stats,
                IntentAction.BLOCK_TRAFFIC:    self._block_traffic,
                IntentAction.ALLOW_TRAFFIC:    self._allow_traffic,
                IntentAction.RATE_LIMIT:       self._rate_limit,
                IntentAction.SET_PRIORITY:     self._set_priority,
                IntentAction.CLEAR_FLOWS:      self._clear_flows,
                IntentAction.ACL:              self._acl,
                IntentAction.QOS_MARK:         self._qos_mark,
                IntentAction.VLAN:             self._vlan,
                IntentAction.MULTIPATH:        self._multipath,
            }
            handler = handlers.get(action)
            if handler is None:
                return {"success": False, "error": f"不支持的操作: {action}"}
            return await handler(intent, intent_id)
        except Exception as e:
            logger.error(f"[PolicyExecutor] {action}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # ── 查询操作 ──────────────────────────────────────────

    async def _query_topology(self, intent: ParsedIntent, _: str) -> Dict:
        """查询当前网络拓扑"""
        topo = topo_manager.topology
        nodes = topo.get("nodes", [])
        links = topo.get("links", [])
        switches = [n for n in nodes if n.get("type") == "switch"]
        hosts = [n for n in nodes if n.get("type") == "host"]
        return {
            "success": True,
            "type": "query_topology",
            "data": topo,
            "message": f"当前拓扑：{len(switches)} 台交换机，{len(hosts)} 台主机，{len(links)} 条链路"
        }

    async def _query_flows(self, intent: ParsedIntent, _: str) -> Dict:
        """查询交换机流表"""
        sw = intent.target_switch
        if sw:
            dpid = topo_manager.get_switch_dpid(sw)
            dpids = [dpid] if dpid else []
        else:
            dpids = topo_manager.get_all_switch_dpids()

        all_flows = {str(dpid): await ryu_client.get_flows(dpid) for dpid in dpids}
        total = sum(len(v) for v in all_flows.values())
        return {"success": True, "type": "query_flows", "data": all_flows, "message": f"共 {total} 条流表"}

    async def _query_port_stats(self, intent: ParsedIntent, _: str) -> Dict:
        """查询交换机端口统计"""
        sw = intent.target_switch
        dpids = [topo_manager.get_switch_dpid(sw)] if sw else topo_manager.get_all_switch_dpids()
        stats = {str(dpid): await ryu_client.get_port_stats(dpid) for dpid in dpids if dpid}
        return {"success": True, "type": "query_port_stats", "data": stats, "message": f"获取了统计数据"}

    # ── 解析辅助 ──────────────────────────────────────────

    def _resolve_hosts(self, nodes: List[str], scope: IntentScope, exclude: List[str]) -> List[Dict]:
        """解析节点列表，处理 'all' 和 exclude 逻辑"""
        if scope == IntentScope.ALL and not nodes:
            all_hosts = topo_manager.get_all_hosts()
            return [h for h in all_hosts if h["id"] not in exclude]
        
        res = []
        for n in nodes:
            if n in exclude: continue
            h = topo_manager.get_host(n)
            if h: res.append(h)
        return res
        
    def _get_target_dpids(self, src_hosts: List[Dict], dst_hosts: List[Dict]) -> Set[int]:
        """根据源和目标主机解析涉及的交换机 DPID 集合"""
        dpids = set()
        for h in src_hosts + dst_hosts:
            sw_name = h.get("connected_switch")
            if sw_name:
                d = topo_manager.get_switch_dpid(sw_name)
                if d: dpids.add(d)
        if not dpids:
            dpids = set(topo_manager.get_all_switch_dpids())
        return dpids

    # ── 控制操作 ──────────────────────────────────────────

    async def _block_traffic(self, intent: ParsedIntent, intent_id: str) -> Dict:
        """下发流量阻断策略，在交换机上安装 DROP 流表规则"""
        src_hosts = self._resolve_hosts(intent.source_nodes, intent.scope, intent.exclude_nodes)
        
        # 检查是否是全网隔离（wildcard block）
        is_wildcard = False
        if not intent.target_nodes and intent.scope == IntentScope.ALL:
            is_wildcard = True
            dst_hosts = [{"id": "any", "mac": "any", "ip": "any", "connected_switch": None}]
        else:
            dst_hosts = self._resolve_hosts(intent.target_nodes, intent.scope, intent.exclude_nodes)

        if not src_hosts or not dst_hosts:
            return {"success": False, "error": "源或目标主机解析为空"}

        cookie = _make_cookie(intent_id)
        target_dpids = self._get_target_dpids(src_hosts, dst_hosts)

        primitives = []
        prio = intent.intent_priority if intent.intent_priority is not None else 500
        for src in src_hosts:
            for dst in dst_hosts:
                match_fwd = _build_match(src["mac"], dst["mac"], src.get("ip"), dst.get("ip"), intent.match)
                match_rev = _build_match(dst["mac"], src["mac"], dst.get("ip"), src.get("ip"), intent.match)
                
                for dpid in target_dpids:
                    primitives.append(NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=prio, match=match_fwd, actions=[]))
                    if intent.direction == "bidirectional":
                        primitives.append(NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=prio, match=match_rev, actions=[]))

        # 为 exclude_nodes 自动生成高优先级的 ALLOW 规则，防止被 wildcard block 误杀
        if is_wildcard and intent.exclude_nodes:
            allow_hosts = [h for h in topo_manager.get_all_hosts() if h["id"] in intent.exclude_nodes]
            if allow_hosts:
                allow_dpids = self._get_target_dpids(src_hosts, allow_hosts)
                for src in src_hosts:
                    for dst in allow_hosts:
                        match_fwd = _build_match(src["mac"], dst["mac"], src.get("ip"), dst.get("ip"), intent.match)
                        match_rev = _build_match(dst["mac"], src["mac"], dst.get("ip"), src.get("ip"), intent.match)
                        for dpid in allow_dpids:
                            primitives.append(NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=prio + 100, match=match_fwd, actions=[{"type": "OUTPUT", "port": "NORMAL"}]))
                            if intent.direction == "bidirectional":
                                primitives.append(NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=prio + 100, match=match_rev, actions=[{"type": "OUTPUT", "port": "NORMAL"}]))

        import asyncio
        results = await asyncio.gather(*(ryu_client.apply_primitive(p) for p in primitives))
        
        if not all(results):
            for d in target_dpids: await ryu_client.delete_flows_by_cookie(d, cookie)
            return {"success": False, "error": "批量下发流表失败，已回滚"}

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id, policy_type=PolicyType.BLOCK, scope=intent.scope,
            source_nodes=intent.source_nodes, target_nodes=intent.target_nodes, exclude_nodes=intent.exclude_nodes,
            intent_action=intent.action, action_params=intent.action_params if isinstance(intent.action_params, dict) else intent.action_params.model_dump(),
            match=intent.match.model_dump() if intent.match else None,
            description=f"隔离 {len(src_hosts)} 台主机与{'全网' if is_wildcard else len(dst_hosts)}台主机的通信",
            ryu_cookies=[cookie], created_at=time.time()
        )
        save_policies(_active_policies, _meter_counter)
        msg_target = "全网主机" if is_wildcard else f"{len(dst_hosts)} 台主机"
        return {"success": True, "type": "block_traffic", "message": f"成功隔离 {len(src_hosts)} 台主机与 {msg_target} 的通信"}

    async def _allow_traffic(self, intent: ParsedIntent, intent_id: str) -> Dict:
        """下发流量允许策略，安装高优先级 NORMAL 转发规则"""
        src_hosts = self._resolve_hosts(intent.source_nodes, intent.scope, intent.exclude_nodes)
        dst_hosts = self._resolve_hosts(intent.target_nodes, intent.scope, intent.exclude_nodes)
        if not src_hosts or not dst_hosts:
            return {"success": False, "error": "源或目标主机解析为空"}

        cookie = _make_cookie(intent_id)
        target_dpids = self._get_target_dpids(src_hosts, dst_hosts)

        primitives = []
        # 使用比 Block (500) 更高的优先级
        prio = intent.intent_priority if intent.intent_priority is not None else 600
        for src in src_hosts:
            for dst in dst_hosts:
                match_fwd = _build_match(src["mac"], dst["mac"], src.get("ip"), dst.get("ip"), intent.match)
                match_rev = _build_match(dst["mac"], src["mac"], dst.get("ip"), src.get("ip"), intent.match)
                
                for dpid in target_dpids:
                    primitives.append(NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=prio, match=match_fwd, actions=[{"type": "OUTPUT", "port": "NORMAL"}]))
                    if intent.direction == "bidirectional":
                        primitives.append(NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=prio, match=match_rev, actions=[{"type": "OUTPUT", "port": "NORMAL"}]))

        import asyncio
        results = await asyncio.gather(*(ryu_client.apply_primitive(p) for p in primitives))
        
        if not all(results):
            for d in target_dpids: await ryu_client.delete_flows_by_cookie(d, cookie)
            return {"success": False, "error": "批量下发允许流表失败，已回滚"}

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id, policy_type=PolicyType.ALLOW, scope=intent.scope,
            source_nodes=intent.source_nodes, target_nodes=intent.target_nodes, exclude_nodes=intent.exclude_nodes,
            intent_action=intent.action, action_params=intent.action_params if isinstance(intent.action_params, dict) else intent.action_params.model_dump(),
            match=intent.match.model_dump() if intent.match else None,
            description=f"明确允许 {len(src_hosts)} ↔ {len(dst_hosts)} 台主机",
            ryu_cookies=[cookie], created_at=time.time()
        )
        save_policies(_active_policies, _meter_counter)
        return {"success": True, "type": "allow_traffic", "message": f"成功下发允许规则：{len(src_hosts)} 到 {len(dst_hosts)} 台主机"}

    async def _rate_limit(self, intent: ParsedIntent, intent_id: str) -> Dict:
        """下发带宽限速策略，通过 Meter 表实现流量速率限制"""
        src_hosts = self._resolve_hosts(intent.source_nodes, intent.scope, intent.exclude_nodes)
        dst_hosts = self._resolve_hosts(intent.target_nodes, intent.scope, intent.exclude_nodes)
        if not src_hosts or not dst_hosts: return {"success": False, "error": "主机为空"}
        
        bw_mbps = float(intent.action_params.get("bandwidth_mbps", 10) if isinstance(intent.action_params, dict) else intent.action_params.bandwidth_mbps)
        rate_kbps = int(bw_mbps * 1000)
        cookie = _make_cookie(intent_id)
        
        src = src_hosts[0]
        dst = dst_hosts[0]
        src_dpid = topo_manager.get_switch_dpid(src.get("connected_switch")) or 1
        dst_dpid = topo_manager.get_switch_dpid(dst.get("connected_switch")) or 1

        m_fwd = _next_meter_id()
        m_rev = _next_meter_id()
        
        prio = intent.intent_priority if intent.intent_priority is not None else 400
        pm1 = NetworkPrimitive(primitive_type=PrimitiveType.METER_ENTRY, dpid=src_dpid, extra={"meter_id": m_fwd, "flags": "KBPS", "bands": [{"type": "DROP", "rate": rate_kbps}]})
        await ryu_client.apply_primitive(pm1)
        
        match_fwd = _build_match(src["mac"], dst["mac"], src.get("ip"), dst.get("ip"), intent.match)
        pf1 = NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=src_dpid, cookie=cookie, priority=prio, match=match_fwd, actions=[{"type": "METER", "meter_id": m_fwd}, {"type": "OUTPUT", "port": "NORMAL"}])
        await ryu_client.apply_primitive(pf1)

        meter_ids = [m_fwd]
        if intent.direction == "bidirectional":
            pm2 = NetworkPrimitive(primitive_type=PrimitiveType.METER_ENTRY, dpid=dst_dpid, extra={"meter_id": m_rev, "flags": "KBPS", "bands": [{"type": "DROP", "rate": rate_kbps}]})
            await ryu_client.apply_primitive(pm2)
            match_rev = _build_match(dst["mac"], src["mac"], dst.get("ip"), src.get("ip"), intent.match)
            pf2 = NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dst_dpid, cookie=cookie, priority=prio, match=match_rev, actions=[{"type": "METER", "meter_id": m_rev}, {"type": "OUTPUT", "port": "NORMAL"}])
            await ryu_client.apply_primitive(pf2)
            meter_ids.append(m_rev)

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id, policy_type=PolicyType.RATE_LIMIT, source_nodes=[src["id"]], target_nodes=[dst["id"]],
            intent_action=intent.action, ryu_cookies=[cookie], meter_ids=meter_ids, description=f"限速 {bw_mbps}M", created_at=time.time()
        )
        dir_text = "双向" if intent.direction == "bidirectional" else "单向"
        return {"success": True, "type": "rate_limit", "message": f"{dir_text}限速 {bw_mbps}Mbps 成功"}

    async def _set_priority(self, intent: ParsedIntent, intent_id: str) -> Dict:
        """下发优先级转发策略，安装指定优先级的 NORMAL 转发规则"""
        src_hosts = self._resolve_hosts(intent.source_nodes, intent.scope, intent.exclude_nodes)
        dst_hosts = self._resolve_hosts(intent.target_nodes, intent.scope, intent.exclude_nodes)
        if not src_hosts or not dst_hosts: return {"success": False, "error": "主机为空"}
        
        priority = int(intent.action_params.get("priority", 200) if isinstance(intent.action_params, dict) else intent.action_params.priority)
        cookie = _make_cookie(intent_id)
        target_dpids = self._get_target_dpids(src_hosts, dst_hosts)

        primitives = []
        prio = intent.intent_priority if intent.intent_priority is not None else priority
        
        for src in src_hosts:
            for dst in dst_hosts:
                match_fwd = _build_match(src["mac"], dst["mac"], src.get("ip"), dst.get("ip"), intent.match)
                match_rev = _build_match(dst["mac"], src["mac"], dst.get("ip"), src.get("ip"), intent.match)
                
                for dpid in target_dpids:
                    primitives.append(NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=prio, match=match_fwd, actions=[{"type": "OUTPUT", "port": "NORMAL"}]))
                    if intent.direction == "bidirectional":
                        primitives.append(NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=prio, match=match_rev, actions=[{"type": "OUTPUT", "port": "NORMAL"}]))

        import asyncio
        await asyncio.gather(*(ryu_client.apply_primitive(p) for p in primitives))

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id, policy_type=PolicyType.PRIORITY, source_nodes=intent.source_nodes, target_nodes=intent.target_nodes,
            intent_action=intent.action, ryu_cookies=[cookie], description=f"设优先级 {priority}", created_at=time.time()
        )
        save_policies(_active_policies, _meter_counter)
        return {"success": True, "type": "set_priority", "message": f"已设置 {len(primitives)} 条优先转发规则"}

    async def _clear_flows(self, intent: ParsedIntent, intent_id: str) -> Dict:
        """清除指定交换机上所有 IBN 自定义流表规则"""
        sw = intent.target_switch
        dpids = [topo_manager.get_switch_dpid(sw)] if sw else topo_manager.get_all_switch_dpids()
        
        removed_count = 0
        policies_to_remove = set()
        for pol_id, pol in list(_active_policies.items()):
            policies_to_remove.add(pol_id)
            for dpid in dpids:
                if dpid:
                    for cookie in pol.ryu_cookies:
                        await ryu_client.delete_flows_by_cookie(dpid, cookie)
                    for mid in pol.meter_ids:
                        await ryu_client.delete_primitive(NetworkPrimitive(primitive_type=PrimitiveType.METER_ENTRY, dpid=dpid, extra={"meter_id": mid}))
                        await ryu_client.delete_primitive(NetworkPrimitive(primitive_type=PrimitiveType.GROUP_ENTRY, dpid=dpid, extra={"group_id": mid}))

        for pid in policies_to_remove:
            if pid in _active_policies: del _active_policies[pid]
            removed_count += 1

        save_policies(_active_policies, _meter_counter)
        return {"success": True, "type": "clear_flows", "message": f"清除了 {removed_count} 条策略"}

    # ── 高级扩展能力 ──────────────────────────────────────

    async def _acl(self, intent: ParsedIntent, intent_id: str) -> Dict:
        """ACL 访问控制（复用阻断逻辑）"""
        return await self._block_traffic(intent, intent_id)

    async def _qos_mark(self, intent: ParsedIntent, intent_id: str) -> Dict:
        """下发 QoS DSCP 标记策略"""
        src_hosts = self._resolve_hosts(intent.source_nodes, intent.scope, intent.exclude_nodes)
        dst_hosts = self._resolve_hosts(intent.target_nodes, intent.scope, intent.exclude_nodes)
        dscp = int(intent.action_params.get("dscp", 0) if isinstance(intent.action_params, dict) else intent.action_params.dscp)
        
        cookie = _make_cookie(intent_id)
        target_dpids = self._get_target_dpids(src_hosts, dst_hosts)

        primitives = []
        prio = intent.intent_priority if intent.intent_priority is not None else 600
        for src in src_hosts:
            for dst in dst_hosts:
                match = _build_match(src["mac"], dst["mac"], src.get("ip"), dst.get("ip"), intent.match)
                match["eth_type"] = 0x0800 # 强制 IPv4 才能改 DSCP
                actions = [
                    {"type": "SET_FIELD", "field": "ip_dscp", "value": dscp},
                    {"type": "OUTPUT", "port": "NORMAL"}
                ]
                for dpid in target_dpids:
                    primitives.append(NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=prio, match=match, actions=actions))
                if intent.direction == "bidirectional":
                    match_rev = _build_match(dst["mac"], src["mac"], dst.get("ip"), src.get("ip"), intent.match)
                    match_rev["eth_type"] = 0x0800
                    actions_rev = [
                        {"type": "SET_FIELD", "field": "ip_dscp", "value": dscp},
                        {"type": "OUTPUT", "port": "NORMAL"}
                    ]
                    for dpid in target_dpids:
                        primitives.append(NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=prio, match=match_rev, actions=actions_rev))

        import asyncio
        await asyncio.gather(*(ryu_client.apply_primitive(p) for p in primitives))

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id, policy_type=PolicyType.QOS_MARK, source_nodes=intent.source_nodes, target_nodes=intent.target_nodes,
            intent_action=intent.action, ryu_cookies=[cookie], description=f"DSCP 标记 {dscp}", created_at=time.time()
        )
        save_policies(_active_policies, _meter_counter)
        return {"success": True, "message": f"成功下发 DSCP = {dscp} 标记策略"}

    async def _vlan(self, intent: ParsedIntent, intent_id: str) -> Dict:
        """下发 VLAN 划分策略，将指定主机隔离到独立 VLAN"""
        src_hosts = self._resolve_hosts(intent.source_nodes, intent.scope, intent.exclude_nodes)
        if not src_hosts:
            return {"success": False, "error": "目标主机为空"}

        vid = int(intent.action_params.get("vlan_id", 0) if isinstance(intent.action_params, dict) else intent.action_params.vlan_id)
        if not vid:
            return {"success": False, "error": "无效的 VLAN ID"}

        cookie = _make_cookie(intent_id)
        primitives = []
        prio = intent.intent_priority if intent.intent_priority is not None else 600

        for h_src in src_hosts:
            src_mac = h_src["mac"]
            port_raw = h_src.get("port")
            sw_name = h_src.get("connected_switch")
            dpid = topo_manager.get_switch_dpid(sw_name)
            
            if not port_raw or not dpid:
                continue
                
            port = int(port_raw, 16) if isinstance(port_raw, str) else int(port_raw)

            # 1. 允许同 VLAN 内成员互通 (Unicast)
            for h_dst in src_hosts:
                if h_src["id"] == h_dst["id"]:
                    continue
                match_uni = {"in_port": port, "eth_src": src_mac, "eth_dst": h_dst["mac"]}
                actions_uni = [
                    {"type": "PUSH_VLAN", "ethertype": 33024},
                    {"type": "SET_FIELD", "field": "vlan_vid", "value": vid | 4096},
                    {"type": "POP_VLAN"},
                    {"type": "OUTPUT", "port": "NORMAL"}
                ]
                primitives.append(NetworkPrimitive(
                    primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=prio, match=match_uni, actions=actions_uni
                ))

            # 2. 允许该主机的广播流量 (ARP等) 
            match_bcast = {"in_port": port, "eth_src": src_mac, "eth_dst": "ff:ff:ff:ff:ff:ff"}
            actions_bcast = [
                {"type": "PUSH_VLAN", "ethertype": 33024},
                {"type": "SET_FIELD", "field": "vlan_vid", "value": vid | 4096},
                {"type": "POP_VLAN"},
                {"type": "OUTPUT", "port": "NORMAL"}
            ]
            primitives.append(NetworkPrimitive(
                primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=prio, match=match_bcast, actions=actions_bcast
            ))

            # 3. 隔离（丢弃）该主机发往非 VLAN 成员的任何其他流量 (降低优先级)
            match_drop = {"in_port": port, "eth_src": src_mac}
            primitives.append(NetworkPrimitive(
                primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=prio - 1, match=match_drop, actions=[]
            ))

        if not primitives:
            return {"success": False, "error": "无法解析主机的网络位置，划分 VLAN 失败"}

        import asyncio
        results = await asyncio.gather(*(ryu_client.apply_primitive(p) for p in primitives))

        if not all(results):
            for p in primitives: await ryu_client.delete_primitive(p)
            return {"success": False, "error": "部分交换机硬件不支持该操作，流表下发失败"}

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id, policy_type=PolicyType.VLAN, scope=intent.scope,
            source_nodes=[h["id"] for h in src_hosts], target_nodes=[],
            intent_action=intent.action, action_params={"vlan_id": vid},
            ryu_cookies=[cookie], description=f"划分至 VLAN {vid}", created_at=time.time()
        )
        save_policies(_active_policies, _meter_counter)
        return {"success": True, "type": "vlan", "message": f"成功将 {len(src_hosts)} 台主机划分至 VLAN {vid}"}

    async def _multipath(self, intent: ParsedIntent, intent_id: str) -> Dict:
        """下发多路径负载均衡策略，使用 Group Table 实现 WCMP"""
        src_hosts = self._resolve_hosts(intent.source_nodes, intent.scope, intent.exclude_nodes)
        dst_hosts = self._resolve_hosts(intent.target_nodes, intent.scope, intent.exclude_nodes)
        if not src_hosts or not dst_hosts:
            return {"success": False, "error": "源或目标主机解析为空"}

        cookie = _make_cookie(intent_id)
        primitives = []
        group_ids = []
        prio = intent.intent_priority if intent.intent_priority is not None else 700

        async def install_multipath(src_host, dst_host):
            src_sw_name = src_host.get("connected_switch")
            dst_sw_name = dst_host.get("connected_switch")
            if not src_sw_name or not dst_sw_name: return
            
            src_dpid = topo_manager.get_switch_dpid(src_sw_name)
            dst_dpid = topo_manager.get_switch_dpid(dst_sw_name)
            
            paths = topo_manager.get_all_shortest_paths(src_sw_name, dst_sw_name)
            if not paths or len(paths) < 2:
                raise ValueError(f"{src_host['id']} 到 {dst_host['id']} 之间没有冗余的等价最短路径，无法执行负载均衡。")

            next_hops = {}
            for path in paths:
                for i in range(len(path) - 1):
                    next_hops.setdefault(path[i], set()).add(path[i+1])

            base_match = _build_match(src_host["mac"], dst_host["mac"], src_host.get("ip"), dst_host.get("ip"), intent.match)
            
            matches_to_install = [(base_match, prio)]
            if "ip_proto" not in base_match and "ipv4_src" in base_match:
                match_tcp = dict(base_match)
                match_tcp["ip_proto"] = 6
                match_udp = dict(base_match)
                match_udp["ip_proto"] = 17
                matches_to_install = [(match_tcp, prio + 1), (match_udp, prio + 1), (base_match, prio)]
            
            for current_node, next_nodes in next_hops.items():
                dpid = topo_manager.get_switch_dpid(current_node)
                if not dpid: continue
                if len(next_nodes) == 1:
                    out_port_raw = topo_manager.get_link_port(current_node, list(next_nodes)[0])
                    if out_port_raw:
                        out_port = int(out_port_raw, 16) if isinstance(out_port_raw, str) else int(out_port_raw)
                        for m, p in matches_to_install:
                            primitives.append(NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=p, match=m, actions=[{"type": "OUTPUT", "port": out_port}]))
                else:
                    group_id = _next_meter_id()
                    group_ids.append(group_id)
                    buckets = []
                    port_desc_list = await ryu_client.get_port_desc(dpid)
                    port_speeds = {p.get("port_no"): p.get("curr_speed", 1000000) for p in port_desc_list}
                    for next_node in next_nodes:
                        out_port_raw = topo_manager.get_link_port(current_node, next_node)
                        if out_port_raw:
                            out_port = int(out_port_raw, 16) if isinstance(out_port_raw, str) else int(out_port_raw)
                            weight = max(1, int(port_speeds.get(out_port, 1000000) / 1000))
                            buckets.append({"weight": weight, "actions": [{"type": "OUTPUT", "port": out_port}]})
                    if buckets:
                        primitives.append(NetworkPrimitive(primitive_type=PrimitiveType.GROUP_ENTRY, dpid=dpid, extra={"type": "SELECT", "group_id": group_id, "buckets": buckets}))
                        for m, p in matches_to_install:
                            primitives.append(NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dpid, cookie=cookie, priority=p, match=m, actions=[{"type": "GROUP", "group_id": group_id}]))
            
            dst_port_raw = dst_host.get("port")
            dst_port = int(dst_port_raw, 16) if isinstance(dst_port_raw, str) else (int(dst_port_raw) if dst_port_raw else 0)
            if dst_port:
                for m, p in matches_to_install:
                    primitives.append(NetworkPrimitive(primitive_type=PrimitiveType.FLOW_ENTRY, dpid=dst_dpid, cookie=cookie, priority=p, match=m, actions=[{"type": "OUTPUT", "port": dst_port}]))

        try:
            for src in src_hosts:
                for dst in dst_hosts:
                    if src["id"] == dst["id"]: continue
                    await install_multipath(src, dst)
                    if intent.direction == "bidirectional":
                        await install_multipath(dst, src)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        import asyncio
        group_prims = [p for p in primitives if p.primitive_type == PrimitiveType.GROUP_ENTRY]
        flow_prims = [p for p in primitives if p.primitive_type == PrimitiveType.FLOW_ENTRY]
        
        # 必须严格保证：先下发 Group Table
        if group_prims:
            group_results = await asyncio.gather(*(ryu_client.apply_primitive(p) for p in group_prims))
            if not all(group_results):
                return {"success": False, "error": "部分交换机不支持 Group Table，智能多路径规则下发失败。"}
        
        # Group Table 生效后，再下发引用它的 Flow Table
        if flow_prims:
            flow_results = await asyncio.gather(*(ryu_client.apply_primitive(p) for p in flow_prims))
            if not all(flow_results):
                for d in topo_manager.get_all_switch_dpids(): await ryu_client.delete_flows_by_cookie(d, cookie)
                return {"success": False, "error": "流表规则下发失败。"}

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id, policy_type=PolicyType.MULTIPATH, scope=intent.scope,
            source_nodes=intent.source_nodes, target_nodes=intent.target_nodes, exclude_nodes=intent.exclude_nodes,
            intent_action=intent.action, action_params={},
            match=intent.match.model_dump() if intent.match else None,
            description=f"多路径智能加权 (WCMP): {len(src_hosts)} ↔ {len(dst_hosts)}",
            ryu_cookies=[cookie], meter_ids=group_ids, created_at=time.time()
        )
        save_policies(_active_policies, _meter_counter)
        return {"success": True, "type": "multipath", "message": f"成功启用了带带宽感知 (WCMP) 的链路多路径负载均衡！"}

    # ── 接口 ──────────────────────────────────────────────

    def get_active_policies(self) -> List[Dict]:
        """获取当前所有活跃策略"""
        return [p.model_dump() for p in _active_policies.values()]

    async def delete_policy(self, policy_id: str) -> Tuple[bool, str]:
        """撤销指定策略，从所有交换机删除关联的流表、Meter 和 Group"""
        pol = _active_policies.get(policy_id)
        if not pol: return False, "策略不存在"
        
        dpids = topo_manager.get_all_switch_dpids()
        for dpid in dpids:
            for cookie in pol.ryu_cookies:
                await ryu_client.delete_flows_by_cookie(dpid, cookie)
            for mid in pol.meter_ids:
                await ryu_client.delete_primitive(NetworkPrimitive(primitive_type=PrimitiveType.METER_ENTRY, dpid=dpid, extra={"meter_id": mid}))
                await ryu_client.delete_primitive(NetworkPrimitive(primitive_type=PrimitiveType.GROUP_ENTRY, dpid=dpid, extra={"group_id": mid}))

        desc = pol.description
        del _active_policies[policy_id]
        save_policies(_active_policies, _meter_counter)
        return True, f"已撤销: {desc}"

    async def sync_with_data_plane(self):
        """与数据平面同步（预留接口）"""
        pass

policy_executor = PolicyExecutor()
