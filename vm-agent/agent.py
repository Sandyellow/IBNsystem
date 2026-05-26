"""
VM Agent — 运行在 Ubuntu VM 上的 Flask 服务
对接 Mininet 和 Ryu，向 Windows 主机暴露统一 REST API
"""
from flask import Flask, jsonify, request
import subprocess
import requests
import time
import json
import os

app = Flask(__name__)

RYU_BASE = "http://127.0.0.1:8080"   # Ryu REST API 本地地址
TOPO_CONFIG = os.path.join(os.path.dirname(__file__), "topology_config.json")


def load_host_config():
    """从 topology_config.json 读取主机信息，文件不存在时返回空列表"""
    try:
        with open(TOPO_CONFIG, "r") as f:
            return json.load(f).get("hosts", [])
    except Exception:
        return []


def safe_json(resp):
    """安全解析 HTTP 响应 JSON，空响应返回 None"""
    try:
        text = resp.text.strip()
        if not text:
            return None
        return resp.json()
    except Exception:
        return None

# ─────────────────────────────────────────────────────
#  健康检查
# ─────────────────────────────────────────────────────
@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "timestamp": time.time()})


# ─────────────────────────────────────────────────────
#  主机静态配置 — 返回 topology_config.json 中的主机信息
#  供 Windows 后端获取 MAC/IP 做流表匹配
# ─────────────────────────────────────────────────────
@app.route("/hosts")
def get_hosts():
    hosts = load_host_config()
    return jsonify({"hosts": hosts, "count": len(hosts)})

# ─────────────────────────────────────────────────────
#  诊断端点 — 查看 Ryu 原始返回（调试用）
#  在 Ubuntu VM 上访问: http://127.0.0.1:5000/debug/ryu
# ─────────────────────────────────────────────────────
@app.route("/debug/ryu")
def debug_ryu():
    result = {}
    for path in [
        "/v1.0/topology/switches",
        "/v1.0/topology/links",
        "/v1.0/topology/hosts",
        "/stats/switches",
    ]:
        try:
            r = requests.get(f"{RYU_BASE}{path}", timeout=5)
            data = safe_json(r)
            result[path] = {
                "http_status": r.status_code,
                "body_length": len(r.text),
                "data": data,
                "raw_preview": r.text[:200] if data is None else None,
            }
        except Exception as e:
            result[path] = {"error": str(e)}
    return jsonify(result)

