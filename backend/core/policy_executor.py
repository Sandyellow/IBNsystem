"""
策略执行器 — 将解析好的 ParsedIntent 直接映射到 Ryu REST API 调用
核心设计：无中间抽象层，意图→Ryu API 一步到位，返回真实执行结果
"""
from __future__ import annotations
import asyncio
import hashlib
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import settings
from core.ryu_client import ryu_client
from core.topo_manager import topo_manager
from models.intent import ParsedIntent, IntentAction
from models.policy import ActivePolicy, PolicyType

logger = logging.getLogger(__name__)

# 内存策略注册表（key = intent_id）
_active_policies: Dict[str, ActivePolicy] = {}

# Meter ID 计数器（从 200 开始，避免与 Ryu 自身 Meter 冲突）
_meter_counter = 200


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
                IntentAction.PING_TEST:        self._ping_test,
                IntentAction.CLEAR_FLOWS:      self._clear_flows,
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
        src_info = topo_manager.get_host(intent.src_host)
        dst_info = topo_manager.get_host(intent.dst_host)
        if not src_info or not dst_info:
            return {"success": False, "error": f"主机不存在: {intent.src_host} 或 {intent.dst_host}"}

        src_mac = src_info["mac"]
        dst_mac = dst_info["mac"]
        cookie = _make_cookie(intent_id)
        dpids = topo_manager.get_all_switch_dpids()

        installed, errors = [], []
        for dpid in dpids:
            # 双向 DROP 规则（高优先级 500，覆盖 L2 学习交换机的 priority=1 规则）
            ok1 = await ryu_client.add_flow({
                "dpid": dpid,
                "cookie": cookie,
                "priority": 500,
                "match": {"eth_src": src_mac, "eth_dst": dst_mac},
                "actions": [],
            })
            ok2 = await ryu_client.add_flow({
                "dpid": dpid,
                "cookie": cookie,
                "priority": 500,
                "match": {"eth_src": dst_mac, "eth_dst": src_mac},
                "actions": [],
            })
            sw_name = f"s{dpid}"
            if ok1 and ok2:
                installed.append(sw_name)
            else:
                errors.append(sw_name)

        if not installed:
            return {"success": False, "error": f"所有交换机下发失败: {errors}"}

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id,
            policy_type=PolicyType.BLOCK,
            src_host=intent.src_host,
            dst_host=intent.dst_host,
            description=f"隔离 {intent.src_host} ↔ {intent.dst_host}",
            ryu_cookies=[cookie],
            created_at=time.time(),
        )

        return {
            "success": True,
            "type": "block_traffic",
            "installed_on": installed,
            "src_mac": src_mac,
            "dst_mac": dst_mac,
            "cookie": cookie,
            "message": (
                f"已在 {', '.join(installed)} 上安装双向隔离规则（优先级500），"
                f"阻断 {intent.src_host}({src_mac}) ↔ {intent.dst_host}({dst_mac}) 的全部通信"
            ),
        }

    async def _allow_traffic(self, intent: ParsedIntent, intent_id: str) -> Dict:
        src_info = topo_manager.get_host(intent.src_host)
        dst_info = topo_manager.get_host(intent.dst_host)
        if not src_info or not dst_info:
            return {"success": False, "error": f"主机不存在: {intent.src_host} 或 {intent.dst_host}"}

        # 找到所有匹配的 block 策略
        target_pair = {intent.src_host, intent.dst_host}
        removed_cookies: List[int] = []
        removed_desc: List[str] = []

        for pol_id, pol in list(_active_policies.items()):
            if pol.policy_type == PolicyType.BLOCK and {pol.src_host, pol.dst_host} == target_pair:
                removed_cookies.extend(pol.ryu_cookies)
                removed_desc.append(pol.description)
                del _active_policies[pol_id]

        if not removed_cookies:
            return {
                "success": True,
                "type": "allow_traffic",
                "message": f"未找到 {intent.src_host}↔{intent.dst_host} 的隔离策略，无需操作",
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
                f"已恢复 {intent.src_host}↔{intent.dst_host} 的通信，"
                f"删除了 {len(removed_cookies)} 组隔离规则"
            ),
        }

    async def _rate_limit(self, intent: ParsedIntent, intent_id: str) -> Dict:
        src_info = topo_manager.get_host(intent.src_host)
        dst_info = topo_manager.get_host(intent.dst_host)
        if not src_info or not dst_info:
            return {"success": False, "error": f"主机不存在: {intent.src_host} 或 {intent.dst_host}"}

        bw_mbps = float(intent.parameters.get("bandwidth_mbps", 10))
        rate_kbps = int(bw_mbps * 1000)
        meter_id = _next_meter_id()
        cookie = _make_cookie(intent_id)

        src_mac = src_info["mac"]
        dst_mac = dst_info["mac"]

        # 在 src_host 连接的交换机上安装 Meter
        src_sw = src_info.get("connected_switch", "s1")
        dpid = topo_manager.get_switch_dpid(src_sw) or 1

        # Step 1: 创建 Meter
        meter_ok = await ryu_client.add_meter({
            "dpid": dpid,
            "meter_id": meter_id,
            "flags": ["KBPS"],
            "bands": [{"type": "DROP", "rate": rate_kbps, "burst_size": max(10, rate_kbps // 10)}],
        })
        if not meter_ok:
            return {"success": False, "error": f"创建 Meter 失败 (dpid={dpid}, meter_id={meter_id})"}

        # Step 2: 安装关联流表（应用 Meter + 正常转发）
        # 在 OpenFlow 1.3 中 METER 是 Instruction，使用 instructions 字段
        flow_ok = await ryu_client.add_flow({
            "dpid": dpid,
            "cookie": cookie,
            "priority": 400,
            "match": {"eth_type": 0x0800, "eth_src": src_mac, "eth_dst": dst_mac},
            "instructions": [
                {"type": "METER", "meter_id": meter_id},
                {"type": "APPLY_ACTIONS", "actions": [{"type": "OUTPUT", "port": "NORMAL"}]},
            ],
        })
        if not flow_ok:
            await ryu_client.delete_meter(dpid, meter_id)
            return {"success": False, "error": "创建限速流表失败，已回滚 Meter"}

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id,
            policy_type=PolicyType.RATE_LIMIT,
            src_host=intent.src_host,
            dst_host=intent.dst_host,
            description=f"限速 {intent.src_host}→{intent.dst_host} ≤{bw_mbps}Mbps",
            ryu_cookies=[cookie],
            meter_ids=[meter_id],
            created_at=time.time(),
        )

        return {
            "success": True,
            "type": "rate_limit",
            "switch": src_sw,
            "dpid": dpid,
            "meter_id": meter_id,
            "rate_kbps": rate_kbps,
            "src_mac": src_mac,
            "dst_mac": dst_mac,
            "message": (
                f"已在 {src_sw}(dpid={dpid}) 创建 Meter #{meter_id}（{bw_mbps}Mbps KBPS 限速），"
                f"关联流表 cookie={hex(cookie)}"
            ),
        }

    async def _set_priority(self, intent: ParsedIntent, intent_id: str) -> Dict:
        src_info = topo_manager.get_host(intent.src_host)
        dst_info = topo_manager.get_host(intent.dst_host)
        if not src_info or not dst_info:
            return {"success": False, "error": f"主机不存在: {intent.src_host} 或 {intent.dst_host}"}

        priority = int(intent.parameters.get("priority", 200))
        src_mac = src_info["mac"]
        dst_mac = dst_info["mac"]
        cookie = _make_cookie(intent_id)
        dpids = topo_manager.get_all_switch_dpids()

        installed = []
        for dpid in dpids:
            ok = await ryu_client.add_flow({
                "dpid": dpid,
                "cookie": cookie,
                "priority": priority,
                "match": {"eth_type": 0x0800, "eth_src": src_mac, "eth_dst": dst_mac},
                "actions": [{"type": "OUTPUT", "port": "NORMAL"}],
            })
            if ok:
                installed.append(f"s{dpid}")

        if not installed:
            return {"success": False, "error": "所有交换机下发失败"}

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id,
            policy_type=PolicyType.PRIORITY,
            src_host=intent.src_host,
            dst_host=intent.dst_host,
            description=f"优先级 {priority}: {intent.src_host}→{intent.dst_host}",
            ryu_cookies=[cookie],
            created_at=time.time(),
        )

        return {
            "success": True,
            "type": "set_priority",
            "priority": priority,
            "installed_on": installed,
            "message": f"已为 {intent.src_host}→{intent.dst_host} 在 {', '.join(installed)} 上设置优先级 {priority} 的转发规则",
        }

    async def _redirect_traffic(self, intent: ParsedIntent, intent_id: str) -> Dict:
        src_info = topo_manager.get_host(intent.src_host)
        dst_info = topo_manager.get_host(intent.dst_host)
        if not src_info or not dst_info:
            return {"success": False, "error": f"主机不存在: {intent.src_host} 或 {intent.dst_host}"}

        via_sw = intent.parameters.get("via_switch")
        src_mac = src_info["mac"]
        dst_mac = dst_info["mac"]
        cookie = _make_cookie(intent_id)

        # 在 src_host 连接的交换机上安装重定向规则
        src_sw_name = src_info.get("connected_switch", "s1")
        dpid = topo_manager.get_switch_dpid(src_sw_name) or 1

        # 从拓扑中查找到 via_switch 的出端口
        out_port = "NORMAL"
        if via_sw:
            for link in topo_manager.topology.get("links", []):
                if link["source"] == src_sw_name and link["target"] == via_sw and link.get("src_port"):
                    out_port = link["src_port"]
                    break
                elif link["target"] == src_sw_name and link["source"] == via_sw and link.get("dst_port"):
                    out_port = link["dst_port"]
                    break

        ok = await ryu_client.add_flow({
            "dpid": dpid,
            "cookie": cookie,
            "priority": 450,
            "match": {"eth_type": 0x0800, "eth_src": src_mac, "eth_dst": dst_mac},
            "actions": [{"type": "OUTPUT", "port": out_port}],
        })

        if not ok:
            return {"success": False, "error": "重定向流表下发失败"}

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id,
            policy_type=PolicyType.REDIRECT,
            src_host=intent.src_host,
            dst_host=intent.dst_host,
            description=f"重定向 {intent.src_host}→{intent.dst_host} 经由 {via_sw or '默认路径'}",
            ryu_cookies=[cookie],
            created_at=time.time(),
        )

        return {
            "success": True,
            "type": "redirect_traffic",
            "switch": src_sw_name,
            "via_switch": via_sw,
            "out_port": out_port,
            "message": (
                f"已在 {src_sw_name}(dpid={dpid}) 安装重定向规则，"
                f"{intent.src_host}→{intent.dst_host} 的流量经由端口 {out_port}"
                f"{' (→' + via_sw + ')' if via_sw else ''}"
            ),
        }

    async def _ping_test(self, intent: ParsedIntent, _: str) -> Dict:
        """通过 VM Agent 的 /mininet/ping 执行真实 ping 测试"""
        src = intent.src_host
        dst = intent.dst_host
        dst_info = topo_manager.get_host(dst)
        dst_ip = dst_info["ip"] if dst_info else dst

        try:
            async with httpx.AsyncClient(
                base_url=settings.VM_AGENT_URL,
                timeout=httpx.Timeout(40.0, connect=5.0),
            ) as client:
                resp = await client.post("/mininet/ping", json={
                    "src": src,
                    "dst": dst,
                    "dst_ip": dst_ip,
                    "count": 4,
                })
                resp.raise_for_status()
                data = resp.json()
                return {
                    "success": data.get("success", False),
                    "type": "ping_test",
                    "output": data.get("output", ""),
                    "packet_loss": data.get("packet_loss"),
                    "avg_rtt_ms": data.get("avg_rtt_ms"),
                    "message": data.get("summary", f"{src} → {dst}({dst_ip}) ping 测试完成"),
                }
        except Exception as e:
            return {"success": False, "type": "ping_test", "error": f"ping 测试失败: {e}"}

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
        return True, f"已撤销策略: {desc}"


# 单例
policy_executor = PolicyExecutor()
