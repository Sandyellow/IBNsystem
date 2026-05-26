"""
LLM 意图解析引擎 — 重构版
改进 System Prompt，注入真实网络上下文，对应实际 Ryu 能力的 action 集合
"""
from __future__ import annotations
import json
import logging
import re
from typing import Optional, Tuple

from openai import AsyncOpenAI

from config import settings
from models.intent import ParsedIntent, IntentAction

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个 SDN 网络控制助手，将用户的自然语言网络管理指令解析为结构化 JSON。

支持的操作（action 必须精确匹配）:
- query_topology   : 查询网络拓扑结构（节点、链路）
- query_flows      : 查询交换机流表规则（target_switch 指定交换机，如 "s1"）
- query_port_stats : 查询交换机端口流量统计
- block_traffic    : 隔离两台主机，双向禁止通信（需要 src_host 和 dst_host）
- allow_traffic    : 恢复两台主机的通信（取消之前的隔离，需要 src_host 和 dst_host）
- rate_limit       : 限制两台主机间的带宽（需要 src_host、dst_host、parameters.bandwidth_mbps）
- set_priority     : 为某对主机的流量设置转发优先级（需要 src_host、dst_host、parameters.priority 范围 1-65535）
- redirect_traffic : 将流量重定向经过指定中间交换机（需要 src_host、dst_host、parameters.via_switch）
- ping_test        : 测试两台主机间的网络连通性（需要 src_host 和 dst_host）
- clear_flows      : 清除某交换机上 IBN 系统下发的所有自定义规则（需要 target_switch）

输出要求（只输出 JSON，不要 markdown 代码块，不要任何额外文字）:
{
  "action": "<上面列出的 action 之一>",
  "src_host": "<主机名如 h1 或 h2，无则为 null>",
  "dst_host": "<主机名如 h3 或 h4，无则为 null>",
  "target_switch": "<交换机名如 s1，无则为 null>",
  "parameters": {
    "bandwidth_mbps": <数字，仅 rate_limit 使用>,
    "priority": <1-65535 整数，仅 set_priority 使用>,
    "via_switch": "<交换机名，仅 redirect_traffic 使用>"
  },
  "explanation": "<一句话中文解释你理解的用户意图>"
}"""

FEW_SHOTS = [
    {"role": "user", "content": "隔离 h1 和 h3，让它们不能互相通信"},
    {"role": "assistant", "content": '{"action":"block_traffic","src_host":"h1","dst_host":"h3","target_switch":null,"parameters":{},"explanation":"在网络所有交换机上安装高优先级 DROP 规则，双向阻断 h1 与 h3 之间的通信"}'},
    {"role": "user", "content": "把 h2 到 h4 的流量限制在 5Mbps"},
    {"role": "assistant", "content": '{"action":"rate_limit","src_host":"h2","dst_host":"h4","target_switch":null,"parameters":{"bandwidth_mbps":5},"explanation":"在 h2 所连接的交换机上创建 5Mbps 限速 Meter，并关联对应流表规则"}'},
    {"role": "user", "content": "测试 h1 和 h2 之间的连通性"},
    {"role": "assistant", "content": '{"action":"ping_test","src_host":"h1","dst_host":"h2","target_switch":null,"parameters":{},"explanation":"在 h1 上执行 ping h2 的连通性测试"}'},
    {"role": "user", "content": "查看 s2 交换机的流表"},
    {"role": "assistant", "content": '{"action":"query_flows","src_host":null,"dst_host":null,"target_switch":"s2","parameters":{},"explanation":"从 Ryu 获取 s2 交换机当前所有流表条目"}'},
    {"role": "user", "content": "恢复 h1 和 h3 之间的通信"},
    {"role": "assistant", "content": '{"action":"allow_traffic","src_host":"h1","dst_host":"h3","target_switch":null,"parameters":{},"explanation":"删除之前下发的隔离规则，恢复 h1 与 h3 的正常双向通信"}'},
    {"role": "user", "content": "显示当前网络拓扑"},
    {"role": "assistant", "content": '{"action":"query_topology","src_host":null,"dst_host":null,"target_switch":null,"parameters":{},"explanation":"获取并展示当前网络中的交换机、主机和链路信息"}'},
    {"role": "user", "content": "给 h1 到 h2 的流量设置高优先级 300"},
    {"role": "assistant", "content": '{"action":"set_priority","src_host":"h1","dst_host":"h2","target_switch":null,"parameters":{"priority":300},"explanation":"在所有交换机上安装优先级 300 的转发规则，使 h1→h2 流量优先处理"}'},
    {"role": "user", "content": "查看所有交换机的端口流量统计"},
    {"role": "assistant", "content": '{"action":"query_port_stats","src_host":null,"dst_host":null,"target_switch":null,"parameters":{},"explanation":"获取所有交换机各端口的收发字节数、包数等统计信息"}'},
    {"role": "user", "content": "清除 s1 上的自定义规则"},
    {"role": "assistant", "content": '{"action":"clear_flows","src_host":null,"dst_host":null,"target_switch":"s1","parameters":{},"explanation":"删除 IBN 系统在 s1 上下发的所有自定义流表规则"}'},
]

VALID_ACTIONS = {a.value for a in IntentAction}


class IntentEngine:
    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
            )
        return self._client

    async def parse(
        self,
        user_text: str,
        topo_context: str = "",
        retry_hint: str = "",
        attempt: int = 0,
    ) -> Tuple[Optional[ParsedIntent], str]:
        client = self._get_client()

        system_content = SYSTEM_PROMPT
        if topo_context:
            system_content += f"\n\n{topo_context}"

        messages = [{"role": "system", "content": system_content}, *FEW_SHOTS]

        if retry_hint and attempt > 0:
            user_msg = f"[第{attempt+1}次重试，上次失败原因: {retry_hint}]\n用户指令: {user_text}"
        else:
            user_msg = user_text
        messages.append({"role": "user", "content": user_msg})

        try:
            resp = await client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=messages,
                temperature=0.1,
                max_tokens=512,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
            data = json.loads(raw)

            action = data.get("action", "")
            if action not in VALID_ACTIONS:
                return None, f"未知 action: {action!r}，支持: {', '.join(VALID_ACTIONS)}"

            intent = ParsedIntent(**data)
            return intent, ""

        except json.JSONDecodeError as e:
            return None, f"JSON 解析失败: {e}"
        except Exception as e:
            return None, f"LLM 调用异常: {type(e).__name__}: {e}"

    async def parse_with_retry(
        self,
        user_text: str,
        topo_context: str = "",
    ) -> Tuple[Optional[ParsedIntent], str, int]:
        last_error = ""
        for attempt in range(settings.MAX_LLM_RETRY):
            intent, error = await self.parse(user_text, topo_context, last_error, attempt)
            if intent is not None:
                return intent, "", attempt
            last_error = error
        return None, last_error, settings.MAX_LLM_RETRY


intent_engine = IntentEngine()
