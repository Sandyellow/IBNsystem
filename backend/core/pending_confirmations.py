"""
Pending Confirmations Store — 存储等待用户二次确认的操作

两种类型：
  - "risk"    : 高危操作（CLEAR_FLOWS / scope=all 的 BLOCK/ACL）
  - "override": OVERRIDE 冲突，等待用户确认是否替换旧策略
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from models.intent import ParsedIntent

logger = logging.getLogger(__name__)

# Token 有效期（秒）
TOKEN_TTL = 60


@dataclass
class PendingItem:
    """等待用户确认的操作条目"""
    intent: ParsedIntent
    intent_id: str
    confirmation_type: str          # "risk" | "override"
    created_at: float = field(default_factory=time.time)
    old_policy_id: Optional[str] = None  # OVERRIDE 时：待替换的旧策略 ID

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > TOKEN_TTL


# 全局内存字典：token → PendingItem
_store: Dict[str, PendingItem] = {}


def add_pending(token: str, item: PendingItem) -> None:
    """添加一个待确认操作"""
    _store[token] = item
    logger.info(f"[PendingConfirm] 新增 token={token[:8]}… type={item.confirmation_type}")


def pop_pending(token: str) -> Optional[PendingItem]:
    """取出并删除一个待确认操作（若不存在或已过期则返回 None）"""
    item = _store.pop(token, None)
    if item is None:
        logger.warning(f"[PendingConfirm] token={token[:8]}… 不存在或已过期")
        return None
    if item.is_expired():
        logger.warning(f"[PendingConfirm] token={token[:8]}… 已超时（{TOKEN_TTL}s），自动丢弃")
        return None
    return item


def cleanup_expired() -> int:
    """清理所有已超时的 pending 条目，返回清理数量"""
    expired = [tok for tok, item in _store.items() if item.is_expired()]
    for tok in expired:
        del _store[tok]
    if expired:
        logger.info(f"[PendingConfirm] 清理 {len(expired)} 条超时 token")
    return len(expired)


def get_all() -> Dict[str, PendingItem]:
    """返回当前所有 pending 条目（只读，用于调试）"""
    return dict(_store)
