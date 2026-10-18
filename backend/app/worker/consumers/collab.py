"""T1.6 协同轮次 worker 消费器（``collab-turns``）。

与 API 进程内执行**共用同一 ``TurnRunner``**（双模式）：Kafka 开启时，用户发言由 API
``event_bus.publish`` 入队，本消费器拉到 ``{turn_id, conversation_id, user_id}`` 后调用
``runner.execute_turn(turn_id)`` 驱动整轮。三条保险共同保证「重投不重跑、崩溃可续跑」：
轮次台账终态幂等（terminal 直接 ack 跳过）+ Redis 轮次锁（同一 turn 单执行者）
+ LangGraph checkpoint（从最近 super-step 续跑，已发言不重复）。

两条后台循环：
1. :func:`consume_turns` —— 消费 ``collab-turns``，逐条执行轮次（手动提交；业务异常在
   runner 内已成 failed/DLQ，**毒消息按条 ack 不阻塞后续**）；
2. :func:`orphan_scan_loop` —— 周期 :meth:`TurnRunner.recover_orphans`，认领租约过期的
   ``running`` 轮次续跑（worker 崩溃接力，规格 §3.2）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from ...core.config import settings
from ...core.events import make_consumer
from ...core.metrics import COLLAB_TURN_ORPHAN, KAFKA_CONSUMER_MESSAGES, record_kafka_lag
from ...services.collab.runner import TurnOutcome, TurnRunner, make_turn_runner

logger = logging.getLogger(__name__)

COLLAB_GROUP_ID = "legalmind-worker-collab"
ConsumerFactory = Callable[..., Any]


def _runner_or_default(worker_id: str, runner: Optional[TurnRunner]) -> TurnRunner:
    return runner if runner is not None else make_turn_runner(worker_id=worker_id)


async def handle_turn_message(
    runner: TurnRunner, payload: Any
) -> Optional[TurnOutcome]:
    """处理一条轮次消息：据 ``turn_id`` 驱动整轮（terminal 幂等由 runner 内部跳过）。"""
    turn_id = (payload or {}).get("turn_id") if isinstance(payload, dict) else None
    if not turn_id:
        logger.warning("[collab-consumer] 消息缺少 turn_id，丢弃：%s", payload)
        return None
    outcome = await runner.execute_turn(turn_id)
    logger.info(
        "[collab-consumer] 轮次处理完成 turn=%s status=%s skipped=%s",
        turn_id, outcome.status, outcome.skipped,
    )
    return outcome


async def _dispatch(runner: TurnRunner, value: Any) -> Optional[TurnOutcome]:
    """单条消息执行 + 异常隔离（一条毒消息不拖垮消费循环）。"""
    try:
        return await handle_turn_message(runner, value)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # runner 内部已尽力降级，此处兜底仅告警
        logger.warning("[collab-consumer] 轮次执行异常（已隔离）：%s", e)
        return None


async def consume_turns(
    stop_event: asyncio.Event,
    *,
    worker_id: str,
    runner: Optional[TurnRunner] = None,
    consumer_factory: Optional[ConsumerFactory] = None,
    standby_state: Optional[dict] = None,
    topic: Optional[str] = None,
    group_id: Optional[str] = None,
) -> None:
    """消费 ``collab-turns`` 并驱动轮次（手动提交；broker 不可达退化为仅心跳）。"""
    topic = topic or settings.KAFKA_TOPIC_TURNS
    group_id = group_id or COLLAB_GROUP_ID
    runner = _runner_or_default(worker_id, runner)
    factory = consumer_factory or make_consumer
    consumer = factory([topic], group_id=group_id)

    started = False
    try:
        try:
            await asyncio.wait_for(consumer.start(), timeout=20)
            started = True
        except Exception as e:
            # broker 不可达不致命：退化为仅心跳（与骨架 standby 同策略）
            if standby_state is not None:
                standby_state["kafka"] = "degraded"
            logger.warning("[collab-consumer] 启动失败（仅心跳待命）：%s", e)
            try:
                await asyncio.wait_for(consumer.stop(), timeout=5)
            except Exception as stop_err:
                logger.debug("[collab-consumer] 启动失败后清理异常：%s", stop_err)
            return

        if standby_state is not None:
            standby_state["kafka"] = "consuming"
        logger.info("[collab-consumer] 就绪 topic=%s group=%s", topic, group_id)

        poll_count = 0
        while not stop_event.is_set():
            data = await consumer.getmany(timeout_ms=1000, max_records=10)
            count = 0
            for msgs in data.values():
                for msg in msgs:
                    count += 1
                    await _dispatch(runner, getattr(msg, "value", msg))
            if count:
                KAFKA_CONSUMER_MESSAGES.labels(group=group_id, topic=topic).inc(count)
                await consumer.commit()
            poll_count += 1
            if poll_count % 10 == 0:
                try:
                    await record_kafka_lag(consumer, group_id)
                except Exception as e:
                    logger.debug("[collab-consumer] lag 探针失败：%s", e)
    finally:
        if started:
            try:
                await consumer.stop()
                logger.info("[collab-consumer] 已停止 topic=%s", topic)
            except Exception as e:
                logger.debug("[collab-consumer] 停止异常：%s", e)


async def orphan_scan_loop(
    runner: TurnRunner,
    stop_event: asyncio.Event,
    *,
    interval: Optional[float] = None,
    limit: int = 50,
) -> None:
    """周期扫描僵死轮次并认领续跑（worker 崩溃接力，§3.2）。"""
    interval = settings.TURN_ORPHAN_SCAN_INTERVAL if interval is None else interval
    while not stop_event.is_set():
        try:
            outcomes = await runner.recover_orphans(limit=limit)
            for out in outcomes:
                COLLAB_TURN_ORPHAN.labels(
                    result="skipped" if out.skipped else "recovered"
                ).inc()
            if outcomes:
                logger.info("[orphan-scan] 认领并处理僵死轮次 %d 个", len(outcomes))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # 扫描失败不杀进程：下一周期重试
            logger.warning("[orphan-scan] 扫描失败（下周期重试）：%s", e)
        if interval and interval > 0:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(0)
