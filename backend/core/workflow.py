"""
LangGraph 意图处理工作流
将意图解析、工具调用查询拓扑、规则验证与策略执行编排为状态机。
"""
import json
import logging
from typing import Annotated, Dict, Any, Optional, TypedDict, Literal, Tuple

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from config import settings
from models.intent import ParsedIntent
from core.tools import get_node_location, get_active_policies, cancel_active_policy
from core.intent_validator import intent_validator
from core.policy_executor import policy_executor
from core.topo_manager import topo_manager

logger = logging.getLogger(__name__)

# 定义图的状态
class IBNState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    intent_id: str
    execution_result: Optional[Dict[str, Any]]
    parsed_intent: Optional[ParsedIntent]

# 初始化 LLM 并绑定工具和结构化输出
llm = ChatOpenAI(
    model=settings.LLM_MODEL,
    api_key=settings.LLM_API_KEY,
    base_url=settings.LLM_BASE_URL,
    temperature=0.1
)

tools = [get_node_location, get_active_policies, cancel_active_policy]
# 将 ParsedIntent 也绑定为工具，供 LLM 在决策完毕后输出最终意图
llm_with_tools = llm.bind_tools(tools + [ParsedIntent])

# 核心 Agent 节点
async def agent_node(state: IBNState):
    messages = state["messages"]
    # 提取初始用户输入作为参考（如果需要）
    user_request = messages[0].content if messages else ""

    # System Prompt 定义
    system_prompt = """你是一个 SDN 网络控制助手。用户的自然语言将被你解析为结构化网络策略。

【重要规则】
1. 遇到未知节点，必须先调用 get_node_location 工具查询节点位置。
2. 策略冲突检测由系统自动完成，你不需要也不应该做冲突判断，直接解析意图并调用 ParsedIntent 工具输出结果即可。
3. 当用户明确要求撤销某条策略时，调用 cancel_active_policy 工具，完成后再调用 ParsedIntent 确认。
4. 完成节点查询后，必须调用 ParsedIntent 工具输出最终结构化意图。不要用自然语言解释，直接调用工具。"""
    from langchain_core.messages import SystemMessage, AIMessage
    
    # 消息清理：保留完整历史，但清理掉一些大模型 API 可能不兼容的额外参数（如 reasoning_content）
    safe_messages = [SystemMessage(content=system_prompt)]
    for msg in messages:
        if isinstance(msg, AIMessage):
            # 创建新的 AIMessage 以防污染原始状态
            safe_msg = AIMessage(
                content=msg.content, 
                tool_calls=msg.tool_calls,
                additional_kwargs={k: v for k, v in msg.additional_kwargs.items() if k != "reasoning_content"}
            )
            safe_messages.append(safe_msg)
        else:
            safe_messages.append(msg)

    # 引入 asyncio 处理超时（例如限制 LLM 单次思考最长 20 秒）
    import asyncio
    try:
        # 使用 asyncio.wait_for 进行超时控制
        response = await asyncio.wait_for(llm_with_tools.ainvoke(safe_messages), timeout=20.0)
    except asyncio.TimeoutError:
        logger.error("[Workflow] LLM 响应超时")
        # 构造一个假的 ToolCall 去执行失败路线，或者直接返回错误消息
        from langchain_core.messages import AIMessage
        from models.intent import ParsedIntent
        # 伪造一个由于超时导致的解析失败结果
        return {"messages": [AIMessage(content="[System] 请求大模型超时，请重试。")]}

    return {"messages": [response]}



# 路由逻辑
def should_continue(state: IBNState) -> Literal["tools", "execute_and_finish", "__end__"]:
    messages = state["messages"]
    last_message = messages[-1]

    # 如果 LLM 没有进行任何工具调用，强制结束（理论上不应该发生，因为我们绑定了 ParsedIntent）
    if not last_message.tool_calls:
        return "__end__"
    
    # 检查 LLM 是否调用了 ParsedIntent
    for tool_call in last_message.tool_calls:
        if tool_call["name"] == "ParsedIntent":
            return "execute_and_finish"
            
    # 如果调用的都是普通工具（查询拓扑/策略），则走向 tools 节点
    return "tools"