# ─────────────────────────────────────────────────────
#  拓扑 — 唯一策略: Ryu LLDP topology API
#  要求 Ryu 启动时加载 ryu.topology.switches --observe-links
# ─────────────────────────────────────────────────────
@app.route("/topology")
def get_topology():
    """
    从 Ryu 的 topology REST API 获取真实拓扑，不做任何猜测或硬编码推断。
    支持任意拓扑结构，不限于当前三交换机测试网络。
    """
    try:
        # ── Step 1: 检查 topology API 可达性 ─────────────────
        sw_resp = requests.get(f"{RYU_BASE}/v1.0/topology/switches", timeout=5)
        if not sw_resp.ok or sw_resp.status_code == 404:
            return jsonify({
                "nodes": [], "links": [],
                "error": "Ryu topology API 不可用，请确认 ryu.topology.switches 已加载 (--observe-links)",
                "source": "error"
            }), 200

        switches = safe_json(sw_resp) or []
        if not switches:
            return jsonify({
                "nodes": [], "links": [],
                "error": "Ryu 返回了空的交换机列表，网络可能尚未就绪",
                "source": "pending"
            }), 200

        # ── Step 2: 轮询等待 LLDP 发现链路（最多 10 次，间隔 1s）─
        # LLDP 发现交换机间链路需要时间，避免返回无链路的拓扑
        links_raw = []
        for attempt in range(10):
            lk_resp = requests.get(f"{RYU_BASE}/v1.0/topology/links", timeout=5)
            links_raw = safe_json(lk_resp) or []
            # 交换机数 >= 2 时，若已发现至少 (sw数-1)*2 条有向链路则认为已稳定
            expected = max(1, (len(switches) - 1) * 2)
            if len(links_raw) >= expected:
                break
            if attempt < 9:
                time.sleep(1)

        # ── Step 3: 获取已学习到的主机 ──────────────────────
        ht_resp = requests.get(f"{RYU_BASE}/v1.0/topology/hosts", timeout=5)
        hosts_raw = safe_json(ht_resp) or []

        # ── Step 4: 构建节点列表（交换机）────────────────────
        nodes = []
        dpid_to_node = {}
        for sw in switches:
            dpid = sw.get("dpid", "")
            node_id = f"s{_dpid_int(dpid)}"
            dpid_to_node[dpid] = node_id
            # 提取端口信息，记录端口号到接口名映射（供链路 ID 生成用）
            ports = sw.get("ports", [])
            nodes.append({
                "id": node_id,
                "type": "switch",
                "label": node_id,
                "dpid": dpid,
                "port_count": len(ports),
            })

        # ── Step 5: 构建交换机间链路（来自 LLDP 真实发现）───
        link_list = []
        seen_links = set()
        for link in links_raw:
            src_dpid = link.get("src", {}).get("dpid", "")
            dst_dpid = link.get("dst", {}).get("dpid", "")
            src_port  = link.get("src", {}).get("port_no")
            dst_port  = link.get("dst", {}).get("port_no")
            src_id = dpid_to_node.get(src_dpid, f"s_{src_dpid}")
            dst_id = dpid_to_node.get(dst_dpid, f"s_{dst_dpid}")
            # 去重：LLDP 链路是双向的，只保留一条
            key = tuple(sorted([src_id, dst_id]))
            if key in seen_links:
                continue
            seen_links.add(key)
            link_list.append({
                "id": f"{src_id}-{dst_id}",
                "source": src_id,
                "target": dst_id,
                "state": "up",
                "src_port": src_port,
                "dst_port": dst_port,
            })

        # ── Step 6: 构建主机节点及主机-交换机链路 ────────────
        # 主机信息完全来自 Ryu 的 PacketIn 学习，不依赖任何配置文件
        mac_to_host_id = {}
        host_counter = 1
        for host in hosts_raw:
            mac  = host.get("mac", "")
            ipv4 = host.get("ipv4", [])
            port_info = host.get("port", {})
            sw_dpid   = port_info.get("dpid", "")
            port_no   = port_info.get("port_no")
            connected_sw = dpid_to_node.get(sw_dpid)

            # 用 MAC 地址作为唯一键，避免重复添加
            if mac in mac_to_host_id:
                continue
            host_id = f"h{host_counter}"
            host_counter += 1
            mac_to_host_id[mac] = host_id

            nodes.append({
                "id": host_id,
                "type": "host",
                "label": host_id,
                "mac": mac,
                "ip": ipv4[0] if ipv4 else None,
            })

            if connected_sw:
                link_list.append({
                    "id": f"{host_id}-{connected_sw}",
                    "source": host_id,
                    "target": connected_sw,
                    "state": "up",
                    "src_port": None,
                    "dst_port": port_no,
                })

        return jsonify({
            "nodes": nodes,
            "links": link_list,
            "timestamp": time.time(),
            "source": "topology_api",
            "switch_count": len(switches),
            "link_count": len(link_list),
        })

    except Exception as e:
        return jsonify({"nodes": [], "links": [], "error": str(e), "source": "error"}), 200







# ─────────────────────────────────────────────────────
#  统计信息 — 从 Ryu 获取端口统计
# ─────────────────────────────────────────────────────
@app.route("/stats")
def get_stats():
    try:
        resp = requests.get(f"{RYU_BASE}/stats/switches", timeout=5)
        if not resp.ok:
            return jsonify({"switches": []})
        dpids = resp.json()
        switches = []
        for dpid in dpids:
            port_resp = requests.get(f"{RYU_BASE}/stats/port/{dpid}", timeout=5)
            if port_resp.ok:
                ports_raw = port_resp.json().get(str(dpid), [])
                ports = [{
                    "port_no": p.get("port_no"),
                    "rx_packets": p.get("rx_packets", 0),
                    "tx_packets": p.get("tx_packets", 0),
                    "rx_bytes": p.get("rx_bytes", 0),
                    "tx_bytes": p.get("tx_bytes", 0),
                    "rx_errors": p.get("rx_errors", 0),
                    "tx_errors": p.get("tx_errors", 0),
                } for p in ports_raw]
                switches.append({"dpid": str(dpid), "ports": ports})
        return jsonify({"switches": switches, "timestamp": time.time()})
    except Exception as e:
        return jsonify({"switches": [], "error": str(e)})


