"""意图处理 API — 完整的 LLM 意图处理流水线"""
from __future__ import annotations
import time
import uuid
import logging
from typing import List

from fastapi import APIRouter, HTTPException, BackgroundTasks

from models.intent import IntentRequest, IntentRecord, IntentStatus, IntentAction
from core.intent_engine import intent_engine
from core.intent_validator import intent_validator
from core.policy_generator import policy_generator
from core.network_manager import network_manager
from core.vm_connector import vm_connector
from api.websocket_manager import ws_manager

router = APIRouter(prefix="/api/intent", tags=["intent"])
logger = logging.getLogger(__name__)

# 内存存储（生产环境可换为 DB）
_records: dict[str, IntentRecord] = {}


def _now() -> float:
    return time.time()


async def _process_intent(record: IntentRecord):
    """完整意图处理流水线（后台任务）"""
    try:
        # ── Step 1: LLM 解析（带重试）
        record.status = IntentStatus.VALIDATING
        record.updated_at = _now()
        await ws_manager.broadcast_intent_update(record.model_dump())

        intent, error, retries = await intent_engine.parse_with_retry(record.user_text)
        record.llm_retries = retries

        if intent is None:
            record.status = IntentStatus.FAILED
            record.error_message = f"意图解析失败（重试{retries}次）: {error}"
            record.updated_at = _now()
            await ws_manager.broadcast_intent_update(record.model_dump())
            return

        record.parsed_intent = intent

        # ── Step 2: 多层验证
        validation_report = await intent_validator.validate(intent, network_manager.topology)
        record.validation_report = validation_report

        if not validation_report.overall_passed:
            record.status = IntentStatus.REJECTED
            failed_layers = [l for l in validation_report.layers if not l.passed]
            record.error_message = "验证未通过: " + "; ".join(l.message for l in failed_layers)
            record.updated_at = _now()
            await ws_manager.broadcast_intent_update(record.model_dump())
            return

        # ── Step 3: 高危操作等待确认（前端需发送 /confirm/{id}）
        if validation_report.requires_confirmation:
            record.status = IntentStatus.CONFIRMED  # 等待前端确认
            record.updated_at = _now()
            await ws_manager.broadcast_intent_update(record.model_dump())
            return  # 暂停，等待 /confirm 接口触发

        # ── Step 4: 生成策略
        await _execute_intent(record)

    except Exception as e:
        logger.error(f"[IntentPipeline] 异常: {e}", exc_info=True)
        record.status = IntentStatus.FAILED
        record.error_message = str(e)
        record.updated_at = _now()
        await ws_manager.broadcast_intent_update(record.model_dump())


async def _execute_intent(record: IntentRecord):
    """生成并执行策略（查询类意图直接返回数据，不走策略生成）"""
    record.status = IntentStatus.EXECUTING
    record.updated_at = _now()
    await ws_manager.broadcast_intent_update(record.model_dump())

    action = record.parsed_intent.action if record.parsed_intent else None

    # ── 查询类意图：直接从 VM 获取数据，无需生成策略 ──
    if action in (IntentAction.QUERY_STATS, IntentAction.QUERY_TOPOLOGY):
        await _handle_query_intent(record)
        return

    # ── 执行类意图：生成策略后下发 ─────────────────────
    policy, rollback, gen_error = policy_generator.generate(
        record.parsed_intent, network_manager.topology, record.id
    )

    if policy is None:
        record.status = IntentStatus.FAILED
        record.error_message = f"策略生成失败: {gen_error}"
        record.updated_at = _now()
        await ws_manager.broadcast_intent_update(record.model_dump())
        return

    # 执行策略
    result = await vm_connector.apply_policy(policy.model_dump())

    if result.get("success"):
        record.status = IntentStatus.SUCCESS
        record.execution_result = {
            "policy": policy.model_dump(),
            "vm_response": result.get("result"),
            "has_rollback": rollback is not None,
        }
    else:
        record.status = IntentStatus.FAILED
        record.error_message = f"策略执行失败: {result.get('error')}"
        # 尝试自动回滚
        if rollback:
            await vm_connector.rollback_policy(rollback.model_dump())
            record.error_message += " (已自动回滚)"

    record.updated_at = _now()
    await ws_manager.broadcast_intent_update(record.model_dump())


