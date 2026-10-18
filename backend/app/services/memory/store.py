"""
用户长期记忆存储（P2 T2.1）

- 权威内容在 PG ``legalmind_app.memories``；向量在 Qdrant ``user_memories``。
- **按 user_id 收敛**：list/get/update/delete 一律带 user_id 过滤，杜绝跨用户越权。
- 向量侧**尽力而为**：嵌入或写库失败不阻断 CRUD，只把 ``embedding_status`` 回写为 failed。
- 记忆总开关（"关闭后不写不读"，ui-refactor §4.3/§6）以 Redis 键按用户隔离存储，缺省为开。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, or_, select

from ...core.embedding import embed_text
from ...core.pg_client import Memory, app_session_factory
from ...core.qdrant_client import (
    COLLECTION_USER_MEMORIES,
    delete_vectors,
    search_vectors,
    upsert_vectors,
)
from ...core.redis_client import get_redis

logger = logging.getLogger(__name__)

SCOPES = ("user", "case")
STATUSES = ("active", "archived")
EMBEDDING_STATUSES = ("pending", "done", "failed")

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

MEMORY_TOGGLE_KEY = "legalmind:memory:enabled:{user_id}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid_or_none(value: Any) -> Optional[uuid.UUID]:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _to_dict(row: Memory) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "user_id": row.user_id,
        "scope": row.scope,
        "case_id": str(row.case_id) if row.case_id else None,
        "memory_type": row.memory_type,
        "content": row.content,
        "summary": row.summary,
        "importance": row.importance,
        "source_conversation_id": str(row.source_conversation_id) if row.source_conversation_id else None,
        "source_message_id": str(row.source_message_id) if row.source_message_id else None,
        "status": row.status,
        "embedding_status": row.embedding_status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class MemoryStore:
    """PG 权威 + Qdrant 向量的用户记忆存储（每方法一个短事务）。"""

    async def list(
        self,
        user_id: str,
        *,
        scope: Optional[str] = None,
        memory_type: Optional[str] = None,
        case_id: Optional[str] = None,
        status: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        limit = max(1, min(limit, MAX_LIMIT))
        conds = [Memory.user_id == user_id]
        if scope:
            conds.append(Memory.scope == scope)
        if memory_type:
            conds.append(Memory.memory_type == memory_type)
        cid = _uuid_or_none(case_id)
        if cid:
            conds.append(Memory.case_id == cid)
        if status:
            conds.append(Memory.status == status)
        if q:
            like = f"%{q}%"
            conds.append(or_(Memory.content.ilike(like), Memory.summary.ilike(like)))

        stmt = (
            select(Memory)
            .where(*conds)
            .order_by(Memory.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_stmt = select(func.count()).select_from(Memory).where(*conds)

        async with app_session_factory() as session:
            rows = (await session.execute(stmt)).scalars().all()
            total = (await session.execute(count_stmt)).scalar_one()
        return [_to_dict(r) for r in rows], int(total)

    async def get(self, user_id: str, memory_id: str) -> Optional[dict]:
        mid = _uuid_or_none(memory_id)
        if not mid:
            return None
        async with app_session_factory() as session:
            row = await session.get(Memory, mid)
        if row is None or row.user_id != user_id:
            return None
        return _to_dict(row)

    async def create(
        self,
        user_id: str,
        *,
        scope: str,
        memory_type: str,
        content: str,
        summary: Optional[str] = None,
        importance: int = 3,
        case_id: Optional[str] = None,
        source_conversation_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
    ) -> dict:
        row = Memory(
            user_id=user_id,
            scope=scope,
            memory_type=memory_type,
            content=content,
            summary=summary,
            importance=importance,
            case_id=_uuid_or_none(case_id),
            source_conversation_id=_uuid_or_none(source_conversation_id),
            source_message_id=_uuid_or_none(source_message_id),
            status="active",
            embedding_status="pending",
        )
        async with app_session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        created = _to_dict(row)
        await self._index(created)
        return (await self.get(user_id, created["id"])) or created

    async def update(
        self,
        user_id: str,
        memory_id: str,
        *,
        content: Optional[str] = None,
        summary: Optional[str] = None,
        importance: Optional[int] = None,
        memory_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Optional[dict]:
        mid = _uuid_or_none(memory_id)
        if not mid:
            return None
        content_changed = False
        async with app_session_factory() as session:
            row = await session.get(Memory, mid)
            if row is None or row.user_id != user_id:
                return None
            if content is not None:
                content_changed = content != row.content
                row.content = content
            if summary is not None:
                row.summary = summary
            if importance is not None:
                row.importance = importance
            if memory_type is not None:
                row.memory_type = memory_type
            if status is not None and status != row.status:
                row.status = status
            row.updated_at = _now()
            if content_changed:
                row.embedding_status = "pending"
            await session.commit()
            await session.refresh(row)
            updated = _to_dict(row)

        if updated["status"] == "archived":
            # 归档即从向量库摘除，召回时不再命中（T2.3 只读 active）
            await self._unindex(memory_id)
        elif content_changed:
            await self._index(updated)
            return await self.get(user_id, memory_id)
        return updated

    async def delete(self, user_id: str, memory_id: str) -> bool:
        mid = _uuid_or_none(memory_id)
        if not mid:
            return False
        async with app_session_factory() as session:
            row = await session.get(Memory, mid)
            if row is None or row.user_id != user_id:
                return False
            await session.delete(row)
            await session.commit()
        await self._unindex(memory_id)
        return True

    # ---- 向量侧（尽力而为） ----

    async def similar(
        self,
        user_id: str,
        vector: list[float],
        *,
        case_id: Optional[str] = None,
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """在 ``user_memories`` 内按 user_id（可选 case_id）做相似检索（T2.2 去重判定）。

        返回 ``[{id, score, payload}]``；向量库异常时返回空列表（调用方按「新增」降级）。
        """
        conds: dict[str, Any] = {"user_id": user_id}
        if case_id:
            conds["case_id"] = str(case_id)
        try:
            hits = await search_vectors(
                COLLECTION_USER_MEMORIES,
                vector,
                top_k=top_k,
                score_threshold=score_threshold,
                filter_conditions=conds,
            )
        except Exception as e:  # pragma: no cover - 向量库不可用时按新增降级
            logger.warning("[memory] 相似检索失败（按新增降级）：%s", e)
            return []
        return [h for h in hits if (h.get("payload") or {}).get("status") == "active"]

    async def _index(self, memory: dict) -> None:
        try:
            vector = await embed_text(memory["content"])
        except Exception as e:  # pragma: no cover - 依赖模型可用性
            logger.warning("记忆嵌入失败（不阻断 CRUD）memory_id=%s: %s", memory["id"], e)
            await self._set_embedding_status(memory["id"], "failed")
            return
        payload = {
            "memory_id": memory["id"],
            "user_id": memory["user_id"],
            "scope": memory["scope"],
            "case_id": memory["case_id"],
            "memory_type": memory["memory_type"],
            "importance": memory["importance"],
            "status": memory["status"],
        }
        try:
            await upsert_vectors(
                COLLECTION_USER_MEMORIES, [vector], [payload], [memory["id"]]
            )
            await self._set_embedding_status(memory["id"], "done")
        except Exception as e:  # pragma: no cover - 依赖向量库可用性
            logger.warning("记忆向量入库失败（不阻断 CRUD）memory_id=%s: %s", memory["id"], e)
            await self._set_embedding_status(memory["id"], "failed")

    async def _unindex(self, memory_id: str) -> None:
        try:
            await delete_vectors(COLLECTION_USER_MEMORIES, [str(memory_id)])
        except Exception as e:  # pragma: no cover - 降级不影响业务
            logger.warning("记忆向量删除失败（忽略）memory_id=%s: %s", memory_id, e)

    async def _set_embedding_status(self, memory_id: str, value: str) -> None:
        mid = _uuid_or_none(memory_id)
        if not mid:
            return
        try:
            async with app_session_factory() as session:
                row = await session.get(Memory, mid)
                if row is not None:
                    row.embedding_status = value
                    await session.commit()
        except Exception as e:  # pragma: no cover - 状态回写失败可忽略
            logger.warning("记忆 embedding_status 回写失败（忽略）：%s", e)


pg_memory_store = MemoryStore()


def get_memory_store() -> MemoryStore:
    """进程单例（测试可 override 注入内存 fake）。"""
    return pg_memory_store


async def is_memory_enabled(user_id: str) -> bool:
    """记忆召回总开关：缺省为开（Codex 式自动记忆）。"""
    try:
        value = await get_redis().get(MEMORY_TOGGLE_KEY.format(user_id=user_id))
    except Exception as e:  # pragma: no cover - Redis 降级按默认开启
        logger.warning("读取记忆开关失败，按默认开启处理：%s", e)
        return True
    if value is None:
        return True
    return str(value) in ("1", "true", "True")


async def set_memory_enabled(user_id: str, enabled: bool) -> bool:
    await get_redis().set(
        MEMORY_TOGGLE_KEY.format(user_id=user_id), "1" if enabled else "0"
    )
    return enabled
