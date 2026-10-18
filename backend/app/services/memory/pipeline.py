"""
记忆写入管线（P2 T2.2）

一轮对话结束 → 抽取候选 → 与既有记忆向量比对（cosine）→ 合并/去重提示/新增 → 重嵌入库。

- **开关生效**：用户关闭自动记忆（Redis 键）后，本管线整体跳过（不写）。
- **失败隔离**：写库/嵌入失败向上抛，由 consumer 负责重试与 DLQ（本模块不吞异常）。
- **派发**：``dispatch_memory_event`` 在 Kafka 开启时投递 ``memory-events``；关闭/降级时
  进程内起后台任务直接跑管线（本地开发无需 broker 也能自动记忆）。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Optional

from sqlalchemy import and_, or_, select

from ...core.config import settings
from ...core.embedding import embed_text
from ...core.events import event_bus
from ...core.metrics import MEMORY_EXTRACT, MEMORY_INGEST
from ...core.pg_client import Message, app_session_factory
from ..collab.conversation_store import serialize_message
from ..collab.turn_store import pg_turn_store
from .extractor import extract_candidates
from .store import MemoryStore, get_memory_store, is_memory_enabled

logger = logging.getLogger(__name__)

ACTION_MERGE = "merge"
ACTION_PROMPT = "prompt"
ACTION_NEW = "new"

_MERGE_TEXT_LIMIT = 1200
# 进程内派发的后台任务强引用（避免被 GC 提前回收）
_inprocess_tasks: set[asyncio.Task] = set()


def _uuid(value: Any) -> Optional[uuid.UUID]:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


# ============================================================
# 本轮 transcript
# ============================================================

async def load_turn_transcript(
    turn: dict[str, Any], *, limit: Optional[int] = None
) -> list[dict[str, Any]]:
    """取「本轮」消息（自 ``trigger_message_id`` 起，含触发消息），正序返回最近 ``limit`` 条。"""
    limit = limit or settings.MEMORY_TURN_MESSAGES_LIMIT
    conv_id = _uuid(turn.get("conversation_id"))
    if conv_id is None:
        return []
    async with app_session_factory() as session:
        stmt = select(Message).where(Message.conversation_id == conv_id)
        trigger_id = _uuid(turn.get("trigger_message_id"))
        if trigger_id is not None:
            anchor = await session.get(Message, trigger_id)
            if anchor is not None:
                stmt = stmt.where(
                    or_(
                        Message.created_at > anchor.created_at,
                        and_(
                            Message.created_at == anchor.created_at,
                            Message.id >= anchor.id,
                        ),
                    )
                )
        stmt = stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
        rows = list((await session.execute(stmt)).scalars().all())
    return [serialize_message(m) for m in reversed(rows)]


# ============================================================
# 候选落库：合并 / 去重提示 / 新增
# ============================================================

def _merge_text(old: str, new: str, *, limit: int = _MERGE_TEXT_LIMIT) -> str:
    old, new = (old or "").strip(), (new or "").strip()
    if not old:
        return new
    if not new or new in old:
        return old
    if old in new:
        return new
    return f"{old}；{new}"[:limit]


async def _apply_candidate(
    store: MemoryStore, user_id: str, cand: dict[str, Any]
) -> dict[str, Any]:
    """比对既有记忆向量并落库，返回 ``{action, memory_id, score?}``。"""
    vector = await embed_text(cand["content"])
    hits = await store.similar(
        user_id,
        vector,
        case_id=cand.get("case_id"),
        top_k=5,
        score_threshold=settings.MEMORY_DEDUP_THRESHOLD,
    )
    best = hits[0] if hits else None
    best_payload = (best or {}).get("payload") or {}
    best_score = float(best["score"]) if best else 0.0

    # ≥ 合并阈值：并入既有记忆（内容合并 + importance 取高）
    if best and best_score >= settings.MEMORY_MERGE_THRESHOLD:
        memory_id = best_payload.get("memory_id")
        existing = await store.get(user_id, memory_id) if memory_id else None
        if existing is not None:
            merged = await store.update(
                user_id,
                memory_id,
                content=_merge_text(existing.get("content", ""), cand["content"]),
                importance=max(int(existing.get("importance") or 3), cand["importance"]),
            )
            if merged is not None:
                MEMORY_EXTRACT.labels(action=ACTION_MERGE).inc()
                logger.info(
                    "[memory] 合并记忆 user=%s id=%s score=%.3f", user_id, memory_id, best_score
                )
                return {"action": ACTION_MERGE, "memory_id": memory_id, "score": best_score}

    # 0.75–0.90：疑似重复 → 新增但标记「去重提示」（便于后续人工/前端确认）
    if best:
        created = await store.create(
            user_id,
            scope=cand["scope"],
            memory_type=cand["memory_type"],
            content=cand["content"],
            summary=cand["summary"],
            importance=cand["importance"],
            case_id=cand.get("case_id"),
        )
        MEMORY_EXTRACT.labels(action=ACTION_PROMPT).inc()
        logger.info(
            "[memory] 去重提示（疑似重复，已新增待确认）user=%s 新=%s 近似=%s score=%.3f",
            user_id, created["id"], best_payload.get("memory_id"), best_score,
        )
        return {
            "action": ACTION_PROMPT,
            "memory_id": created["id"],
            "similar_memory_id": best_payload.get("memory_id"),
            "score": best_score,
        }

    # < 去重阈值：全新记忆
    created = await store.create(
        user_id,
        scope=cand["scope"],
        memory_type=cand["memory_type"],
        content=cand["content"],
        summary=cand["summary"],
        importance=cand["importance"],
        case_id=cand.get("case_id"),
    )
    MEMORY_EXTRACT.labels(action=ACTION_NEW).inc()
    return {"action": ACTION_NEW, "memory_id": created["id"]}


# ============================================================
# 管线主入口
# ============================================================

async def ingest_turn(
    turn_id: str,
    *,
    store: Optional[MemoryStore] = None,
    llm: Any = None,
) -> dict[str, Any]:
    """抽取并写入一轮对话产生的记忆。异常向上抛（consumer 重试/DLQ）。"""
    store = store or get_memory_store()
    turn = await pg_turn_store.get_turn(turn_id)
    if turn is None:
        MEMORY_INGEST.labels(result="skipped").inc()
        return {"result": "skipped", "reason": "turn_not_found"}

    user_id = turn.get("user_id") or ""
    if not await is_memory_enabled(user_id):
        MEMORY_INGEST.labels(result="skipped").inc()
        logger.info("[memory] 用户已关闭自动记忆，跳过 turn=%s user=%s", turn_id, user_id)
        return {"result": "skipped", "reason": "disabled"}

    transcript = await load_turn_transcript(turn)
    if not transcript:
        MEMORY_INGEST.labels(result="skipped").inc()
        return {"result": "skipped", "reason": "empty_transcript"}

    candidates = await extract_candidates(transcript, llm=llm)
    applied: list[dict[str, Any]] = []
    for cand in candidates:
        applied.append(await _apply_candidate(store, user_id, cand))

    MEMORY_INGEST.labels(result="ok").inc()
    logger.info(
        "[memory] 写入完成 turn=%s user=%s candidates=%d applied=%s",
        turn_id, user_id, len(candidates),
        [a["action"] for a in applied],
    )
    return {
        "result": "ok",
        "turn_id": turn_id,
        "user_id": user_id,
        "candidates": len(candidates),
        "applied": applied,
    }


# ============================================================
# 派发（turn 结束触发；Kafka 优先，关闭/降级走进程内）
# ============================================================

async def dispatch_memory_event(turn: dict[str, Any]) -> None:
    """在轮次成功收尾时派发记忆事件（fail-open：任何异常都不影响轮次终态）。"""
    payload = {
        "turn_id": turn.get("turn_id"),
        "conversation_id": turn.get("conversation_id"),
        "user_id": turn.get("user_id"),
    }
    if not payload["turn_id"]:
        return
    try:
        if settings.ENABLE_KAFKA:
            sent = await event_bus.publish(
                settings.KAFKA_TOPIC_MEMORY,
                payload,
                key=payload["conversation_id"],
            )
            if sent:
                return
            logger.warning(
                "[memory] Kafka 入队降级，改进程内抽取 turn=%s", payload["turn_id"]
            )
        task = asyncio.ensure_future(_ingest_inprocess(payload["turn_id"]))
        _inprocess_tasks.add(task)
        task.add_done_callback(_inprocess_tasks.discard)
    except Exception as e:  # pragma: no cover - 派发失败不阻断轮次收尾
        logger.warning("[memory] 派发失败（忽略）：%s", e)


async def _ingest_inprocess(turn_id: str) -> None:
    try:
        await ingest_turn(turn_id)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # pragma: no cover - 后台任务失败仅告警
        MEMORY_INGEST.labels(result="error").inc()
        logger.warning("[memory] 进程内抽取失败 turn=%s：%s", turn_id, e)
