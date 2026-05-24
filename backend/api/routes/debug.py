"""
诊断 API — 提供系统各组件的可观测性接口
覆盖：系统健康检查、意图管道追踪、各层干运行、VM 直连测试
"""
from __future__ import annotations
import time
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.intent_engine import intent_engine
from core.intent_validator import intent_validator
from core.policy_generator import policy_generator
from core.network_manager import network_manager
from core.vm_connector import vm_connector
from models.intent import IntentRequest, ParsedIntent, IntentAction
from models.policy import PolicyType, NetworkPolicy, FlowMatch, FlowAction
from api.websocket_manager import ws_manager

router = APIRouter(prefix="/api/debug", tags=["debug"])
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  1. 系统健康总览
# ─────────────────────────────────────────────────────────────

@router.get("/health", summary="系统健康总览")
async def debug_health():
    """
    检查所有子系统的健康状态：
    - LLM 服务可达性（通过配置判断）
    - VM Agent 连通性
    - 拓扑数据状态
    - WebSocket 连接数
    """
    from config import settings

    vm_ok = await vm_connector.ping()
    topo = network_manager.get_topology_dict()
    node_count = len(topo.get("nodes", []))
    link_count = len(topo.get("links", []))

    return {
        "timestamp": time.time(),
        "overall": "ok" if vm_ok else "degraded",
        "components": {
            "vm_agent": {
                "status": "ok" if vm_ok else "unreachable",
                "url": settings.VM_AGENT_URL,
            },
            "llm": {
                "status": "configured",
                "base_url": settings.LLM_BASE_URL,
                "model": settings.LLM_MODEL,
                "max_retry": settings.MAX_LLM_RETRY,
            },
            "topology": {
                "status": "ok" if node_count > 0 else "empty",
                "node_count": node_count,
                "link_count": link_count,
                "last_update": topo.get("timestamp"),
            },
            "websocket": {
                "active_connections": len(ws_manager._connections),
            },
        },
        "alerts_count": len(network_manager.alerts),
    }


# ─────────────────────────────────────────────────────────────
#  2. 意图管道追踪（dry-run，不实际执行）
# ─────────────────────────────────────────────────────────────

class DryRunRequest(BaseModel):
    text: str
    stop_at: str = "policy"   # llm | validate | policy（逐步停止便于定位问题层）


@router.post("/dry-run", summary="意图管道干运行（不实际下发）")
async def debug_dry_run(req: DryRunRequest):
    """
    对一段自然语言意图完整走一遍处理管道（LLM解析→验证→策略生成），
    但不向 VM Agent 下发任何命令，用于诊断哪一层出了问题。

    stop_at 参数控制停在哪一层：
    - llm      : 仅执行 LLM 解析
    - validate : 执行到验证层
    - policy   : 执行到策略生成（默认，最完整）
    """
    result: Dict[str, Any] = {
        "input": req.text,
        "stop_at": req.stop_at,
        "timestamp": time.time(),
        "stages": {},
    }

    # ── Stage 1: LLM 解析（注入拓扑上下文） ──
    t0 = time.perf_counter()
    intent, error, retries = await intent_engine.parse_with_retry(
        req.text,
        topology=network_manager.topology,
    )
    llm_ms = round((time.perf_counter() - t0) * 1000, 1)

    result["stages"]["llm"] = {
        "ok": intent is not None,
        "elapsed_ms": llm_ms,
        "retries": retries,
        "error": error or None,
        "parsed_intent": intent.model_dump() if intent else None,
    }

    if intent is None or req.stop_at == "llm":
        result["conclusion"] = "LLM解析失败" if intent is None else "已在LLM层停止"
        return result

    # ── Stage 2: 验证 ──
    t1 = time.perf_counter()
    report = await intent_validator.validate(intent, network_manager.topology)
    val_ms = round((time.perf_counter() - t1) * 1000, 1)

    result["stages"]["validate"] = {
        "ok": report.overall_passed,
        "elapsed_ms": val_ms,
        "overall_passed": report.overall_passed,
        "requires_confirmation": report.requires_confirmation,
        "risk_level": report.risk_level,
        "layers": [l.model_dump() for l in report.layers],
    }

    if not report.overall_passed or req.stop_at == "validate":
        result["conclusion"] = (
            "验证未通过: " + "; ".join(l.message for l in report.layers if not l.passed)
            if not report.overall_passed else "已在验证层停止"
        )
        return result

    # ── Stage 3: 策略生成 ──
    t2 = time.perf_counter()
    policy, rollback, gen_err = policy_generator.generate(
        intent, network_manager.topology, "dry-run"
    )
    gen_ms = round((time.perf_counter() - t2) * 1000, 1)

    result["stages"]["policy"] = {
        "ok": policy is not None,
        "elapsed_ms": gen_ms,
        "error": gen_err or None,
        "policy": policy.model_dump() if policy else None,
        "rollback": rollback.model_dump() if rollback else None,
    }

    result["conclusion"] = (
        f"策略生成失败: {gen_err}" if policy is None else "策略生成成功（未实际下发）"
    )
    return result


# ─────────────────────────────────────────────────────────────
#  3. 意图记录追踪（查历史执行链路）
# ─────────────────────────────────────────────────────────────

