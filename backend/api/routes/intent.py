"""意图处理 API — 简化版 3 步流水线：LLM 解析 → 直接执行 → WebSocket 推送"""
from __future__ import annotations
import time
import uuid
import logging
from typing import List

from fastapi import APIRouter, HTTPException, BackgroundTasks

from models.intent import IntentRequest, IntentRecord, IntentStatus
from core.intent_engine import intent_engine
from core.policy_executor import policy_executor
from core.topo_manager import topo_manager
from api.websocket_manager import ws_manager

router = APIRouter(prefix="/api/intent", tags=["intent"])
logger = logging.getLogger(__name__)

# 内存存储（最近 200 条记录）
_records: dict[str, IntentRecord] = {}


def _now() -> float:
    return time.time()


async def _process(record: IntentRecord):
    """意图处理流水线（后台异步执行）"""
    try:
        # ── Step 1: LLM 解析 ───────────────────────────────
        record.status = IntentStatus.PARSING
        record.updated_at = _now()
        await ws_manager.broadcast_intent_update(record.model_dump())

        topo_ctx = topo_manager.get_llm_context()
        intent, error, retries = await intent_engine.parse_with_retry(
            record.user_text, topo_context=topo_ctx
        )
        record.llm_retries = retries

        if intent is None:
            record.status = IntentStatus.FAILED
            record.error_message = f"意图解析失败（重试 {retries} 次）: {error}"
            record.updated_at = _now()
            await ws_manager.broadcast_intent_update(record.model_dump())
            return

        record.parsed_intent = intent

        # ── Step 2: 执行 ───────────────────────────────────
        record.status = IntentStatus.EXECUTING
        record.updated_at = _now()
        await ws_manager.broadcast_intent_update(record.model_dump())

        result = await policy_executor.execute(intent, record.id)

        if result.get("success"):
            record.status = IntentStatus.SUCCESS
            record.execution_result = result
        else:
            record.status = IntentStatus.FAILED
            record.error_message = result.get("error", "执行失败")
            record.execution_result = result

        record.updated_at = _now()
        await ws_manager.broadcast_intent_update(record.model_dump())

        # ── Step 3: 控制操作后刷新拓扑和策略 ──────────────
        query_actions = {"query_topology", "query_flows", "query_port_stats"}
        if intent.action.value not in query_actions and result.get("success"):
            await topo_manager.refresh()
            # 推送策略更新
            await ws_manager.broadcast({
                "type": "policy_update",
                "data": policy_executor.get_active_policies(),
            })

    except Exception as e:
        logger.error(f"[IntentProcess] 异常: {e}", exc_info=True)
        record.status = IntentStatus.FAILED
        record.error_message = str(e)
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

    # 限制内存，保留最近 200 条
    if len(_records) > 200:
        keys = sorted(_records, key=lambda k: _records[k].created_at)
        for k in keys[:50]:
            _records.pop(k, None)

    background_tasks.add_task(_process, record)
    return {"intent_id": record.id, "status": record.status}


@router.get("/records")
async def list_records(limit: int = 20) -> List[dict]:
    records = list(reversed(list(_records.values())))[:limit]
    return [r.model_dump() for r in records]


@router.get("/records/{intent_id}")
async def get_record(intent_id: str):
    record = _records.get(intent_id)
    if not record:
        raise HTTPException(404, "记录不存在")
    return record.model_dump()
