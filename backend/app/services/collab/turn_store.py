"""
协同轮次台账存储层（T1.6）——恢复与幂等的权威依据

对齐
[docs/collab-supervisor-checkpoint_spec.md](../../../../docs/collab-supervisor-checkpoint_spec.md) §4.1/§4.3：
``collab_turns`` 记录「谁在执行、跑到哪、失败了几次」，是 Kafka 重投 / worker 崩溃 / 租约过期时
判断「跳过 / 续跑 / 进 DLQ」的唯一权威源。

与 ``conversation_store`` 同样的抽象方式：``TurnStore`` 协议便于无 DB 单测注入内存实现，
生产用 ``PgTurnStore``（SQLAlchemy ORM，短事务）。轮次状态机（§4.3）：

    running ──host ask_user──▶ interrupted ──resume──▶ running
    running ──全部节点成功──▶ completed（终态）
    running ──attempts≥N──▶ failed（DLQ；可重试→running）
    任意时刻 worker 心跳超时 → 视为 running 孤儿 → 被其它副本认领续跑
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.pg_client import CollabTurn, app_session_factory

# ---- 状态常量（与 04-app-schema.sql CHECK 约束一致）----
TURN_RUNNING = "running"
TURN_INTERRUPTED = "interrupted"
TURN_COMPLETED = "completed"
TURN_FAILED = "failed"

TURN_STATUSES = (TURN_RUNNING, TURN_INTERRUPTED, TURN_COMPLETED, TURN_FAILED)
# 终态：不再被 Kafka 重投或孤儿扫描续跑
TERMINAL_STATUSES = (TURN_COMPLETED, TURN_FAILED)
# 未终态：可被认领续跑（running 需租约过期；interrupted 等待用户输入）
OPEN_STATUSES = (TURN_RUNNING, TURN_INTERRUPTED)

# 执行模式
MODE_INPROCESS = "inprocess"
MODE_KAFKA = "kafka"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def serialize_turn(turn: CollabTurn) -> dict[str, Any]:
    """序列化 ``collab_turns`` 行（对外统一用 turn_id 字符串）。"""
    return {
        "turn_id": str(turn.turn_id),
        "conversation_id": str(turn.conversation_id),
        "user_id": turn.user_id,
        "trigger_message_id": (
            str(turn.trigger_message_id) if turn.trigger_message_id is not None else None
        ),
        "status": turn.status,
        "mode": turn.mode,
        "worker_id": turn.worker_id,
        "worker_heartbeat": _dt(turn.worker_heartbeat),
        "attempts": int(turn.attempts or 0),
        "last_checkpoint_id": turn.last_checkpoint_id,
        "error": turn.error or None,
        "forked_from_turn_id": (
            str(turn.forked_from_turn_id) if turn.forked_from_turn_id is not None else None
        ),
        "created_at": _dt(turn.created_at),
        "updated_at": _dt(turn.updated_at),
        "completed_at": _dt(turn.completed_at),
    }


# ============================================================
# Store 协议
# ============================================================

class TurnStore(Protocol):
    async def create_turn(
        self,
        conversation_id: str,
        user_id: str,
        *,
        mode: str = MODE_INPROCESS,
        trigger_message_id: Optional[str] = None,
        forked_from_turn_id: Optional[str] = None,
    ) -> dict: ...

    async def get_turn(self, turn_id: str) -> Optional[dict]: ...

    async def get_open_turn(self, conversation_id: str) -> Optional[dict]: ...

    async def list_turns(self, conversation_id: str, limit: int = 20) -> list[dict]: ...

    async def update_turn(
        self,
        turn_id: str,
        *,
        status: Optional[str] = None,
        error: Optional[dict] = None,
        checkpoint_id: Optional[str] = None,
        worker_id: Optional[str] = None,
        completed: bool = False,
    ) -> Optional[dict]: ...

    async def heartbeat(self, turn_id: str, worker_id: str) -> bool: ...

    async def increment_attempts(self, turn_id: str) -> Optional[int]: ...

    async def claim_orphan_turns(
        self, worker_id: str, *, lease_seconds: int, limit: int = 50
    ) -> list[dict]: ...


# ============================================================
# PostgreSQL 实现
# ============================================================

class PgTurnStore:
    """每个方法一个短事务（``app_session_factory`` 上下文自动关闭）。"""

    async def create_turn(
        self,
        conversation_id: str,
        user_id: str,
        *,
        mode: str = MODE_INPROCESS,
        trigger_message_id: Optional[str] = None,
        forked_from_turn_id: Optional[str] = None,
    ) -> dict:
        async with app_session_factory() as session:
            turn = CollabTurn(
                conversation_id=self._uuid(conversation_id),
                user_id=user_id,
                status=TURN_RUNNING,
                mode=mode if mode in (MODE_INPROCESS, MODE_KAFKA) else MODE_INPROCESS,
                attempts=0,
                trigger_message_id=(
                    self._uuid(trigger_message_id) if trigger_message_id else None
                ),
                forked_from_turn_id=(
                    self._uuid(forked_from_turn_id) if forked_from_turn_id else None
                ),
                worker_heartbeat=_now(),
            )
            session.add(turn)
            await session.commit()
            await session.refresh(turn)
            return serialize_turn(turn)

    async def get_turn(self, turn_id: str) -> Optional[dict]:
        async with app_session_factory() as session:
            turn = await session.get(CollabTurn, self._uuid(turn_id))
            return serialize_turn(turn) if turn is not None else None

    async def get_open_turn(self, conversation_id: str) -> Optional[dict]:
        """最近一个未终态轮次（running/interrupted）——用户发言据此决定「续跑 or 新轮次」。"""
        async with app_session_factory() as session:
            stmt = (
                select(CollabTurn)
                .where(
                    CollabTurn.conversation_id == self._uuid(conversation_id),
                    CollabTurn.status.in_(OPEN_STATUSES),
                )
                .order_by(CollabTurn.created_at.desc())
                .limit(1)
            )
            turn = (await session.execute(stmt)).scalar_one_or_none()
            return serialize_turn(turn) if turn is not None else None

    async def list_turns(self, conversation_id: str, limit: int = 20) -> list[dict]:
        async with app_session_factory() as session:
            stmt = (
                select(CollabTurn)
                .where(CollabTurn.conversation_id == self._uuid(conversation_id))
                .order_by(CollabTurn.created_at.desc())
                .limit(max(1, min(limit, 100)))
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [serialize_turn(t) for t in rows]

    async def update_turn(
        self,
        turn_id: str,
        *,
        status: Optional[str] = None,
        error: Optional[dict] = None,
        checkpoint_id: Optional[str] = None,
        worker_id: Optional[str] = None,
        completed: bool = False,
    ) -> Optional[dict]:
        async with app_session_factory() as session:
            values: dict[str, Any] = {"updated_at": _now()}
            if status is not None:
                values["status"] = status
            if error is not None:
                values["error"] = error
            if checkpoint_id is not None:
                values["last_checkpoint_id"] = checkpoint_id
            if worker_id is not None:
                values["worker_id"] = worker_id
                values["worker_heartbeat"] = _now()
            if completed:
                values["completed_at"] = _now()
            stmt = (
                update(CollabTurn)
                .where(CollabTurn.turn_id == self._uuid(turn_id))
                .values(**values)
                .returning(CollabTurn)
            )
            turn = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
            return serialize_turn(turn) if turn is not None else None

    async def heartbeat(self, turn_id: str, worker_id: str) -> bool:
        """续租：刷新 worker_id + worker_heartbeat（90s 无心跳即被视为僵死）。"""
        async with app_session_factory() as session:
            stmt = (
                update(CollabTurn)
                .where(CollabTurn.turn_id == self._uuid(turn_id))
                .values(worker_id=worker_id, worker_heartbeat=_now(), updated_at=_now())
            )
            result = await session.execute(stmt)
            await session.commit()
            return bool(result.rowcount)

    async def increment_attempts(self, turn_id: str) -> Optional[int]:
        """失败计一次：原子自增并返回新值（判断是否达到 DLQ 阈值）。"""
        async with app_session_factory() as session:
            stmt = (
                update(CollabTurn)
                .where(CollabTurn.turn_id == self._uuid(turn_id))
                .values(attempts=CollabTurn.attempts + 1, updated_at=_now())
                .returning(CollabTurn.attempts)
            )
            new_value = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
            return int(new_value) if new_value is not None else None

    async def claim_orphan_turns(
        self, worker_id: str, *, lease_seconds: int, limit: int = 50
    ) -> list[dict]:
        """认领租约过期的 running 轮次（worker 崩溃/重启后接力续跑）。

        ``FOR UPDATE SKIP LOCKED`` 保证多副本并发扫描时同一 turn 只被一个 worker 认领
        （与 Redis 轮次锁共同构成「同一 turn 单执行者」的双保险）。
        """
        cutoff = _now() - timedelta(seconds=max(0, int(lease_seconds)))
        async with app_session_factory() as session:
            ids_stmt = (
                select(CollabTurn.turn_id)
                .where(
                    CollabTurn.status == TURN_RUNNING,
                    (CollabTurn.worker_heartbeat.is_(None))
                    | (CollabTurn.worker_heartbeat < cutoff),
                )
                .order_by(CollabTurn.created_at.asc())
                .limit(max(1, min(limit, 200)))
                .with_for_update(skip_locked=True)
            )
            ids = list((await session.execute(ids_stmt)).scalars().all())
            if not ids:
                return []
            stmt = (
                update(CollabTurn)
                .where(CollabTurn.turn_id.in_(ids))
                .values(worker_id=worker_id, worker_heartbeat=_now(), updated_at=_now())
                .returning(CollabTurn)
            )
            rows = (await session.execute(stmt)).scalars().all()
            await session.commit()
            return [serialize_turn(t) for t in rows]

    @staticmethod
    def _uuid(value: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError):
            raise ValueError(f"非法 turn_id：{value}")


# 进程级单例（路由/runner 依赖默认注入；测试可 override）
pg_turn_store = PgTurnStore()