@router.get("/pipeline/{intent_id}", summary="查看指定意图的完整执行链路")
async def debug_pipeline_trace(intent_id: str):
    """
    从内存记录中取出指定 intent_id 的完整执行信息，
    包括每个阶段的结果、状态、验证报告和最终执行结果。
    """
    # 延迟导入，避免循环依赖
    from api.routes.intent import intent_records
    record = intent_records.get(intent_id)
    if not record:
        raise HTTPException(404, f"intent_id={intent_id} 不存在（可能已过期被清理）")

    parsed = record.parsed_intent
    val_report = record.validation_report

    return {
        "intent_id": intent_id,
        "user_text": record.user_text,
        "status": record.status,
        "llm_retries": record.llm_retries,
        "error_message": record.error_message,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "elapsed_ms": round((record.updated_at - record.created_at) * 1000, 1),
        "pipeline": {
            "llm": {
                "ok": parsed is not None,
                "action": parsed.action if parsed else None,
                "source_node": parsed.source_node if parsed else None,
                "target_node": parsed.target_node if parsed else None,
                "parameters": parsed.parameters if parsed else None,
                "confidence": parsed.confidence if parsed else None,
                "explanation": parsed.explanation if parsed else None,
            },
            "validate": {
                "ok": val_report.overall_passed if val_report else None,
                "requires_confirmation": val_report.requires_confirmation if val_report else None,
                "risk_level": val_report.risk_level if val_report else None,
                "layers": [l.model_dump() for l in val_report.layers] if val_report else None,
            } if val_report else {"ok": None, "skipped": True},
            "execution": record.execution_result,
        },
    }


# ─────────────────────────────────────────────────────────────
#  4. 历史意图统计汇总
# ─────────────────────────────────────────────────────────────

@router.get("/stats/actions", summary="动作执行统计")
async def debug_action_stats():
    """
    统计各 action 类型的执行次数、成功率、失败原因分布。
    """
    from api.routes.intent import intent_records
    from models.intent import IntentStatus

    counters: Dict[str, Dict] = {}
    for record in intent_records.values():
        action = (
            record.parsed_intent.action
            if record.parsed_intent else "__parse_failed__"
        )
        if action not in counters:
            counters[action] = {"total": 0, "success": 0, "failed": 0, "rejected": 0, "pending": 0, "errors": []}
        counters[action]["total"] += 1
        s = record.status
        if s == IntentStatus.SUCCESS:
            counters[action]["success"] += 1
        elif s == IntentStatus.FAILED:
            counters[action]["failed"] += 1
            if record.error_message:
                counters[action]["errors"].append(record.error_message[:120])
        elif s == IntentStatus.REJECTED:
            counters[action]["rejected"] += 1
        else:
            counters[action]["pending"] += 1

    # 截断错误列表，只保留最近 5 条
    for v in counters.values():
        v["errors"] = v["errors"][-5:]
        v["success_rate"] = (
            round(v["success"] / v["total"] * 100, 1) if v["total"] else 0
        )

    return {
        "timestamp": time.time(),
        "total_records": sum(v["total"] for v in counters.values()),
        "actions": counters,
    }


# ─────────────────────────────────────────────────────────────
#  5. VM Agent 直连测试
# ─────────────────────────────────────────────────────────────

class VMTestRequest(BaseModel):
    command: str


@router.post("/test/vm-cmd", summary="直接向 VM Agent 发送 Mininet 命令")
async def debug_test_vm_cmd(req: VMTestRequest):
    """
    不经过意图解析，直接向 VM Agent 的 /mininet/exec 发送命令。
    用于验证 VM Agent 是否正常响应，以及具体命令格式是否正确。
    """
    t0 = time.perf_counter()
    result = await vm_connector.exec_mininet_cmd(req.command)
    elapsed = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "command": req.command,
        "elapsed_ms": elapsed,
        "result": result,
    }


class PolicyTestRequest(BaseModel):
    policy: Dict[str, Any]


@router.post("/test/vm-policy", summary="直接向 VM Agent 下发策略")
async def debug_test_vm_policy(req: PolicyTestRequest):
    """
    不经过意图解析，直接将 policy JSON 发送到 VM Agent 的 /policy/apply。
    用于验证 Ryu Agent 端的策略接收和处理是否正常。
    """
    t0 = time.perf_counter()
    result = await vm_connector.apply_policy(req.policy)
    elapsed = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "elapsed_ms": elapsed,
        "result": result,
    }


# ─────────────────────────────────────────────────────────────
#  6. 拓扑诊断
# ─────────────────────────────────────────────────────────────

@router.get("/topology", summary="当前拓扑诊断视图")
async def debug_topology():
    """
    返回当前拓扑的诊断信息，包括节点、链路、端口映射表，
    便于确认 policy_generator 能否正确解析端口。
    """
    topo = network_manager.topology
    port_map: List[Dict] = []

    for link in topo.links:
        port_map.append({
            "link_id": link.id,
            "source": link.source,
            "target": link.target,
            "src_port": link.src_port,
            "dst_port": link.dst_port,
            "state": link.state,
        })

    return {
        "timestamp": topo.timestamp,
        "nodes": [
            {
                "id": n.id,
                "type": n.type,
                "ip": n.ip,
                "dpid": n.dpid,
            }
            for n in topo.nodes
        ],
        "links": port_map,
        "port_resolution_available": any(
            l.src_port is not None for l in topo.links
        ),
    }
