"""
意图解析引擎 — 使用 OpenAI 兼容格式 LLM 将自然语言转换为结构化意图
含重试机制：每次重试携带上次失败原因引导 LLM 修正
支持拓扑上下文注入和语义验证
"""
from __future__ import annotations
import json
import logging
import re
from typing import List, Optional, Tuple

from openai import AsyncOpenAI
from pydantic import ValidationError

from config import settings
from models.intent import ParsedIntent
from models.network import Topology

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个 SDN 网络意图解析助手，将用户自然语言转为严格 JSON。

支持的 action（必须精确匹配）:
add_flow | delete_flow | rate_limit | block_traffic | allow_traffic |
redirect_traffic | query_stats | ping | set_priority | load_balance | query_topology

输出格式（只输出 JSON，不要 markdown 代码块）:
{
  "action": "<action>",
  "source_node": "<h1/s1 等，可为 null>",
  "target_node": "<节点名，可为 null>",
  "parameters": {
    "bandwidth_mbps": <number, 仅 rate_limit>,
    "via_node": "<string, 仅 redirect_traffic>",
    "priority": <1-65535, 仅 set_priority>
  },
  "explanation": "<中文解释>"
}

规则: 只输出合法 JSON。"""

FEW_SHOT = [
    {"role": "user", "content": "把 h1 到 h3 的流量限制在 10Mbps"},
    {"role": "assistant", "content": '{"action":"rate_limit","source_node":"h1","target_node":"h3","parameters":{"bandwidth_mbps":10},"explanation":"限制 h1→h3 带宽为 10Mbps"}'},
    {"role": "user", "content": "封锁 h2 和 h4 之间的通信"},
    {"role": "assistant", "content": '{"action":"block_traffic","source_node":"h2","target_node":"h4","parameters":{},"explanation":"阻断 h2 与 h4 之间双向流量"}'},
    {"role": "user", "content": "帮我看看现在网络里有几个节点和链路"},
    {"role": "assistant", "content": '{"action":"query_topology","source_node":null,"target_node":null,"parameters":{},"explanation":"用户想查看当前的拓扑概览"}'},
]


def _build_topology_summary(topology: Topology) -> str:
    """构建拓扑摘要文本，追加到 system prompt 中引导 LLM 基于真实数据输出"""
    nodes_str = "\n".join(
        f"  {n.id} (IP: {n.ip or 'N/A'}, 类型: {n.type.value})"
        for n in topology.nodes
    )
    links_str = "\n".join(
        f"  {l.source} ↔ {l.target} (状态: {l.state.value}, 带宽: {l.bandwidth_mbps or 'N/A'}Mbps)"
        for l in topology.links
    )
    return (
        "当前网络拓扑（请基于以下真实节点和连接关系解析用户意图，不要虚构节点名）:\n"
        f"节点:\n{nodes_str or '  暂无节点'}\n"
        f"连接:\n{links_str or '  暂无连接'}"
    )


# 语义校验已移至 models/intent.py 的 Pydantic validator 中


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
        retry_context: str = "",
        attempt: int = 0,
        topology: Optional[Topology] = None,
    ) -> Tuple[Optional[ParsedIntent], str]:
        client = self._get_client()

        system_content = SYSTEM_PROMPT
        if topology and topology.nodes:
            system_content += "\n\n" + _build_topology_summary(topology)

        messages = [{"role": "system", "content": system_content}, *FEW_SHOT]
        if retry_context and attempt > 0:
            user_msg = f"重新解析（第{attempt+1}次），上次失败原因：{retry_context}\n原始输入：{user_text}"
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

            if data.get("source_node") and data.get("target_node") and data.get("source_node") == data.get("target_node"):
                return None, "语义验证失败: source_node 和 target_node 不能相同"
                
            if data.get("action") == "redirect_traffic":
                via = data.get("parameters", {}).get("via_node")
                source = data.get("source_node")
                target = data.get("target_node")
                if via and source and via == source:
                    return None, "语义验证失败: via_node 不能与 source_node 相同"
                if via and target and via == target:
                    return None, "语义验证失败: via_node 不能与 target_node 相同"

            intent = ParsedIntent(**data)
            
            return intent, ""
        except json.JSONDecodeError as e:
            return None, f"JSON解析失败: {e}"
        except ValidationError as e:
            return None, f"Schema校验失败: {e.errors()}"
        except Exception as e:
            return None, f"LLM调用异常: {type(e).__name__}: {e}"

    async def parse_with_retry(
        self,
        user_text: str,
        topology: Optional[Topology] = None,
    ) -> Tuple[Optional[ParsedIntent], str, int]:
        """
        带重试的意图解析。
        仅对 JSON 格式错误和语法语义级错误进行重试，不涉及业务校验。
        """
        last_error = ""
        for attempt in range(settings.MAX_LLM_RETRY):
            intent, error = await self.parse(user_text, last_error, attempt, topology)
            if intent is not None:
                return intent, "", attempt
            last_error = error
        return None, last_error, settings.MAX_LLM_RETRY


intent_engine = IntentEngine()
