"""
LangGraph 意图处理工作流
将意图解析、工具调用查询拓扑、规则验证与策略执行编排为状态机。
"""
import json
import logging
from typing import Annotated, Dict, Any, Optional, TypedDict, Literal, Tuple, List

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from config import settings
from models.intent import ParsedIntent, ClarificationNeeded
from core.intent_tools import get_node_location, get_active_policies, cancel_active_policy
from core.intent_validator import intent_validator
from core.policy_executor import policy_executor
from core.topology_manager import topo_manager

logger = logging.getLogger(__name__)

class IntentList(BaseModel):
    """用于包装多个网络意图操作的列表。即使只有一个操作，也请放在列表中。"""
    intents: List[ParsedIntent] = Field(..., description="要执行的网络操作意图列表，按顺序执行。")

# 定义图的状态
class IBNState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    intent_id: str
    execution_result: Optional[Dict[str, Any]]
    parsed_intents: Optional[List[ParsedIntent]]

# 初始化 LLM 并绑定工具和结构化输出
llm = ChatOpenAI(
    model=settings.LLM_MODEL,
    api_key=settings.LLM_API_KEY,
    base_url=settings.LLM_BASE_URL,
    temperature=0.1
)

tools = [get_node_location, get_active_policies, cancel_active_policy]
# 将 IntentList 和 ClarificationNeeded 绑定为工具
llm_with_tools = llm.bind_tools(tools + [IntentList, ClarificationNeeded])

# 核心 Agent 节点
async def agent_node(state: IBNState):
    """LangGraph Agent 节点：调用 LLM 解析用户意图并决定下一步工具调用"""
    messages = state["messages"]

    # System Prompt 定义
    system_prompt = """你是一个 SDN 网络控制助手。用户的自然语言将被你解析为结构化的网络策略（IntentList 包含一组 ParsedIntent）。

【重要规则】
1. 遇到未知节点，必须先调用 get_node_location 工具查询节点位置。
2. 策略冲突检测由系统自动完成，你不需做冲突判断。
3. 当用户明确要求撤销某条策略时，调用 cancel_active_policy 工具。
4. 必须调用 IntentList 工具输出最终的意图列表。对于复合指令，可以拆分成多个独立的 ParsedIntent 放入列表中。
5. **消歧与澄清机制**：如果用户的指令语义模糊（例如：未说明是单向还是双向，“只能通信”是否意味着双向均阻断其他通信？或者指令有明显歧义），**请调用 ClarificationNeeded 工具**，提供给用户清晰的选择选项，**不要**调用 IntentList 瞎猜。
6. 关注策略的单双向 `direction` 属性。如果不确定通常默认为 `bidirectional`，但明确的“单向”请使用 `unidirectional`。

【参数说明与Few-shot 示例】
- 简单一对一："限制 h1 到 h2 的带宽为 5M"
  => action: rate_limit, source_nodes: ["h1"], target_nodes: ["h2"], action_params: {"bandwidth_mbps": 5}
- 批量与方向："单向阻断 h1 到所有主机的通信"
  => action: block_traffic, scope: "all", source_nodes: ["h1"], target_nodes: [], direction: "unidirectional"
- 排除操作："除了 h2 之外，阻断 h1 和所有人的通信"
  => action: block_traffic, scope: "all", source_nodes: ["h1"], target_nodes: [], exclude_nodes: ["h2"]
- 隔离操作："仅允许 h1 和 h2 通信，阻断与其他所有主机(h3, h4)的通信"
  => 输出包含两个对象的列表：
     1. action: allow_traffic, source_nodes: ["h1"], target_nodes: ["h2"]
     2. action: block_traffic, scope: "all", source_nodes: ["h1", "h2"], target_nodes: []
- 条件匹配："限制 h1 到 h3 的 SSH 流量 (TCP 22)"
  => action: block_traffic, source_nodes: ["h1"], target_nodes: ["h3"], match: {"ip_proto": 6, "tcp_dst": 22}
- 划分VLAN："把 h1 和 h2 划分到 vlan 10"
  => action: vlan, source_nodes: ["h1", "h2"], action_params: {"vlan_id": 10}
- 链路负载均衡："在 h1 和 h2 之间启用链路多路径负载均衡"
  => action: multipath, source_nodes: ["h1"], target_nodes: ["h2"]
- 复合操作："先限制 h1 到 h2 带宽 5M，然后隔离 h3"
  => 输出包含两个对象的列表：
     1. action: rate_limit, source_nodes: ["h1"], target_nodes: ["h2"], action_params: {"bandwidth_mbps": 5}
     2. action: block_traffic, source_nodes: ["h3"], scope: "all"
"""
    from langchain_core.messages import SystemMessage, AIMessage
    
    # 消息清理
    safe_messages = [SystemMessage(content=system_prompt)]
    for msg in messages:
        if isinstance(msg, AIMessage):
            safe_msg = AIMessage(
                content=msg.content, 
                tool_calls=msg.tool_calls,
                additional_kwargs={k: v for k, v in msg.additional_kwargs.items() if k != "reasoning_content"}
            )
            safe_messages.append(safe_msg)
        else:
            safe_messages.append(msg)

    import asyncio
    try:
        response = await asyncio.wait_for(llm_with_tools.ainvoke(safe_messages), timeout=20.0)
    except asyncio.TimeoutError:
        logger.error("[Workflow] LLM 响应超时")
        raise Exception("请求大模型超时，请稍后重试。")

    return {"messages": [response]}


