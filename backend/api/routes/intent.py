"""意图处理 API — 简化版 3 步流水线：LLM 解析 → 直接执行 → WebSocket 推送"""
from __future__ import annotations
import time
import uuid
import logging
from typing import List

from fastapi import APIRouter, HTTPException, BackgroundTasks

from models.intent import IntentRequest, IntentRecord, IntentStatus, IntentAction
from core.workflow import process_intent as graph_process_intent
from core.policy_executor import policy_executor
from core.topology_manager import topo_manager
from api.websocket_manager import ws_manager
from core.pending_confirmations import pop_pending, cleanup_expired

router = APIRouter(prefix="/api/intent", tags=["intent"])
logger = logging.getLogger(__name__)

# 内存存储（最近 200 条记录）
_records: dict[str, IntentRecord] = {}


def _now() -> float:
    return time.time()


async def _process(record: IntentRecord):
    """意图处理流水线（后台异步执行）"""
    try:
        # ── LangGraph 工作流（解析+验证+执行） ────────────────
        record.status = IntentStatus.PARSING # 因为图里包含了这些阶段，我们可以统称为 PARSING 或 EXECUTING
        record.updated_at = _now()
        await ws_manager.broadcast_intent_update(record.model_dump())

        # 调用工作流主入口
        result = await graph_process_intent(record.user_text, record.id)
        
        # 提取图生成的 ParsedIntent 对象
        parsed_intent = result.pop("parsed_intent_obj", None)
        if parsed_intent:
            record.parsed_intent = parsed_intent
            
        record.status = IntentStatus.EXECUTING
        record.updated_at = _now()
        await ws_manager.broadcast_intent_update(record.model_dump())

        if result.get("type") == "clarification":
            record.status = IntentStatus.CLARIFICATION
            record.execution_result = result
        elif result.get("type") == "chat":
            record.status = IntentStatus.CHAT
            record.execution_result = result
        elif result.get("type") == "confirmation_required":
            record.status = IntentStatus.AWAITING_CONFIRMATION
            record.execution_result = result
        elif result.get("success"):
            record.status = IntentStatus.SUCCESS
            record.execution_result = result
        else:
            record.status = IntentStatus.FAILED
            record.error_message = result.get("error", "执行失败")
            record.execution_result = result

        record.updated_at = _now()
        await ws_manager.broadcast_intent_update(record.model_dump())

        # ── 控制操作后刷新拓扑和策略 ──────────────
        query_actions = {
            IntentAction.QUERY_TOPOLOGY.value,
            IntentAction.QUERY_FLOWS.value,
            IntentAction.QUERY_PORT_STATS.value
        }
        # 这里需要从 parsed_intent 中获取 action，因为有可能是查拓扑
        is_query = False
        if parsed_intent and parsed_intent.action.value in query_actions:
            is_query = True
            
        if not is_query and result.get("success"):
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
    """获取最近意图处理记录列表"""
    records = list(reversed(list(_records.values())))[:limit]
    return [r.model_dump() for r in records]


@router.get("/records/{intent_id}")
async def get_record(intent_id: str):
    """根据 ID 获取单条意图处理记录"""
    record = _records.get(intent_id)
    if not record:
        raise HTTPException(404, "记录不存在")
    return record.model_dump()


@router.post("/confirm/{token}")
async def confirm_pending(
    token: str,
    background_tasks: BackgroundTasks,
    cancel: bool = False,
):
    """用户确认或取消一个待确认操作。cancel=true 表示取消。"""
    cleanup_expired()  # 顺便清理过期 token
    item = pop_pending(token)
    if item is None:
        raise HTTPException(404, "确认令牌不存在或已过期，请重新提交意图")

    if cancel:
        logger.info(f"[Confirm] 用户取消 token={token[:8]}… type={item.confirmation_type}")
        cancel_result = {
            "type": "confirmation_cancelled",
            "success": False,
            "message": "操作已取消",
        }
        record = _records.get(item.intent_id)
        if record:
            record.status = IntentStatus.FAILED
            record.execution_result = cancel_result
            record.updated_at = _now()
            await ws_manager.broadcast_intent_update(record.model_dump())
        else:
            await ws_manager.broadcast_intent_update({
                "id": item.intent_id,
                "status": IntentStatus.FAILED,
                "execution_result": cancel_result,
            })
        return cancel_result

    logger.info(f"[Confirm] 用户确认 token={token[:8]}… type={item.confirmation_type}")

    async def _execute_confirmed():
        try:
            # OVERRIDE 类型：先撤销旧策略
            if item.confirmation_type == "override" and item.old_policy_id:
                ok, msg = await policy_executor.delete_policy(item.old_policy_id)
                logger.info(f"[Confirm] 撤销旧策略 {item.old_policy_id}: {ok} {msg}")

            # 执行新意图
            result = await policy_executor.execute(item.intent, item.intent_id)
            result["confirmation_type"] = item.confirmation_type

            # 推送执行结果给前端
            if result.get("success"):
                status = IntentStatus.SUCCESS
                await topo_manager.refresh()
                await ws_manager.broadcast({
                    "type": "policy_update",
                    "data": policy_executor.get_active_policies(),
                })
            else:
                status = IntentStatus.FAILED

            record = _records.get(item.intent_id)
            if record:
                record.status = status
                record.execution_result = result
                record.updated_at = _now()
                await ws_manager.broadcast_intent_update(record.model_dump())
            else:
                await ws_manager.broadcast_intent_update({
                    "id": item.intent_id,
                    "status": status,
                    "execution_result": result,
                })
        except Exception as e:
            logger.error(f"[Confirm] 执行异常: {e}", exc_info=True)
            record = _records.get(item.intent_id)
            if record:
                record.status = IntentStatus.FAILED
                record.execution_result = {"success": False, "error": str(e)}
                record.updated_at = _now()
                await ws_manager.broadcast_intent_update(record.model_dump())
            else:
                await ws_manager.broadcast_intent_update({
                    "id": item.intent_id,
                    "status": IntentStatus.FAILED,
                    "execution_result": {"success": False, "error": str(e)},
                })

    background_tasks.add_task(_execute_confirmed)
    return {"message": "正在执行确认操作，结果将通过 WebSocket 推送"}