# ─────────────────────────────────────────────────────
#  流表信息 — 从 Ryu 获取指定交换机的流表
# ─────────────────────────────────────────────────────
@app.route("/flows/<dpid>")
def get_flows(dpid):
    try:
        resp = requests.get(f"{RYU_BASE}/stats/flow/{dpid}", timeout=5)
        if not resp.ok:
            return jsonify({"flows": [], "error": f"Ryu HTTP {resp.status_code}"})
        data = resp.json()
        flows = data.get(str(dpid), [])
        return jsonify({"flows": flows, "timestamp": time.time()})
    except Exception as e:
        return jsonify({"flows": [], "error": str(e)})


# ── 端口采样缓存：{dpid_portno: (timestamp, bytes_total)} ──
_port_samples: dict = {}

# 链路带宽上限（bps），与 mininet_topology.py 中 bw=100 Mbps 对应
_LINK_BW_BPS = 100 * 1_000_000


@app.route("/link-stats")
def get_link_stats():
    """基于 OVS 端口字节差值计算真实利用率，延迟根据丢包率估算。
    两次调用之间取差值，首次调用返回 0 利用率（无前样本）但不返回随机值。
    """
    global _port_samples
    now = time.time()

    try:
        # ── 1. 拉取交换机列表 ─────────────────────────────
        sw_resp = requests.get(f"{RYU_BASE}/stats/switches", timeout=5)
        if not sw_resp.ok:
            return jsonify({"links": [], "error": "无法获取交换机列表", "timestamp": now})
        dpids = sw_resp.json() or []

        # ── 2. 对每台交换机采样端口字节数 ─────────────────
        new_samples: dict = {}
        # dpid → {port_no: {rx_bytes, tx_bytes, rx_errors, tx_packets}}
        port_data_map: dict = {}
        for dpid in dpids:
            pr = requests.get(f"{RYU_BASE}/stats/port/{dpid}", timeout=5)
            if not pr.ok:
                continue
            ports_raw = pr.json().get(str(dpid), [])
            port_data_map[dpid] = {}
            for p in ports_raw:
                pno = p.get("port_no", 0)
                if pno == 4294967294:   # LOCAL 端口，跳过
                    continue
                rb = p.get("rx_bytes", 0)
                tb = p.get("tx_bytes", 0)
                re_ = p.get("rx_errors", 0)
                txp = p.get("tx_packets", 0)
                rxp = p.get("rx_packets", 0)
                key = f"{dpid}:{pno}"
                new_samples[key] = (now, rb + tb)
                port_data_map[dpid][pno] = {
                    "rx_bytes": rb, "tx_bytes": tb,
                    "rx_errors": re_, "tx_packets": txp, "rx_packets": rxp,
                }

        # ── 3. 获取当前拓扑，拿到链路列表 ─────────────────
        topo_resp = get_topology()
        resp_obj = topo_resp[0] if isinstance(topo_resp, tuple) else topo_resp
        topo_data = resp_obj.get_json()
        links = topo_data.get("links", [])

        # ── 4. 构建 dpid_to_node 映射（node_id → dpid）───
        node_to_dpid: dict = {}
        for node in topo_data.get("nodes", []):
            if node.get("type") == "switch" and node.get("dpid"):
                node_to_dpid[node["id"]] = int(node["dpid"], 16) if isinstance(node["dpid"], str) else node["dpid"]

        # ── 5. 计算每条链路的利用率 ───────────────────────
        link_stats = []
        for link in links:
            if link.get("state") == "down":
                continue

            src_id = link.get("source", "")
            dst_id = link.get("target", "")
            lid = link.get("id", f"{src_id}-{dst_id}")

            # 获取 src 端口字节差值（选编号最小的非 LOCAL 端口）
            utilization_pct = 0.0
            latency_ms = 2.0          # 基准延迟（拓扑配置 1ms + 1ms 抖动）
            packet_loss_pct = 0.0

            src_dpid = node_to_dpid.get(src_id)
            if src_dpid and src_dpid in port_data_map:
                src_ports = port_data_map[src_dpid]
                if src_ports:
                    # 取第一个有效端口
                    ref_pno = min(src_ports.keys())
                    key = f"{src_dpid}:{ref_pno}"
                    prev = _port_samples.get(key)
                    if prev:
                        prev_ts, prev_bytes = prev
                        dt = now - prev_ts
                        if dt > 0.1:
                            delta_bytes = new_samples.get(key, (0, 0))[1] - prev_bytes
                            if delta_bytes >= 0:
                                bps = (delta_bytes * 8) / dt
                                utilization_pct = round(min(bps / _LINK_BW_BPS * 100, 100.0), 1)

                    # 延迟估算：根据错误率加权，无错误时保持基准
                    pd = src_ports[ref_pno]
                    total_pkt = pd["rx_packets"] + pd["tx_packets"]
                    if total_pkt > 0:
                        err_rate = pd["rx_errors"] / total_pkt
                        latency_ms = round(2.0 + err_rate * 50, 2)
                        packet_loss_pct = round(min(err_rate * 100, 100.0), 2)

            link_stats.append({
                "id": lid,
                "latency_ms": latency_ms,
                "packet_loss_pct": packet_loss_pct,
                "utilization_pct": utilization_pct,
            })

        # ── 6. 更新缓存 ───────────────────────────────────
        _port_samples = new_samples

        return jsonify({"links": link_stats, "timestamp": now})

    except Exception as e:
        return jsonify({"links": [], "error": str(e), "timestamp": now})