# 执行与终结节点
async def execute_node(state: IBNState):
    messages = state["messages"]
    last_message = messages[-1]
    intent_id = state["intent_id"]
    
    parsed_intent_call = None
    for tool_call in last_message.tool_calls:
        if tool_call["name"] == "ParsedIntent":
            parsed_intent_call = tool_call
            break
            
    if not parsed_intent_call:
        return {"execution_result": {"success": False, "error": "LLM failed to output ParsedIntent"}}
        
    try:
        # 1. 还原 Pydantic 模型
        intent_args = parsed_intent_call["args"]
        parsed_intent = ParsedIntent(**intent_args)
        logger.info(f"[{intent_id}] LLM 输出了 ParsedIntent: {parsed_intent}")
        
        # 2. Rule-based 验证层
        topo = topo_manager.topology
        report = await intent_validator.validate(parsed_intent, topo, intent_id)
        
        # 如果 Rule-based 验证失败
        if not report.overall_passed:
            # 检查是否为冲突类失败：冲突失败直接结束，不触发 LLM 回环重试
            conflict_layer = next((res for res in report.layers if res.layer == "conflict_detection" and not res.passed), None)
            if conflict_layer:
                logger.warning(f"[{intent_id}] 冲突检测失败，直接结束: {conflict_layer.message}")
                # 从活跃策略中补充冲突策略的完整描述
                from core.policy_executor import policy_executor as _pe
                active_map = {p["id"]: p for p in _pe.get_active_policies()}
                enriched_conflicts = []
                for c in (conflict_layer.conflicts or []):
                    c_dict = c.model_dump()
                    pol = active_map.get(c.policy_id, {})
                    c_dict["existing_description"] = pol.get("description", "")
                    c_dict["existing_src"] = pol.get("src_host", "")
                    c_dict["existing_dst"] = pol.get("dst_host", "")
                    enriched_conflicts.append(c_dict)
                conflict_result = {
                    "success": False,
                    "type": "conflict",
                    "message": conflict_layer.message,
                    "conflicts": enriched_conflicts,
                }
                success_msg = ToolMessage(
                    content=json.dumps(conflict_result, ensure_ascii=False),
                    tool_call_id=parsed_intent_call["id"],
                    name="ParsedIntent"
                )
                return {"messages": [success_msg], "execution_result": conflict_result, "parsed_intent": parsed_intent}

            # 非冲突类失败（拓扑/安全）：退回给 LLM 重试
            error_msgs = [f"[{res.layer}] {res.message}" for res in report.layers if not res.passed]
            full_error = "验证失败：\n" + "\n".join(error_msgs) + "\n请根据报错修正你的参数，重新输出 ParsedIntent。"
            
            tool_msg = ToolMessage(
                content=full_error,
                tool_call_id=parsed_intent_call["id"],
                name="ParsedIntent"
            )
            logger.warning(f"[{intent_id}] Rule-based 验证失败，已退回给 LLM 重试: {full_error}")
            return {"messages": [tool_msg]} # 会触发图继续循环回到 agent_node
            
        # 3. 如果验证通过，直接通过 policy_executor 执行
        # 这里为了严谨起见，直接调用 executor，因为 executor 内置了所有执行逻辑。
        
        res = await policy_executor.execute(parsed_intent, intent_id)
        
        # 为了兼容消息链，我们需要返回一个 ToolMessage 表示 ParsedIntent 已经被成功处理
        success_msg = ToolMessage(
            content=json.dumps(res, ensure_ascii=False),
            tool_call_id=parsed_intent_call["id"],
            name="ParsedIntent"
        )
        return {"messages": [success_msg], "execution_result": res, "parsed_intent": parsed_intent}
        
    except Exception as e:
        logger.error(f"[{intent_id}] 执行节点异常: {e}", exc_info=True)
        return {"execution_result": {"success": False, "error": str(e)}, "parsed_intent": None}

# 构建 LangGraph
workflow = StateGraph(IBNState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", ToolNode(tools)) # 仅包含查询类工具
workflow.add_node("execute_and_finish", execute_node)

workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue)
workflow.add_edge("tools", "agent")

# execute_and_finish 可能会因为验证失败回到 agent，也可能会真正结束
def check_finish_route(state: IBNState) -> Literal["agent", "__end__"]:
    if state.get("execution_result") is not None:
        return "__end__"
    return "agent"

workflow.add_conditional_edges("execute_and_finish", check_finish_route)

# 编译图
app = workflow.compile()

# 提供给外部调用的异步包装函数
async def process_intent(user_text: str, intent_id: str) -> Dict[str, Any]:
    """主入口函数：处理用户的自然语言意图"""
    inputs = {
        "messages": [HumanMessage(content=user_text)],
        "intent_id": intent_id,
        "execution_result": None,
        "parsed_intent": None
    }
    
    # 限制递归层数以防死循环
    final_state = await app.ainvoke(inputs, config={"recursion_limit": 10})
    
    result = final_state.get("execution_result")
    parsed_intent = final_state.get("parsed_intent")
    
    if not result:
        return {"success": False, "error": "执行失败：未产生有效结果", "parsed_intent": parsed_intent}
    
    # 将 parsed_intent 塞入 result 方便外层提取
    result["parsed_intent_obj"] = parsed_intent
    return result

async def parse_intent_dry_run(user_text: str) -> Tuple[Optional[ParsedIntent], str]:
    """仅进行意图解析（干运行/调试用）"""
    system_prompt = "你是一个 SDN 网络控制助手。用户的自然语言将被你解析为结构化网络策略。如果无法解析，可输出相应的字段说明。"
    try:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]
        # 使用 bind_tools 替代 with_structured_output 绕过特定 API 的 tool_choice 限制
        llm_strict = llm.bind_tools([ParsedIntent])
        response = await llm_strict.ainvoke(messages)
        
        if not response.tool_calls:
            return None, "LLM failed to output ParsedIntent tool call"
            
        intent_args = response.tool_calls[0]["args"]
        parsed = ParsedIntent(**intent_args)
        return parsed, ""
    except Exception as e:
        return None, str(e)