async def _handle_query_intent(record: IntentRecord):
    """处理查询类意图（QUERY_STATS / QUERY_TOPOLOGY）"""
    intent = record.parsed_intent
    action = intent.action
    target = intent.source_node or intent.target_node  # 查询目标节点

    try:
        if action == IntentAction.QUERY_TOPOLOGY:
            topo = await vm_connector.get_topology()
            record.status = IntentStatus.SUCCESS
            record.execution_result = {
                "type": "topology",
                "nodes": len(topo.get("nodes", [])),
                "links": len(topo.get("links", [])),
                "data": topo,
                "message": f"当前拓扑：{len(topo.get('nodes',[]))} 个节点，{len(topo.get('links',[]))} 条链路",
            }

        elif action == IntentAction.QUERY_STATS:
            raw = await vm_connector.get_stats()
            switches_raw = raw.get("switches", [])

            # 如果指定了目标节点（如 s1），只返回该节点数据
            if target:
                target_dpid = None
                for node in network_manager.topology.nodes:
                    if node.id == target and node.dpid:
                        target_dpid = node.dpid
                        break

                filtered = [
                    sw for sw in switches_raw
                    if str(sw.get("dpid", "")) == str(target_dpid or target.lstrip("s"))
                ]
                data = filtered if filtered else switches_raw
                label = target
            else:
                data = switches_raw
                label = "所有交换机"

            # 格式化统计摘要
            summary_lines = []
            for sw in data:
                dpid = sw.get("dpid", "?")
                sw_id = f"s{dpid}"
                ports = sw.get("ports", [])
                total_rx = sum(p.get("rx_bytes", 0) for p in ports)
                total_tx = sum(p.get("tx_bytes", 0) for p in ports)
                summary_lines.append(
                    f"{sw_id}: RX {total_rx//1024} KB / TX {total_tx//1024} KB"
                )

            record.status = IntentStatus.SUCCESS
            record.execution_result = {
                "type": "stats",
                "target": label,
                "summary": "\n".join(summary_lines) if summary_lines else "暂无统计数据",
                "data": data,
                "message": f"{label} 流量统计: " + (summary_lines[0] if summary_lines else "暂无数据"),
            }

    except Exception as e:
        record.status = IntentStatus.FAILED
        record.error_message = f"查询失败: {e}"
        record.updated_at = _now()
        await ws_manager.broadcast_intent_update(record.model_dump())
        return

    record.updated_at = _now()
    await ws_manager.broadcast_intent_update(record.model_dump())


@router.post("/process")
async def process_intent(req: IntentRequest, background_tasks: BackgroundTasks):
    """提交自然语言意图，异步处理"""
    record = IntentRecord(
        id=str(uuid.uuid4()),
        user_text=req.text,
        status=IntentStatus.PENDING,
        created_at=_now(),
        updated_at=_now(),
    )
    _records[record.id] = record
    background_tasks.add_task(_process_intent, record)
    return {"intent_id": record.id, "status": record.status}


@router.post("/confirm/{intent_id}")
async def confirm_intent(intent_id: str, background_tasks: BackgroundTasks):
    """用户确认高危操作后继续执行"""
    record = _records.get(intent_id)
    if not record:
        raise HTTPException(404, "意图记录不存在")
    if record.status != IntentStatus.CONFIRMED:
        raise HTTPException(400, f"当前状态 {record.status} 不需要确认")
    background_tasks.add_task(_execute_intent, record)
    return {"message": "已确认，开始执行"}


@router.get("/records")
async def list_records(limit: int = 20) -> List[dict]:
    records = list(reversed(list(_records.values())))[:limit]
    return [r.model_dump() for r in records]


@router.get("/records/{intent_id}")
async def get_record(intent_id: str):
    record = _records.get(intent_id)
    if not record:
        raise HTTPException(404, "意图记录不存在")
    return record.model_dump()