# ─────────────────────────────────────────────────────
#  策略执行 — 调用 Ryu REST API 下发流表
# ─────────────────────────────────────────────────────
@app.route("/policy/apply", methods=["POST"])
def apply_policy():
    policy = request.json
    try:
        policy_type = policy.get("policy_type", "flow_rule")
        if policy_type == "meter":
            return _apply_meter(policy)
        elif policy_type == "flow_rule":
            return _apply_flow(policy)
        else:
            return jsonify({"success": False, "error": f"不支持的策略类型: {policy_type}"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _dpid_int(dpid):
    """将 dpid 字符串或整数统一转为 int"""
    if isinstance(dpid, int):
        return dpid
    try:
        return int(dpid, 16)
    except (ValueError, TypeError):
        return int(dpid)


def _apply_flow(policy):
    dpid     = policy.get("dpid", "1")
    match    = policy.get("match", {})
    actions_raw = policy.get("actions", [])
    intent_id = policy.get("intent_id", "")

    cookie = 0
    if intent_id:
        import hashlib
        cookie = int(hashlib.md5(intent_id.encode()).hexdigest()[:15], 16)

    flow_entry = {
        "dpid": _dpid_int(dpid),
        "cookie": cookie,
        "priority": policy.get("priority", 100),
        "idle_timeout": policy.get("idle_timeout", 0),
        "hard_timeout": policy.get("hard_timeout", 0),
        "match": {},
        "actions": [],
    }

    for k, v in match.items():
        if v is not None:
            flow_entry["match"][k] = v
            
    if ("ipv4_src" in match or "ipv4_dst" in match) and "eth_type" not in flow_entry["match"]:
        flow_entry["match"]["eth_type"] = 0x0800
    elif ("ipv6_src" in match or "ipv6_dst" in match) and "eth_type" not in flow_entry["match"]:
        flow_entry["match"]["eth_type"] = 0x86DD

    for action in actions_raw:
        atype = action.get("type", "")
        if atype == "output":
            flow_entry["actions"].append({"type": "OUTPUT", "port": action.get("value", "NORMAL")})
        elif atype == "drop":
            flow_entry["instructions"] = [{"type": "CLEAR_ACTIONS"}]
            del flow_entry["actions"]
            break
        elif atype == "meter":
            flow_entry["actions"].append({"type": "METER", "meter_id": action.get("value")})
        elif atype == "delete":
            if cookie != 0:
                flow_entry["cookie_mask"] = 0xFFFFFFFFFFFFFFFF
            resp = requests.delete(f"{RYU_BASE}/stats/flowentry/delete", json=flow_entry, timeout=5)
            return jsonify({"success": resp.ok, "ryu_status": resp.status_code})

    resp = requests.post(f"{RYU_BASE}/stats/flowentry/add", json=flow_entry, timeout=5)
    return jsonify({"success": resp.ok, "ryu_status": resp.status_code, "ryu_response": resp.text})


def _apply_meter(policy):
    dpid     = policy.get("dpid", "1")
    meter_id = policy.get("meter_id", 1)
    rate_kbps = policy.get("rate_kbps", 1000)

    meter_entry = {
        "dpid": _dpid_int(dpid),
        "meter_id": meter_id,
    }

    actions_raw = policy.get("actions", [])
    is_delete = any(a.get("type") == "delete" for a in actions_raw)

    if is_delete:
        _apply_flow(policy)  # 删除关联流表
        resp = requests.post(f"{RYU_BASE}/stats/meterentry/delete", json=meter_entry, timeout=5)
    else:
        meter_entry["flags"] = ["KBPS"]
        meter_entry["bands"] = [{"type": "DROP", "rate": rate_kbps, "burst_size": 10}]
        resp = requests.post(f"{RYU_BASE}/stats/meterentry/add", json=meter_entry, timeout=5)
        if resp.ok:
            _apply_flow(policy)  # 添加关联流表
            
    return jsonify({"success": resp.ok, "ryu_status": resp.status_code})


@app.route("/policy/rollback", methods=["POST"])
def rollback_policy():
    policy = request.json
    for action in policy.get("actions", []):
        action["type"] = "delete"
    return apply_policy()


# ─────────────────────────────────────────────────────
#  Mininet 命令执行
# ─────────────────────────────────────────────────────
@app.route("/mininet/exec", methods=["POST"])
def exec_mininet_cmd():
    cmd = request.json.get("command", "")
    import re
    if re.search(r'[;&|`$><]', cmd):
        return jsonify({"success": False, "error": "包含非法字符，禁止执行"})
    
    import shlex
    try:
        cmd_parts = shlex.split(cmd)
        result = subprocess.run(
            cmd_parts, capture_output=True, text=True, timeout=30
        )
        return jsonify({"success": True, "output": result.stdout, "stderr": result.stderr})
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "命令执行超时"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ─────────────────────────────────────────────────────
#  Mininet 主机间 ping 测试
#  通过 ip netns exec 在对应主机网络命名空间内执行 ping
# ─────────────────────────────────────────────────────
@app.route("/mininet/ping", methods=["POST"])
def mininet_ping():
    data = request.json or {}
    src = data.get("src", "")
    dst_ip = data.get("dst_ip", "")
    count = int(data.get("count", 4))

    if not src or not dst_ip:
        return jsonify({"success": False, "error": "需要 src 和 dst_ip 参数"})

    # 利用 ip netns exec 在 Mininet 主机命名空间内执行 ping
    # Mininet 主机命名空间名与主机名相同（如 h1, h2）
    try:
        result = subprocess.run(
            ["ip", "netns", "exec", src, "ping", "-c", str(count), "-W", "2", dst_ip],
            capture_output=True, text=True, timeout=count * 3 + 5
        )
        output = result.stdout + result.stderr
        success = result.returncode == 0

        # 解析 ping 统计
        import re as _re
        packet_loss = None
        avg_rtt_ms = None
        loss_match = _re.search(r'(\d+)% packet loss', output)
        rtt_match = _re.search(r'rtt min/avg/max/mdev = [\d.]+/([\d.]+)/', output)
        if loss_match:
            packet_loss = int(loss_match.group(1))
        if rtt_match:
            avg_rtt_ms = float(rtt_match.group(1))

        summary = (
            f"{src} → {dst_ip}: "
            f"{'连通' if success else '不通'}"
            f"{', 丢包 ' + str(packet_loss) + '%' if packet_loss is not None else ''}"
            f"{', RTT avg=' + str(avg_rtt_ms) + 'ms' if avg_rtt_ms is not None else ''}"
        )
        return jsonify({
            "success": success,
            "output": output,
            "packet_loss": packet_loss,
            "avg_rtt_ms": avg_rtt_ms,
            "summary": summary,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "ping 超时", "output": ""})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "output": ""})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
