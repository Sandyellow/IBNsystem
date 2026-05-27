"""
LangChain 工具库
封装系统现有的功能供 LLM Agent 调用。
不改变底层核心逻辑，仅提供标准的 @tool 接口与明确的类型标注。
"""
import json
from langchain_core.tools import tool

from core.topo_manager import topo_manager
from core.policy_executor import policy_executor


@tool
def get_node_location(node_id: str) -> str:
    """
    查询指定节点（主机或交换机）的网络位置信息。
    当你需要了解某个节点是否存在、其IP地址、MAC地址以及它连接在哪台交换机上时，必须调用此工具。
    参数 node_id: 节点的唯一标识符，例如 'h1'（主机）或 's2'（交换机）。
    """
    if not node_id:
        return "查询失败：未提供 node_id"

    # 查询是否为主机
    host_info = topo_manager.get_host(node_id)
    if host_info:
        ip = host_info.get("ip", "未知")
        mac = host_info.get("mac", "未知")
        connected_sw = host_info.get("connected_switch", "未知")
        port = host_info.get("port", "未知")
        return (f"主机节点 {node_id} 存在: "
                f"IP={ip}, MAC={mac}, 连接在交换机 {connected_sw} 的端口 {port} 上。")
    
    # 查询是否为交换机
    dpid = topo_manager.get_switch_dpid(node_id)
    if dpid is not None:
        return f"交换机节点 {node_id} 存在: DPID={dpid}。"
        
    return f"节点 {node_id} 不存在于当前网络拓扑中。"


@tool
def get_active_policies() -> str:
    """
    查询当前网络中所有由 IBN 系统下发的活跃策略（Active Policies）。
    当用户打算下发新策略，你需要判断新策略是否与现有策略产生逻辑冲突（例如重复下发、限速冲突、隔离冲突）时，必须调用此工具。
    返回的是一个 JSON 格式的策略列表。
    """
    policies = policy_executor.get_active_policies()
    if not policies:
        return "当前网络没有任何活跃的自定义策略。"
    
    # 将字典列表转为美化的 JSON 字符串供 LLM 理解
    return json.dumps(policies, ensure_ascii=False, indent=2)

