"""T0.10 协同 worker 骨架（``python -m app.worker.main --role collab|memory|doc``）。

本卡职责（骨架，真实消费逻辑由 T1.6/T2.2/T3.4 的 consumers 落地）：

1. :8001 ``/healthz``（进程存活即 200，**不查依赖**）与 ``/metrics``
   （Prometheus 注册表，业务指标 T0.11 补齐）；
2. 每 ``WORKER_HEARTBEAT_INTERVAL``（10s）写一次 Redis 心跳：
   - 实例 key ``legalmind:worker:{worker_id}``，TTL 30s，value 为元信息 JSON；
   - 在线索引 ZSET ``legalmind:workers:online``（score=最后心跳 epoch，
     顺带修剪过期成员，滚动 TTL 防止全员死亡后索引永驻）；
3. ``ENABLE_KAFKA=true`` 时按角色订阅对应 topic 加入消费组：
   **collab 角色接真实消费器**（``consumers/collab.py`` 驱动轮次执行，T1.6），
   memory/doc 仍空转待命（真实逻辑由 T2.2/T3.4 落地）；broker 不可达则退化为仅心跳；
4. **collab 角色另跑孤儿扫描**（``orphan_scan_loop``）：周期认领租约过期的僵死轮次续跑，
   与消费器共用同一 ``TurnRunner``（T1.6 §3.2 崩溃接力）；
5. SIGTERM/SIGINT → 停心跳/HTTP/消费者，关连接，优雅退出（compose stop 10s 内）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import socket
import sys
import time
import uuid
from typing import Any, Optional

from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ..core.config import settings
from ..core.events import event_bus, make_consumer
from ..core.logging import setup_logging
from ..core.metrics import (
    KAFKA_CONSUMER_MESSAGES,
    WORKER_HEARTBEAT_TS,
    WORKER_ONLINE,
    record_kafka_lag,
)
from ..core.redis_client import close_redis, init_redis
from ..core.tracing import setup_tracing
from ..services.collab.runner import make_turn_runner
from .consumers.collab import consume_turns, orphan_scan_loop
from .consumers.memory import consume_memory_events

logger = logging.getLogger("app.worker")

ROLES = ("collab", "memory", "doc")


# ---------- 纯逻辑（便于单测） ----------

def role_topic(role: str) -> str:
    """角色 → 订阅 topic（collab/memory/doc 三选一）。"""
    return {
        "collab": settings.KAFKA_TOPIC_TURNS,
        "memory": settings.KAFKA_TOPIC_MEMORY,
        "doc": settings.KAFKA_TOPIC_DOC_TASKS,
    }[role]


def build_worker_id(role: str) -> str:
    """稳定前缀 role- + 主机/PID/短随机，保证多副本不撞。"""
    return f"{role}-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _memory_dispatch():
    """惰性取 T2.2 记忆派发器（collab 轮次成功收尾 → 投递 ``memory-events``）。"""
    from ..services.memory.pipeline import dispatch_memory_event

    return dispatch_memory_event


def heartbeat_key(worker_id: str) -> str:
    return f"{settings.WORKER_KEY_PREFIX}:{worker_id}"


def build_payload(role: str, worker_id: str, started_at: float, now: float) -> dict:
    return {
        "role": role,
        "worker_id": worker_id,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "started_at": started_at,
        "ts": now,
    }


async def beat_once(
    redis: Any,
    *,
    role: str,
    worker_id: str,
    started_at: float,
    now: Optional[float] = None,
) -> dict:
    """写一跳心跳：实例 key（EX=TTL）+ ZSET 在线索引（修剪+滚动过期）。"""
    now = time.time() if now is None else now
    payload = build_payload(role, worker_id, started_at, now)
    pipe = redis.pipeline()
    pipe.set(
        heartbeat_key(worker_id),
        json.dumps(payload, ensure_ascii=False),
        ex=settings.WORKER_HEARTBEAT_TTL,
    )
    pipe.zadd(settings.WORKER_INDEX_KEY, {worker_id: now})
    # 修剪判定窗口外的死成员；索引整体滚动 TTL*2，全员 kill 后索引也会消失
    pipe.zremrangebyscore(
        settings.WORKER_INDEX_KEY, 0, now - settings.WORKER_HEARTBEAT_TTL
    )
    pipe.expire(settings.WORKER_INDEX_KEY, settings.WORKER_HEARTBEAT_TTL * 2)
    await pipe.execute()
    WORKER_HEARTBEAT_TS.labels(role=role, worker_id=worker_id).set(now)
    WORKER_ONLINE.labels(role=role, worker_id=worker_id).set(1)
    return payload


async def deregister_worker(redis: Any, role: str, worker_id: str) -> None:
    """优雅停机主动摘除：删实例 key + ZSET 成员（崩溃场景仍由 TTL/修剪兜底）。"""
    pipe = redis.pipeline()
    pipe.delete(heartbeat_key(worker_id))
    pipe.zrem(settings.WORKER_INDEX_KEY, worker_id)
    try:
        await pipe.execute()
    except Exception as e:
        logger.warning("worker.deregister_failed id=%s error=%s", worker_id, e)
    WORKER_ONLINE.labels(role=role, worker_id=worker_id).set(0)


async def list_online(redis: Any, *, now: Optional[float] = None) -> list[dict]:
    """返回当前在线 worker（ZSET 分数在判定窗口内），按最后心跳倒序。"""
    now = time.time() if now is None else now
    cutoff = now - settings.WORKER_HEARTBEAT_TTL
    rows = await redis.zrangebyscore(
        settings.WORKER_INDEX_KEY, f"({cutoff}", "+inf",
        start=0, num=100, withscores=True,
    )
    return [
        {"worker_id": member, "role": member.split("-", 1)[0], "last_beat": score}
        for member, score in rows
    ]


# ---------- 健康端点 ----------

def create_app(
    role: str,
    worker_id: str,
    started_at: float,
    redis: Any = None,
    standby_state: Optional[dict] = None,
) -> web.Application:
    async def healthz(_request: web.Request) -> web.Response:
        # T0.11 约定：healthz 只表进程存活，不查 Redis/Kafka 等依赖
        return web.json_response(
            {"status": "ok", "role": role, "worker_id": worker_id,
             "uptime": round(time.time() - started_at, 1)}
        )

    async def readyz(_request: web.Request) -> web.Response:
        # Redis 是心跳命脉，不可达即不就绪；Kafka 不可达为设计内降级，仅报告
        checks: dict = {}
        ready = True
        try:
            await asyncio.wait_for(redis.ping(), timeout=2.0)
            checks["redis"] = {"status": "healthy"}
        except Exception as e:
            checks["redis"] = {"status": "unhealthy", "error": str(e)}
            ready = False
        if standby_state is not None and settings.ENABLE_KAFKA:
            checks["kafka"] = {"status": standby_state.get("kafka", "starting")}
        elif standby_state is not None:
            checks["kafka"] = {"status": "disabled"}
        return web.json_response(
            {"ready": ready, "checks": checks},
            status=200 if ready else 503,
        )

    async def metrics(_request: web.Request) -> web.Response:
        return web.Response(
            body=generate_latest(),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )

    app = web.Application()
    app.add_routes([
        web.get("/healthz", healthz),
        web.get("/readyz", readyz),
        web.get("/metrics", metrics),
    ])
    return app


# ---------- 后台循环 ----------

async def heartbeat_loop(
    redis: Any, role: str, worker_id: str, started_at: float, stop_event: asyncio.Event
) -> None:
    while not stop_event.is_set():
        try:
            await beat_once(
                redis, role=role, worker_id=worker_id, started_at=started_at
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Redis 短暂故障不杀进程：下一跳重试；超过 TTL 未恢复则 key 过期被判死
            logger.warning("heartbeat.failed role=%s error=%s", role, e)
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=settings.WORKER_HEARTBEAT_INTERVAL
            )
        except asyncio.TimeoutError:
            pass


async def serve_health(
    role: str, worker_id: str, started_at: float, stop_event: asyncio.Event,
    redis: Any = None, standby_state: Optional[dict] = None,
) -> None:
    runner = web.AppRunner(
        create_app(role, worker_id, started_at, redis=redis, standby_state=standby_state)
    )
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.WORKER_HEALTH_PORT)
    await site.start()
    logger.info("worker.health_listening port=%d", settings.WORKER_HEALTH_PORT)
    try:
        await stop_event.wait()
    finally:
        await runner.cleanup()


async def consume_standby(
    role: str, stop_event: asyncio.Event, standby_state: dict
) -> None:
    """ENABLE_KAFKA=true：加入角色消费组空转待命。骨架不处理消息。"""
    topic = role_topic(role)
    group_id = f"legalmind-worker-{role}"
    consumer = make_consumer([topic], group_id=group_id)
    started = False
    try:
        try:
            await asyncio.wait_for(consumer.start(), timeout=20)
            started = True
        except Exception as e:
            # broker 不可达不致命：退化为仅心跳，compose 重启或 T1.6 再接。
            # start 超时会取消其内部协程，已建连接/后台任务必须显式 stop 清理，
            # 否则反复重连会在进程内累积 socket 与 Fetcher 任务。
            standby_state["kafka"] = "degraded"
            logger.warning("worker.consumer_start_failed role=%s error=%s（仅心跳待命）", role, e)
            try:
                await asyncio.wait_for(consumer.stop(), timeout=5)
            except Exception as stop_err:
                logger.debug("worker.consumer_stop_after_start_failed role=%s error=%s", role, stop_err)
            return
        standby_state["kafka"] = "standby"
        logger.info("worker.standby topic=%s group=%s", topic, group_id)
        poll_count = 0
        while not stop_event.is_set():
            data = await consumer.getmany(timeout_ms=1000, max_records=10)
            count = sum(len(msgs) for msgs in data.values())
            if count:
                logger.debug("worker.standby.poll topic=%s count=%d（骨架不处理）", topic, count)
                KAFKA_CONSUMER_MESSAGES.labels(group=group_id, topic=topic).inc(count)
                await consumer.commit()
            # ~每 10 轮（≈10s）刷新一次各分区 lag gauge
            poll_count += 1
            if poll_count % 10 == 0:
                try:
                    await record_kafka_lag(consumer, group_id)
                except Exception as e:
                    logger.debug("worker.lag_probe_failed %s", e)
    finally:
        if started:
            await consumer.stop()
            logger.info("worker.consumer_stopped role=%s", role)


# ---------- 入口 ----------

async def amain(role: str) -> int:
    setup_logging()
    setup_tracing(service_name=f"legalmind-worker-{role}")
    started_at = time.time()
    worker_id = build_worker_id(role)
    logger.info("worker.starting role=%s id=%s kafka=%s", role, worker_id, settings.ENABLE_KAFKA)

    # 心跳是 worker 的存在意义：Redis 起连失败直接非零退出，交编排重启
    try:
        redis = await init_redis()
    except Exception:
        logger.critical("worker.redis_unavailable role=%s 退出交编排重启", role, exc_info=True)
        return 1

    stop_event = asyncio.Event()
    standby_state = {"kafka": "disabled" if not settings.ENABLE_KAFKA else "starting"}
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # Windows 等平台无信号

    tasks = [
        asyncio.create_task(
            heartbeat_loop(redis, role, worker_id, started_at, stop_event),
            name="heartbeat",
        ),
        asyncio.create_task(
            serve_health(role, worker_id, started_at, stop_event,
                         redis=redis, standby_state=standby_state),
            name="health",
        ),
    ]
    # collab 角色持有轮次执行器（消费 + 孤儿扫描共用；线性初始化不建图/不连库）
    collab_runner = (
        make_turn_runner(worker_id=worker_id, memory_dispatch=_memory_dispatch())
        if role == "collab"
        else None
    )

    if settings.ENABLE_KAFKA:
        if collab_runner is not None:
            tasks.append(
                asyncio.create_task(
                    consume_turns(
                        stop_event, worker_id=worker_id,
                        runner=collab_runner, standby_state=standby_state,
                    ),
                    name="kafka",
                )
            )
        elif role == "memory":
            tasks.append(
                asyncio.create_task(
                    consume_memory_events(
                        stop_event, worker_id=worker_id, standby_state=standby_state
                    ),
                    name="kafka",
                )
            )
        else:
            tasks.append(
                asyncio.create_task(
                    consume_standby(role, stop_event, standby_state), name="kafka"
                )
            )
    else:
        logger.info("worker.kafka_disabled 仅心跳待命 ENABLE_KAFKA=false")

    # collab 角色无论 Kafka 开关都跑孤儿扫描：认领僵死轮次续跑（worker 崩溃接力，§3.2）
    if collab_runner is not None:
        tasks.append(
            asyncio.create_task(
                orphan_scan_loop(collab_runner, stop_event), name="orphan-scan"
            )
        )

    await stop_event.wait()
    logger.info("worker.stopping role=%s", role)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await deregister_worker(redis, role, worker_id)  # 正常退出立即摘除，不等 TTL
    await event_bus.close()  # 骨架不生产；保险释放（未启用时为空操作）
    await close_redis()
    logger.info("worker.stopped role=%s", role)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="LegalMind 协同 worker（T0.10 骨架）")
    parser.add_argument("--role", required=True, choices=ROLES)
    args = parser.parse_args()
    code = asyncio.run(amain(args.role))
    sys.exit(code)


if __name__ == "__main__":
    main()
