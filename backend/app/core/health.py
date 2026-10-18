"""
探针聚合（T0.11）

- ``/healthz``：存活探针，**不查任何依赖**，进程在即 200（由路由直接返回）；
- ``readiness_report()``：就绪探针，并行检查 Redis / PostgreSQL / Qdrant /
  Kafka 生产者（ENABLE_KAFKA=false 时为 disabled，不算失败）。每项独立超时、
  异常隔离；任一必需依赖不健康 → ready=False（HTTP 503）。
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from sqlalchemy import text

CHECK_TIMEOUT_SECONDS = 2.5      # 单项依赖检查超时
KAFKA_CHECK_TIMEOUT_SECONDS = 6.0  # 首次懒连可能受 KAFKA_CONNECT_TIMEOUT 约束


def _timed(check: Callable[[], Awaitable[dict]], timeout: float) -> Callable[[], Awaitable[dict]]:
    async def wrapped() -> dict:
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(check(), timeout=timeout)
            result.setdefault("latency_ms", round((time.perf_counter() - start) * 1000, 1))
            return result
        except asyncio.TimeoutError:
            return {"status": "unhealthy", "error": f"timeout after {timeout}s"}
        except Exception as e:
            return {"status": "unhealthy", "error": f"{type(e).__name__}: {e}"}
    return wrapped


async def check_redis() -> dict:
    from .redis_client import get_redis
    await get_redis().ping()
    return {"status": "healthy"}


async def check_postgres() -> dict:
    from .pg_client import ENGINES, app_engine
    engines = {**ENGINES, "app": app_engine}
    dbs: dict[str, dict] = {}
    failed = []
    for name, engine in engines.items():
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            dbs[name] = {"status": "healthy"}
        except Exception as e:
            dbs[name] = {"status": "unhealthy", "error": f"{type(e).__name__}: {e}"}
            failed.append(name)
    if failed:
        return {"status": "unhealthy", "databases": dbs, "failed": failed}
    return {"status": "healthy", "databases": list(dbs)}


async def check_qdrant() -> dict:
    from .qdrant_client import get_qdrant_client_or_none
    # 只用 lifespan 已预热实例：本地模式冷构造会从磁盘加载数十秒，
    # 绝不能在探针路径触发（否则冻结事件循环，拖垮并行检查与 /healthz）。
    client = get_qdrant_client_or_none()
    if client is None:
        return {"status": "unhealthy", "error": "client not initialized"}
    collections = await client.get_collections()
    return {"status": "healthy", "collections": len(collections.collections)}


async def check_kafka() -> dict:
    """ENABLED=true：触发懒连并要求 connected；false：disabled 不阻断就绪。"""
    from .events import event_bus
    report = await event_bus.readiness()
    if not report["enabled"]:
        return {"status": "disabled", "bootstrap_servers": report["bootstrap_servers"]}
    report["status"] = "healthy" if report["connected"] else "unhealthy"
    return report


# (检查名, 超时)；协程工厂在 readiness_report() 时按名动态取模块属性，
# 便于单测 monkeypatch 单项检查而不触碰真实依赖。
_CHECKS = (
    ("redis", CHECK_TIMEOUT_SECONDS),
    ("postgres", CHECK_TIMEOUT_SECONDS),
    ("qdrant", CHECK_TIMEOUT_SECONDS),
    ("kafka", KAFKA_CHECK_TIMEOUT_SECONDS),
)


async def readiness_report() -> dict:
    """并行跑全部检查，返回 ``{"ready": bool, "checks": {...}}``。永不抛异常。"""
    results = await asyncio.gather(
        *(
            _timed(globals()[f"check_{name}"], timeout)()
            for name, timeout in _CHECKS
        ),
        return_exceptions=False,  # _timed 已兜底，不会抛
    )
    checks = dict(zip([n for n, _ in _CHECKS], results))
    # disabled 不算未就绪；其余非 healthy 即未就绪
    ready = all(
        c.get("status") in ("healthy", "disabled") for c in checks.values()
    )
    return {"ready": ready, "checks": checks}