# 路由逻辑
def should_continue(state: IBNState) -> Literal["tools", "execute_and_finish", "__end__"]:
    """路由函数：根据 LLM 输出的 tool_calls 决定下一步走向"""
    messages = state["messages"]
    last_message = messages[-1]

    if not last_message.tool_calls:
        return "__end__"
    
    for tool_call in last_message.tool_calls:
        if tool_call["name"] in ["IntentList", "ClarificationNeeded"]:
            return "execute_and_finish"
            
    return "tools"

# 执行与终结节点
async def execute_node(state: IBNState):
    """执行与终结节点：解析 LLM 输出的 IntentList 或 ClarificationNeeded，执行策略或返回澄清"""
    messages = state["messages"]
    last_message = messages[-1]
    intent_id = state["intent_id"]
    
    intent_list_call = None
    clarification_call = None
    for tool_call in last_message.tool_calls:
        if tool_call["name"] == "ClarificationNeeded":
            clarification_call = tool_call
            break
        elif tool_call["name"] == "IntentList":
            intent_list_call = tool_call
            break
            
    if clarification_call:
        args = clarification_call["args"]
        res = {
            "success": False,
            "type": "clarification",
            "reason": args.get("reason", "您的指令存在歧义，需要澄清："),
            "options": args.get("options", [])
        }
        success_msg = ToolMessage(
            content=json.dumps(res, ensure_ascii=False),
            tool_call_id=clarification_call["id"],
            name="ClarificationNeeded"
        )
        return {"messages": [success_msg], "execution_result": res, "parsed_intents": None}

    if not intent_list_call:
        return {"execution_result": {"success": False, "error": "LLM failed to output IntentList or ClarificationNeeded"}}
        
    try:
        # 1. 还原 Pydantic 模型
        args = intent_list_call["args"]
        intent_list = IntentList(**args)
        parsed_intents = intent_list.intents
        logger.info(f"[{intent_id}] LLM 输出了 {len(parsed_intents)} 个 ParsedIntent")
        
        # 2. Rule-based 验证层 (逐一验证)
        topo = topo_manager.topology
        all_reports = []
        for pi in parsed_intents:
            report = await intent_validator.validate(pi, topo, intent_id)
            all_reports.append((pi, report))
            
            if not report.overall_passed:
                # 遇到失败，立刻返回错误给 LLM 重试
                conflict_layer = next((res for res in report.layers if res.layer == "conflict_detection" and not res.passed), None)
                if conflict_layer:
                    logger.warning(f"[{intent_id}] 冲突检测失败: {conflict_layer.message}")
                    from core.policy_executor import policy_executor as _pe
                    active_map = {p["id"]: p for p in _pe.get_active_policies()}
                    enriched_conflicts = []
                    for c in (conflict_layer.conflicts or []):
                        c_dict = c.model_dump()
                        pol = active_map.get(c.policy_id, {})
                        c_dict["existing_description"] = pol.get("description", "")
                        enriched_conflicts.append(c_dict)
                    conflict_result = {
                        "success": False,
                        "type": "conflict",
                        "message": conflict_layer.message,
                        "conflicts": enriched_conflicts,
                    }
                    success_msg = ToolMessage(
                        content=json.dumps(conflict_result, ensure_ascii=False),
                        tool_call_id=intent_list_call["id"],
                        name="IntentList"
                    )
                    return {"messages": [success_msg], "execution_result": conflict_result, "parsed_intents": parsed_intents}

                # 非冲突类失败（拓扑/安全）：退回给 LLM 重试
                error_msgs = [f"[{res.layer}] {res.message}" for res in report.layers if not res.passed]
                full_error = f"意图 {pi.action} 验证失败：\n" + "\n".join(error_msgs) + "\n请根据报错修正你的参数，重新输出 IntentList。"
                
                tool_msg = ToolMessage(
                    content=full_error,
                    tool_call_id=intent_list_call["id"],
                    name="IntentList"
                )
                return {"messages": [tool_msg]} 
            
        # 3. 验证全部通过后，逐个执行
        final_results = []
        for i, pi in enumerate(parsed_intents):
            sub_id = f"{intent_id}_{i}" if len(parsed_intents) > 1 else intent_id
            res = await policy_executor.execute(pi, sub_id)
            final_results.append(res)
            # 若中间有失败，可以视情况中断或继续。这里简化为全部执行完毕，合并结果。
        
        # 将结果合并展示给前端
        merged_res = {
            "success": all(r.get("success", False) for r in final_results),
            "type": final_results[0].get("type") if len(final_results) == 1 else "composite",
            "message": "\n".join([r.get("message", r.get("error", "未知错误")) for r in final_results]),
            "details": final_results
        }
        
        success_msg = ToolMessage(
            content=json.dumps(merged_res, ensure_ascii=False),
            tool_call_id=intent_list_call["id"],
            name="IntentList"
        )
        return {"messages": [success_msg], "execution_result": merged_res, "parsed_intents": parsed_intents}
        
    except Exception as e:
        logger.error(f"[{intent_id}] 执行节点异常: {e}", exc_info=True)
        return {"execution_result": {"success": False, "error": str(e)}, "parsed_intents": None}

