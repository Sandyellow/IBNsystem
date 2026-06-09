"""
策略执行器 — 将解析好的 ParsedIntent 直接映射到 Ryu REST API 调用
核心设计：无中间抽象层，意图→Ryu API 一步到位，返回真实执行结果
"""
from __future__ import annotations
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from core.ryu_client import ryu_client
from core.topo_manager import topo_manager, _is_placeholder_mac
from models.intent import ParsedIntent, IntentAction
from models.policy import ActivePolicy, PolicyType

from core.policy_store import load_policies, save_policies

logger = logging.getLogger(__name__)

# 从本地加载持久化策略和计数器
_active_policies, _meter_counter = load_policies()


def _next_meter_id() -> int:
    global _meter_counter
    _meter_counter += 1
    return _meter_counter


def _make_cookie(intent_id: str) -> int:
    """从 intent_id 生成稳定的 64-bit cookie，用于标识和精准删除流表"""
    h = hashlib.md5(intent_id.encode()).hexdigest()[:15]
    return int(h, 16)


class PolicyExecutor:

    async def execute(self, intent: ParsedIntent, intent_id: str) -> Dict[str, Any]:
        """执行意图，返回包含真实 Ryu 执行结果的字典"""
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
                IntentAction.REDIRECT_TRAFFIC: self._redirect_traffic,
                IntentAction.CLEAR_FLOWS:      self._clear_flows,
                IntentAction.ADD_FLOW:         self._unimplemented,
                IntentAction.DELETE_FLOW:      self._unimplemented,
                IntentAction.LOAD_BALANCE:     self._unimplemented,
            }
            handler = handlers.get(action)
            if handler is None:
                return {"success": False, "error": f"不支持的操作: {action}"}
            return await handler(intent, intent_id)
        except Exception as e:
            logger.error(f"[PolicyExecutor] {action}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _unimplemented(self, intent: ParsedIntent, intent_id: str) -> Dict:
        return {"success": False, "error": f"功能尚未实现: {intent.action.value}"}

    # ── 查询操作 ──────────────────────────────────────────

    async def _query_topology(self, intent: ParsedIntent, _: str) -> Dict:
        topo = topo_manager.topology
        nodes = topo.get("nodes", [])
        links = topo.get("links", [])
        switches = [n for n in nodes if n.get("type") == "switch"]
        hosts = [n for n in nodes if n.get("type") == "host"]
        return {
            "success": True,
            "type": "query_topology",
            "data": topo,
            "message": (
                f"当前拓扑：{len(switches)} 台交换机，{len(hosts)} 台主机，"
                f"{len(links)} 条链路"
            ),
        }

    async def _query_flows(self, intent: ParsedIntent, _: str) -> Dict:
        sw = intent.target_switch
        if sw:
            dpid = topo_manager.get_switch_dpid(sw)
            if dpid is None:
                return {"success": False, "error": f"找不到交换机: {sw}"}
            dpids = [dpid]
        else:
            dpids = topo_manager.get_all_switch_dpids()

        all_flows: Dict[str, List] = {}
        for dpid in dpids:
            flows = await ryu_client.get_flows(dpid)
            all_flows[str(dpid)] = flows

        total = sum(len(v) for v in all_flows.values())
        return {
            "success": True,
            "type": "query_flows",
            "data": all_flows,
            "message": f"共 {total} 条流表规则（覆盖 {len(dpids)} 台交换机）",
        }

    async def _query_port_stats(self, intent: ParsedIntent, _: str) -> Dict:
        sw = intent.target_switch
        if sw:
            dpid = topo_manager.get_switch_dpid(sw)
            dpids = [dpid] if dpid else []
        else:
            dpids = topo_manager.get_all_switch_dpids()

        stats: Dict[str, List] = {}
        for dpid in dpids:
            s = await ryu_client.get_port_stats(dpid)
            stats[str(dpid)] = s

        return {
            "success": True,
            "type": "query_port_stats",
            "data": stats,
            "message": f"已获取 {len(dpids)} 台交换机的端口统计",
        }

    # ── 控制操作 ──────────────────────────────────────────

    async def _block_traffic(self, intent: ParsedIntent, intent_id: str) -> Dict:
        src_info = topo_manager.get_host(intent.source_node)
        dst_info = topo_manager.get_host(intent.target_node)
        if not src_info or not dst_info:
            return {"success": False, "error": f"主机不存在: {intent.source_node} 或 {intent.target_node}"}

        src_mac = src_info["mac"]
        dst_mac = dst_info["mac"]

        # 检测是否获取到了占位符假 MAC，若是则触发重新发现后重试一次
        if _is_placeholder_mac(src_mac) or _is_placeholder_mac(dst_mac):
            logger.warning(
                f"[PolicyExecutor] 检测到占位符 MAC（{src_mac}, {dst_mac}），"
                "触发主机重新发现..."
            )
            await topo_manager.fetch_host_config()
            src_info = topo_manager.get_host(intent.source_node)
            dst_info = topo_manager.get_host(intent.target_node)
            if not src_info or not dst_info:
                return {"success": False, "error": "重新发现后主机信息仍不存在"}
            src_mac = src_info["mac"]
            dst_mac = dst_info["mac"]
            if _is_placeholder_mac(src_mac) or _is_placeholder_mac(dst_mac):
                return {
                    "success": False,
                    "error": (
                        f"无法获取 {intent.source_node}/{intent.target_node} 的真实 MAC。"
                        "请确认 Mininet 网络已启动，Ryu 控制器已学习到主机信息（可先执行 ping 测试触发学习）"
                    ),
                }
        cookie = _make_cookie(intent_id)
        
        # 获取通信双方连接的边缘交换机
        src_sw_name = src_info.get("connected_switch")
        dst_sw_name = dst_info.get("connected_switch")
        
        target_dpids = set()
        if src_sw_name:
            dpid = topo_manager.get_switch_dpid(src_sw_name)
            if dpid: target_dpids.add(dpid)
        if dst_sw_name:
            dpid = topo_manager.get_switch_dpid(dst_sw_name)
            if dpid: target_dpids.add(dpid)
            
        # 容错：如果找不到边缘交换机，则使用全局（尽管这应该很少发生）
        if not target_dpids:
            target_dpids = set(topo_manager.get_all_switch_dpids())

        import asyncio
        
        base_match = {"eth_src": src_mac, "eth_dst": dst_mac}
        rev_match = {"eth_src": dst_mac, "eth_dst": src_mac}
        
        # 为了前端能展示 IP 且匹配更精确，我们指定协议类型为 IPv4 并加入 IP 匹配
        # 注意：一旦加入 IP 匹配，必须设置 eth_type = 0x0800
        if src_info.get("ip") and dst_info.get("ip"):
            base_match["eth_type"] = 0x0800
            base_match["ipv4_src"] = src_info["ip"]
            base_match["ipv4_dst"] = dst_info["ip"]
            
            rev_match["eth_type"] = 0x0800
            rev_match["ipv4_src"] = dst_info["ip"]
            rev_match["ipv4_dst"] = src_info["ip"]

        async def deploy_to_switch(dpid):
            ok1 = await ryu_client.add_flow({
                "dpid": dpid,
                "cookie": cookie,
                "priority": 500,
                "match": base_match,
                "actions": [],
            })
            ok2 = await ryu_client.add_flow({
                "dpid": dpid,
                "cookie": cookie,
                "priority": 500,
                "match": rev_match,
                "actions": [],
            })
            return dpid if (ok1 and ok2) else None

        target_dpids_list = list(target_dpids)
        results = await asyncio.gather(*(deploy_to_switch(d) for d in target_dpids_list))
        installed_dpids = [r for r in results if r is not None]
        errors = [d for r, d in zip(results, target_dpids_list) if r is None]

        if errors:
            logger.warning(f"[_block_traffic] 发现失败，开始执行 Rollback: 清除 {installed_dpids} 上的脏流表 (cookie={cookie})")
            await asyncio.gather(*(ryu_client.delete_flow_by_cookie(d, cookie) for d in installed_dpids))
            return {"success": False, "error": f"下发失败 (失败交换机 DPID 列表: {errors})，系统已安全回滚"}

        installed = [f"s{d}" for d in installed_dpids]

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id,
            policy_type=PolicyType.BLOCK,
            src_host=intent.source_node,
            dst_host=intent.target_node,
            intent_action=intent.action,
            parameters=intent.parameters,
            description=f"隔离 {intent.source_node} ↔ {intent.target_node}",
            ryu_cookies=[cookie],
            created_at=time.time(),
        )
        save_policies(_active_policies, _meter_counter)

        return {
            "success": True,
            "type": "block_traffic",
            "installed_on": installed,
            "src_mac": src_mac,
            "dst_mac": dst_mac,
            "cookie": cookie,
            "message": (
                f"已在 {', '.join(installed)} 上安装双向隔离规则（优先级500），"
                f"阻断 {intent.source_node}({src_mac}) ↔ {intent.target_node}({dst_mac}) 的全部通信"
            ),
        }

    async def _allow_traffic(self, intent: ParsedIntent, intent_id: str) -> Dict:
        src_info = topo_manager.get_host(intent.source_node)
        dst_info = topo_manager.get_host(intent.target_node)
        if not src_info or not dst_info:
            return {"success": False, "error": f"主机不存在: {intent.source_node} 或 {intent.target_node}"}

        # 找到所有匹配的 block 策略
        target_pair = {intent.source_node, intent.target_node}
        removed_cookies: List[int] = []
        removed_desc: List[str] = []

        for pol_id, pol in list(_active_policies.items()):
            if pol.policy_type == PolicyType.BLOCK and {pol.src_host, pol.dst_host} == target_pair:
                removed_cookies.extend(pol.ryu_cookies)
                removed_desc.append(pol.description)
                del _active_policies[pol_id]

        if removed_cookies:
            save_policies(_active_policies, _meter_counter)

        if not removed_cookies:
            return {
                "success": True,
                "type": "allow_traffic",
                "message": f"未找到 {intent.source_node}↔{intent.target_node} 的隔离策略，无需操作",
            }

        dpids = topo_manager.get_all_switch_dpids()
        for dpid in dpids:
            for cookie in removed_cookies:
                await ryu_client.delete_flow_by_cookie(dpid, cookie)

        return {
            "success": True,
            "type": "allow_traffic",
            "removed_policies": removed_desc,
            "message": (
                f"已恢复 {intent.source_node}↔{intent.target_node} 的通信，"
                f"删除了 {len(removed_cookies)} 组隔离规则"
            ),
        }

    async def _rate_limit(self, intent: ParsedIntent, intent_id: str) -> Dict:
        src_info = topo_manager.get_host(intent.source_node)
        dst_info = topo_manager.get_host(intent.target_node)
        if not src_info or not dst_info:
            return {"success": False, "error": f"主机不存在: {intent.source_node} 或 {intent.target_node}"}

        src_mac = src_info["mac"]
        dst_mac = dst_info["mac"]

        # 与 block_traffic 保持一致：检测占位符 MAC，触发重新发现
        if _is_placeholder_mac(src_mac) or _is_placeholder_mac(dst_mac):
            logger.warning(
                f"[PolicyExecutor] 限速操作检测到占位符 MAC（{src_mac}, {dst_mac}），"
                "触发主机重新发现..."
            )
            await topo_manager.fetch_host_config()
            src_info = topo_manager.get_host(intent.source_node)
            dst_info = topo_manager.get_host(intent.target_node)
            if not src_info or not dst_info:
                return {"success": False, "error": "重新发现后主机信息仍不存在"}
            src_mac = src_info["mac"]
            dst_mac = dst_info["mac"]
            if _is_placeholder_mac(src_mac) or _is_placeholder_mac(dst_mac):
                return {
                    "success": False,
                    "error": (
                        f"无法获取 {intent.source_node}/{intent.target_node} 的真实 MAC。"
                        "请确认 Mininet 网络已启动，Ryu 控制器已学习到主机信息（可先执行 ping 测试触发学习）"
                    ),
                }

        bw_mbps = float(intent.parameters.get("bandwidth_mbps", 10))
        rate_kbps = int(bw_mbps * 1000)
        cookie = _make_cookie(intent_id)

        # 获取两端的交换机，准备双向限速
        src_sw_name = src_info.get("connected_switch")
        dst_sw_name = dst_info.get("connected_switch")
        
        src_dpid = topo_manager.get_switch_dpid(src_sw_name) if src_sw_name else 1
        dst_dpid = topo_manager.get_switch_dpid(dst_sw_name) if dst_sw_name else 1

        meter_id_fwd = _next_meter_id()
        meter_id_rev = _next_meter_id()
        
        meter_config = {
            "flags": ["KBPS"],
            "bands": [{"type": "DROP", "rate": rate_kbps, "burst_size": max(10, rate_kbps // 10)}],
        }

        import asyncio

        base_match = {"eth_type": 0x0800, "eth_src": src_mac, "eth_dst": dst_mac}
        rev_match = {"eth_type": 0x0800, "eth_src": dst_mac, "eth_dst": src_mac}
        if src_info.get("ip") and dst_info.get("ip"):
            base_match["ipv4_src"] = src_info["ip"]
            base_match["ipv4_dst"] = dst_info["ip"]
            rev_match["ipv4_src"] = dst_info["ip"]
            rev_match["ipv4_dst"] = src_info["ip"]

        # 在源交换机限制 src->dst 的正向流量
        m1_ok = await ryu_client.add_meter({"dpid": src_dpid, "meter_id": meter_id_fwd, **meter_config})
        if not m1_ok:
            return {"success": False, "error": f"创建源交换机 Meter 失败 (dpid={src_dpid})"}

        # 在目的交换机限制 dst->src 的反向流量
        m2_ok = await ryu_client.add_meter({"dpid": dst_dpid, "meter_id": meter_id_rev, **meter_config})
        if not m2_ok:
            await ryu_client.delete_meter(src_dpid, meter_id_fwd)
            return {"success": False, "error": f"创建目的交换机 Meter 失败 (dpid={dst_dpid})，已回滚"}

        # 安装限速流表
        f1_ok = await ryu_client.add_flow({
            "dpid": src_dpid,
            "cookie": cookie,
            "priority": 400,
            "match": base_match,
            "actions": [
                {"type": "METER", "meter_id": meter_id_fwd},
                {"type": "OUTPUT", "port": "NORMAL"},
            ],
        })

        f2_ok = await ryu_client.add_flow({
            "dpid": dst_dpid,
            "cookie": cookie,
            "priority": 400,
            "match": rev_match,
            "actions": [
                {"type": "METER", "meter_id": meter_id_rev},
                {"type": "OUTPUT", "port": "NORMAL"},
            ],
        })

        if not (f1_ok and f2_ok):
            logger.warning("[_rate_limit] 发现失败，开始执行 Rollback")
            await ryu_client.delete_flow_by_cookie(src_dpid, cookie)
            await ryu_client.delete_flow_by_cookie(dst_dpid, cookie)
            await ryu_client.delete_meter(src_dpid, meter_id_fwd)
            await ryu_client.delete_meter(dst_dpid, meter_id_rev)
            return {"success": False, "error": "创建限速流表失败，已回滚全套 Meter 和流表"}

        meter_ids = [meter_id_fwd]
        installed_on = [f"{src_sw_name}({src_dpid})"]
        if src_dpid != dst_dpid:
            meter_ids.append(meter_id_rev)
            installed_on.append(f"{dst_sw_name}({dst_dpid})")

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id,
            policy_type=PolicyType.RATE_LIMIT,
            src_host=intent.source_node,
            dst_host=intent.target_node,
            intent_action=intent.action,
            parameters=intent.parameters,
            description=f"双向限速 {intent.source_node}↔{intent.target_node} ≤{bw_mbps}Mbps",
            ryu_cookies=[cookie],
            meter_ids=meter_ids,
            created_at=time.time(),
        )
        save_policies(_active_policies, _meter_counter)

        return {
            "success": True,
            "type": "rate_limit",
            "installed_switches": installed_on,
            "meter_ids": meter_ids,
            "rate_kbps": rate_kbps,
            "bw_mbps": bw_mbps,
            "src_mac": src_mac,
            "dst_mac": dst_mac,
            "message": (
                f"已在 {', '.join(installed_on)} 创建双向 Meter（{bw_mbps}Mbps 限速），"
                f"关联流表 cookie={hex(cookie)}。"
            ),
        }

    async def _set_priority(self, intent: ParsedIntent, intent_id: str) -> Dict:
        src_info = topo_manager.get_host(intent.source_node)
        dst_info = topo_manager.get_host(intent.target_node)
        if not src_info or not dst_info:
            return {"success": False, "error": f"主机不存在: {intent.source_node} 或 {intent.target_node}"}

        priority = int(intent.parameters.get("priority", 200))
        src_mac = src_info["mac"]
        dst_mac = dst_info["mac"]
        cookie = _make_cookie(intent_id)
        
        # 获取通信双方连接的边缘交换机
        src_sw_name = src_info.get("connected_switch")
        dst_sw_name = dst_info.get("connected_switch")
        
        target_dpids = set()
        if src_sw_name:
            dpid = topo_manager.get_switch_dpid(src_sw_name)
            if dpid: target_dpids.add(dpid)
        if dst_sw_name:
            dpid = topo_manager.get_switch_dpid(dst_sw_name)
            if dpid: target_dpids.add(dpid)
            
        if not target_dpids:
            target_dpids = set(topo_manager.get_all_switch_dpids())

        import asyncio
        
        base_match = {"eth_type": 0x0800, "eth_src": src_mac, "eth_dst": dst_mac}
        rev_match = {"eth_type": 0x0800, "eth_src": dst_mac, "eth_dst": src_mac}
        if src_info.get("ip") and dst_info.get("ip"):
            base_match["ipv4_src"] = src_info["ip"]
            base_match["ipv4_dst"] = dst_info["ip"]
            rev_match["ipv4_src"] = dst_info["ip"]
            rev_match["ipv4_dst"] = src_info["ip"]

        async def deploy_to_switch(dpid):
            ok1 = await ryu_client.add_flow({
                "dpid": dpid,
                "cookie": cookie,
                "priority": priority,
                "match": base_match,
                "actions": [{"type": "OUTPUT", "port": "NORMAL"}],
            })
            ok2 = await ryu_client.add_flow({
                "dpid": dpid,
                "cookie": cookie,
                "priority": priority,
                "match": rev_match,
                "actions": [{"type": "OUTPUT", "port": "NORMAL"}],
            })
            return dpid if (ok1 and ok2) else None

        target_dpids_list = list(target_dpids)
        results = await asyncio.gather(*(deploy_to_switch(d) for d in target_dpids_list))
        installed_dpids = [r for r in results if r is not None]
        errors = [d for r, d in zip(results, target_dpids_list) if r is None]

        if errors:
            logger.warning(f"[_set_priority] 发现失败，开始执行 Rollback: 清除 {installed_dpids} 上的脏流表 (cookie={cookie})")
            await asyncio.gather(*(ryu_client.delete_flow_by_cookie(d, cookie) for d in installed_dpids))
            return {"success": False, "error": f"下发失败 (失败交换机 DPID 列表: {errors})，系统已安全回滚"}

        installed = [f"s{d}" for d in installed_dpids]

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id,
            policy_type=PolicyType.PRIORITY,
            src_host=intent.source_node,
            dst_host=intent.target_node,
            intent_action=intent.action,
            parameters=intent.parameters,
            description=f"优先级 {priority}: {intent.source_node}→{intent.target_node}",
            ryu_cookies=[cookie],
            created_at=time.time(),
        )
        save_policies(_active_policies, _meter_counter)

        return {
            "success": True,
            "type": "set_priority",
            "priority": priority,
            "installed_on": installed,
            "message": f"已为 {intent.source_node}→{intent.target_node} 在 {', '.join(installed)} 上设置优先级 {priority} 的转发规则",
        }

    async def _redirect_traffic(self, intent: ParsedIntent, intent_id: str) -> Dict:
        src_info = topo_manager.get_host(intent.source_node)
        dst_info = topo_manager.get_host(intent.target_node)
        if not src_info or not dst_info:
            return {"success": False, "error": f"主机不存在: {intent.source_node} 或 {intent.target_node}"}

        # 兼容 LLM 输出的 via_node 或 via_switch
        via_sw = intent.parameters.get("via_node") or intent.parameters.get("via_switch")
        if not via_sw:
            return {"success": False, "error": "重定向策略未指定中转节点 (via_node)"}

        src_sw_name = src_info.get("connected_switch")
        dst_sw_name = dst_info.get("connected_switch")
        if not src_sw_name or not dst_sw_name:
            return {"success": False, "error": "无法确定主机的连接交换机，重定向失败"}

        src_mac = src_info["mac"]
        dst_mac = dst_info["mac"]
        cookie = _make_cookie(intent_id)

        # 1. 计算正向路径：src_sw -> via_sw -> dst_sw
        path_a = topo_manager.get_shortest_path(src_sw_name, via_sw)
        path_b = topo_manager.get_shortest_path(via_sw, dst_sw_name)
        if not path_a or not path_b:
            return {"success": False, "error": f"无法找到从 {src_sw_name} 经 {via_sw} 到 {dst_sw_name} 的物理路径"}
        # 拼接正向全路径（去除重复的 via_sw）
        fwd_path = path_a[:-1] + path_b

        # 2. 计算反向路径：dst_sw -> via_sw -> src_sw
        path_c = topo_manager.get_shortest_path(dst_sw_name, via_sw)
        path_d = topo_manager.get_shortest_path(via_sw, src_sw_name)
        rev_path = (path_c[:-1] + path_d) if (path_c and path_d) else []

        base_match = {"eth_type": 0x0800, "eth_src": src_mac, "eth_dst": dst_mac}
        rev_match = {"eth_type": 0x0800, "eth_src": dst_mac, "eth_dst": src_mac}
        if src_info.get("ip") and dst_info.get("ip"):
            base_match["ipv4_src"] = src_info["ip"]
            base_match["ipv4_dst"] = dst_info["ip"]
            rev_match["ipv4_src"] = dst_info["ip"]
            rev_match["ipv4_dst"] = src_info["ip"]

        import asyncio
        installed_nodes = []

        async def install_hop(sw_name: str, next_hop: str, match: dict) -> bool:
            out_port = topo_manager.get_link_port(sw_name, next_hop)
            if not out_port:
                logger.error(f"找不到从 {sw_name} 到 {next_hop} 的端口")
                return False
            dpid = topo_manager.get_switch_dpid(sw_name)
            if not dpid: return False
            
            ok = await ryu_client.add_flow({
                "dpid": dpid,
                "cookie": cookie,
                "priority": 450,
                "match": match,
                "actions": [{"type": "OUTPUT", "port": int(out_port)}],
            })
            if ok and sw_name not in installed_nodes:
                installed_nodes.append(sw_name)
            return ok

        tasks = []
        # 3. 逐跳下发正向流表
        for i in range(len(fwd_path)):
            current = fwd_path[i]
            next_hop = fwd_path[i+1] if i + 1 < len(fwd_path) else intent.target_node
            tasks.append(install_hop(current, next_hop, base_match))
            
        # 4. 逐跳下发反向流表
        for i in range(len(rev_path)):
            current = rev_path[i]
            next_hop = rev_path[i+1] if i + 1 < len(rev_path) else intent.source_node
            tasks.append(install_hop(current, next_hop, rev_match))

        results = await asyncio.gather(*tasks)
        if not all(results) or not tasks:
            # 失败回滚
            for n in installed_nodes:
                d = topo_manager.get_switch_dpid(n)
                if d: await ryu_client.delete_flow_by_cookie(d, cookie)
            return {"success": False, "error": "部分接力流表下发失败，重定向已回滚"}

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id,
            policy_type=PolicyType.REDIRECT,
            src_host=intent.source_node,
            dst_host=intent.target_node,
            intent_action=intent.action,
            parameters=intent.parameters,
            description=f"双向重定向 {intent.source_node}↔{intent.target_node} 经由 {via_sw}",
            ryu_cookies=[cookie],
            created_at=time.time(),
        )
        save_policies(_active_policies, _meter_counter)

        return {
            "success": True,
            "type": "redirect_traffic",
            "via_switch": via_sw,
            "installed_on": installed_nodes,
            "message": (
                f"已成功下发双向重定向策略，流量强制绕路 {via_sw}。\n"
                f"正向路径: {intent.source_node} -> {' -> '.join(fwd_path)} -> {intent.target_node}"
            ),
        }


    async def _clear_flows(self, intent: ParsedIntent, intent_id: str) -> Dict:
        """清除指定交换机上 IBN 系统下发的所有自定义规则"""
        sw = intent.target_switch
        if not sw:
            return {"success": False, "error": "请指定要清除的交换机（如 s1）"}

        dpid = topo_manager.get_switch_dpid(sw)
        if not dpid:
            return {"success": False, "error": f"找不到交换机: {sw}"}

        removed_count = 0
        for pol_id, pol in list(_active_policies.items()):
            for cookie in pol.ryu_cookies:
                ok = await ryu_client.delete_flow_by_cookie(dpid, cookie)
                if ok:
                    removed_count += 1
            for mid in pol.meter_ids:
                await ryu_client.delete_meter(dpid, mid)
            del _active_policies[pol_id]

        save_policies(_active_policies, _meter_counter)

        return {
            "success": True,
            "type": "clear_flows",
            "switch": sw,
            "dpid": dpid,
            "removed_count": removed_count,
            "message": f"已清除 {sw}(dpid={dpid}) 上 {removed_count} 条 IBN 自定义规则",
        }

    # ── 策略注册表对外接口 ────────────────────────────────

    def get_active_policies(self) -> List[Dict]:
        return [p.to_dict() for p in _active_policies.values()]

    async def delete_policy(self, policy_id: str) -> Tuple[bool, str]:
        pol = _active_policies.get(policy_id)
        if not pol:
            return False, "策略不存在"

        dpids = topo_manager.get_all_switch_dpids()
        for dpid in dpids:
            for cookie in pol.ryu_cookies:
                await ryu_client.delete_flow_by_cookie(dpid, cookie)
            for mid in pol.meter_ids:
                await ryu_client.delete_meter(dpid, mid)

        desc = pol.description
        del _active_policies[policy_id]
        save_policies(_active_policies, _meter_counter)
        return True, f"已撤销策略: {desc}"

    async def sync_with_data_plane(self):
        """核心对齐/调和逻辑：通过拉取底层真实流表，重建丢失的策略规则"""
        logger.info("[Reconciler] 开始执行与底层数据平面的状态对齐...")
        dpids = topo_manager.get_all_switch_dpids()
        if not dpids:
            logger.warning("[Reconciler] 拓扑暂无交换机，跳过调和")
            return
            
        # 1. 收集所有交换机上当前存活的 cookies
        alive_cookies = set()
        for dpid in dpids:
            flows = await ryu_client.get_flows(dpid)
            for f in flows:
                cookie = f.get("cookie", 0)
                if cookie != 0:
                    alive_cookies.add(cookie)
                    
        # 2. 对比期望状态并触发重建
        rebuilt_count = 0
        for pol_id, pol in list(_active_policies.items()):
            # 若策略关联的任意一个 cookie 丢失，意味着底层可能发生了重置
            # 为了安全起见，只要丢了任何一个 cookie 就重新应用整个意图
            is_missing = False
            for c in pol.ryu_cookies:
                if c not in alive_cookies:
                    is_missing = True
                    break
                    
            if is_missing and pol.intent_action:
                logger.warning(f"[Reconciler] 策略 {pol_id} ({pol.description}) 在底层发生缺失，准备自动重建...")
                intent = ParsedIntent(
                    action=pol.intent_action,
                    src_host=pol.src_host,
                    dst_host=pol.dst_host,
                    target_switch=pol.target_switch,
                    parameters=pol.parameters,
                    explanation="[Reconciler 自动重建]"
                )
                # 重新执行以恢复底层流表
                res = await self.execute(intent, pol_id)
                if res.get("success"):
                    rebuilt_count += 1
                else:
                    logger.error(f"[Reconciler] 重建策略 {pol_id} 失败: {res.get('error')}")
                    
        logger.info(f"[Reconciler] 对齐完成。共检测并自动重建了 {rebuilt_count} 条策略。")


# 单例
policy_executor = PolicyExecutor()
