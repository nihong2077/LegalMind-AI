"""
LangGraph Postgres Checkpointer（T0.9）

- AsyncPostgresSaver 连 ``legalmind_app`` 库，startup 调 ``setup()`` 建表：
  checkpoints / checkpoint_blobs / checkpoint_writes（+ 迁移表），幂等；
- 使用 psycopg AsyncConnectionPool（长生命周期、并发安全），连接级
  autocommit + prepare_threshold=0 + dict_row（对齐官方 from_conn_string）；
- 故障可降级：初始化失败只告警、get_checkpointer() 返回 None，
  上层图可在 P1 选择内存检查点或直接报"协同暂不可用"，不阻断 API 启动。
"""
from __future__ import annotations

import logging
from typing import Optional

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import settings

logger = logging.getLogger(__name__)

_pool: Optional[AsyncConnectionPool] = None
_checkpointer: Optional[AsyncPostgresSaver] = None


def to_psycopg_dsn(url: Optional[str] = None) -> str:
    """SQLAlchemy 风格 URL（postgresql+asyncpg://...）→ psycopg DSN（postgresql://...）。"""
    raw = url or settings.PG_APP_URL
    return raw.replace("+asyncpg", "").replace("+psycopg2", "")


async def init_checkpointer(
    *,
    dsn: Optional[str] = None,
    pool_max_size: Optional[int] = None,
) -> Optional[AsyncPostgresSaver]:
    """建池 + 建表，返回全局 checkpointer。幂等；失败抛异常由 lifespan 决定降级。"""
    global _pool, _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    dsn = to_psycopg_dsn(dsn)
    pool = AsyncConnectionPool(
        dsn,
        open=False,
        min_size=1,
        max_size=pool_max_size or settings.CHECKPOINT_POOL_MAX_SIZE,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,  # PgBouncer/多语句兼容，与官方示例一致
            "row_factory": dict_row,
        },
    )
    try:
        await pool.open(wait=True)
        saver = AsyncPostgresSaver(conn=pool)
        # CREATE TABLE IF NOT EXISTS：checkpoints / checkpoint_blobs / checkpoint_writes
        await saver.setup()
    except Exception:
        await _safe_close_pool(pool)
        raise

    _pool = pool
    _checkpointer = saver
    logger.info(
        "[checkpoint] LangGraph Postgres 检查点已就绪（表：checkpoints/"
        "checkpoint_blobs/checkpoint_writes，pool_max=%d）",
        pool.max_size,
    )
    return _checkpointer


async def close_checkpointer() -> None:
    """优雅停机：关闭连接池（幂等，未初始化时安全空操作）。"""
    global _pool, _checkpointer
    pool, _pool = _pool, None
    _checkpointer = None
    if pool is not None:
        await _safe_close_pool(pool)
        logger.info("[checkpoint] 检查点连接池已关闭")


async def _safe_close_pool(pool: AsyncConnectionPool) -> None:
    try:
        await pool.close()
    except Exception as e:
        logger.warning("[checkpoint] 连接池关闭异常（忽略）：%s", e)


def get_checkpointer() -> Optional[AsyncPostgresSaver]:
    """返回全局 checkpointer；未就绪时为 None（上层据此降级）。"""
    return _checkpointer