# 构建 LangGraph
workflow = StateGraph(IBNState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", ToolNode(tools))
workflow.add_node("execute_and_finish", execute_node)

workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue)
workflow.add_edge("tools", "agent")

def check_finish_route(state: IBNState) -> Literal["agent", "__end__"]:
    """检查执行结果，决定是结束还是回到 Agent 重试"""
    if state.get("execution_result") is not None:
        return "__end__"
    return "agent"

workflow.add_conditional_edges("execute_and_finish", check_finish_route)

# 编译图
app = workflow.compile()

async def process_intent(user_text: str, intent_id: str) -> Dict[str, Any]:
    """主入口函数：处理用户的自然语言意图"""
    inputs = {
        "messages": [HumanMessage(content=user_text)],
        "intent_id": intent_id,
        "execution_result": None,
        "parsed_intents": None
    }
    
    final_state = await app.ainvoke(inputs, config={"recursion_limit": 10})
    
    result = final_state.get("execution_result")
    parsed_intents = final_state.get("parsed_intents")
    
    if not result:
        # 尝试检查大模型是否用纯文本进行了对话反问
        last_msg = final_state["messages"][-1]
        from langchain_core.messages import AIMessage
        if isinstance(last_msg, AIMessage) and not last_msg.tool_calls:
            return {
                "success": True, 
                "type": "chat", 
                "message": last_msg.content,
                "parsed_intents": None
            }
        return {"success": False, "error": "执行失败：未产生有效结果", "parsed_intents": parsed_intents}
    
    # 存入列表供前端记录
    result["parsed_intent_list"] = parsed_intents
    # 为了兼容前端现在的气泡展示，取第一个意图作为主意图
    if parsed_intents:
        result["parsed_intent_obj"] = parsed_intents[0]

    return result

async def parse_intent_dry_run(user_text: str) -> Tuple[Optional[List[ParsedIntent]], str]:
    """仅进行意图解析（干运行/调试用）"""
    system_prompt = "你是一个 SDN 网络控制助手。解析意图并输出 IntentList。"
    try:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]
        llm_strict = llm.bind_tools([IntentList])
        response = await llm_strict.ainvoke(messages)
        
        if not response.tool_calls:
            return None, "LLM failed to output IntentList tool call"
            
        args = response.tool_calls[0]["args"]
        parsed = IntentList(**args)
        return parsed.intents, ""
    except Exception as e:
        return None, str(e)



