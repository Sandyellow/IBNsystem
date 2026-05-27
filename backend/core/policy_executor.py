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
        meter_id = _next_meter_id()
        cookie = _make_cookie(intent_id)

        # 在 src_host 连接的交换机上安装 Meter
        src_sw = src_info.get("connected_switch", "s1")
        dpid = topo_manager.get_switch_dpid(src_sw) or 1

        # Step 1: 创建 Meter（超速部分由 OVS Meter 丢弃，正常速率内的包继续转发）
        meter_ok = await ryu_client.add_meter({
            "dpid": dpid,
            "meter_id": meter_id,
            "flags": ["KBPS"],
            "bands": [{"type": "DROP", "rate": rate_kbps, "burst_size": max(10, rate_kbps // 10)}],
        })
        if not meter_ok:
            return {"success": False, "error": f"创建 Meter 失败 (dpid={dpid}, meter_id={meter_id})"}

        # Step 2: 安装限速流表
        # ⚠️  Ryu /stats/flowentry/add 不支持 instructions 字段！
        # 必须使用 actions 列表，在其中用 {"type": "METER"} 挂载 Meter，
        # Ryu 会自动将其转换为 OpenFlow 1.3 的 METER Instruction + APPLY_ACTIONS Instruction。
        flow_ok = await ryu_client.add_flow({
            "dpid": dpid,
            "cookie": cookie,
            "priority": 400,
            "match": {"eth_type": 0x0800, "eth_src": src_mac, "eth_dst": dst_mac},
            "actions": [
                {"type": "METER", "meter_id": meter_id},   # 超速丢包，正常流量继续
                {"type": "OUTPUT", "port": "NORMAL"},       # 正常转发（依赖 OVS L2 学习）
            ],
        })

        # 添加反向流表（不挂载 Meter），防止未知单播泛洪，保证双向通信正常
        await ryu_client.add_flow({
            "dpid": dpid,
            "cookie": cookie,
            "priority": 400,
            "match": {"eth_type": 0x0800, "eth_src": dst_mac, "eth_dst": src_mac},
            "actions": [
                {"type": "OUTPUT", "port": "NORMAL"},
            ],
        })

        if not flow_ok:
            await ryu_client.delete_meter(dpid, meter_id)
            return {"success": False, "error": "创建限速流表失败，已回滚 Meter"}

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id,
            policy_type=PolicyType.RATE_LIMIT,
            src_host=intent.source_node,
            dst_host=intent.target_node,
            intent_action=intent.action,
            parameters=intent.parameters,
            description=f"限速 {intent.source_node}→{intent.target_node} ≤{bw_mbps}Mbps",
            ryu_cookies=[cookie],
            meter_ids=[meter_id],
            created_at=time.time(),
        )
        save_policies(_active_policies, _meter_counter)

        return {
            "success": True,
            "type": "rate_limit",
            "switch": src_sw,
            "dpid": dpid,
            "meter_id": meter_id,
            "rate_kbps": rate_kbps,
            "bw_mbps": bw_mbps,
            "src_mac": src_mac,
            "dst_mac": dst_mac,
            "message": (
                f"已在 {src_sw}(dpid={dpid}) 创建 Meter #{meter_id}（{bw_mbps}Mbps，"
                f"{rate_kbps}kbps KBPS 限速），正向流表 cookie={hex(cookie)}。"
                f"超速包由 OVS Meter 丢弃，速率内的包正常转发"
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
        dpids = topo_manager.get_all_switch_dpids()

        installed = []
        for dpid in dpids:
            ok1 = await ryu_client.add_flow({
                "dpid": dpid,
                "cookie": cookie,
                "priority": priority,
                "match": {"eth_type": 0x0800, "eth_src": src_mac, "eth_dst": dst_mac},
                "actions": [{"type": "OUTPUT", "port": "NORMAL"}],
            })
            # 双向下发：保证 OVS NORMAL 机制能学习到反向 MAC，避免未知单播全网泛洪
            ok2 = await ryu_client.add_flow({
                "dpid": dpid,
                "cookie": cookie,
                "priority": priority,
                "match": {"eth_type": 0x0800, "eth_src": dst_mac, "eth_dst": src_mac},
                "actions": [{"type": "OUTPUT", "port": "NORMAL"}],
            })
            if ok1 and ok2:
                installed.append(f"s{dpid}")

        if not installed:
            return {"success": False, "error": "所有交换机下发失败"}

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

        # 强制将端口号转为 int，防止 Ryu API 接收到字符串端口引发 500 校验错误
        port_val = out_port
        try:
            port_val = int(out_port)
        except ValueError:
            pass

        ok = await ryu_client.add_flow({
            "dpid": dpid,
            "cookie": cookie,
            "priority": 450,
            "match": {"eth_type": 0x0800, "eth_src": src_mac, "eth_dst": dst_mac},
            "actions": [{"type": "OUTPUT", "port": port_val}],
        })

        if not ok:
            return {"success": False, "error": "重定向流表下发失败"}

        _active_policies[intent_id] = ActivePolicy(
            id=intent_id,
            policy_type=PolicyType.REDIRECT,
            src_host=intent.source_node,
            dst_host=intent.target_node,
            intent_action=intent.action,
            parameters=intent.parameters,
            description=f"重定向 {intent.source_node}→{intent.target_node} 经由 {via_sw or '默认路径'}",
            ryu_cookies=[cookie],
            created_at=time.time(),
        )
        save_policies(_active_policies, _meter_counter)

        return {
            "success": True,
            "type": "redirect_traffic",
            "switch": src_sw_name,
            "via_switch": via_sw,
            "out_port": out_port,
            "message": (
                f"已在 {src_sw_name}(dpid={dpid}) 安装重定向规则，"
                f"{intent.source_node}→{intent.target_node} 的流量经由端口 {out_port}"
                f"{' (→' + via_sw + ')' if via_sw else ''}"
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
