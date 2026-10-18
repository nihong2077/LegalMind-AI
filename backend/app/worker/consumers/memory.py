"""T2.2 记忆抽取 worker 消费器（``memory-events``）。

轮次成功收尾时由 :func:`app.services.memory.pipeline.dispatch_memory_event` 投递
``{turn_id, conversation_id, user_id}``；本消费器拉到后驱动记忆写入管线
（抽取 → 相似度比对 → 合并/去重提示/新增 → 重嵌入库）。

与 ``collab`` 消费器同构：手动提交 + **单条毒消息隔离**（逐条 try/except，失败重试
``MEMORY_MAX_ATTEMPTS`` 次后发 ``memory-events-dlq`` 并 ack 本条，不阻塞后续消息）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from ...core.config import settings
from ...core.events import event_bus, make_consumer
from ...core.metrics import KAFKA_CONSUMER_MESSAGES, MEMORY_INGEST, record_kafka_lag
from ...services.memory.pipeline import ingest_turn
from ...services.memory.store import MemoryStore

logger = logging.getLogger(__name__)

MEMORY_GROUP_ID = "legalmind-worker-memory"
ConsumerFactory = Callable[..., Any]


async def _publish_dlq(payload: Any, error: Optional[Exception]) -> None:
    body = {
        **(payload if isinstance(payload, dict) else {}),
        "attempts": settings.MEMORY_MAX_ATTEMPTS,
        "error": {
            "type": type(error).__name__ if error else "UnknownError",
            "message": str(error) if error else "",
        },
    }
    try:
        await event_bus.publish(
            settings.KAFKA_TOPIC_MEMORY_DLQ, body, key=str(body.get("conversation_id") or "")
        )
    except Exception as e:  # DLQ 失败不阻断消费循环（fail-open）
        logger.warning("[memory-consumer] DLQ 发布失败（忽略）：%s", e)


async def handle_memory_message(
    payload: Any,
    *,
    store: Optional[MemoryStore] = None,
    llm: Any = None,
) -> dict[str, Any]:
    """处理一条记忆事件：重试 ``MEMORY_MAX_ATTEMPTS`` 次；仍失败 → DLQ + ack（不阻塞）。"""
    turn_id = (payload or {}).get("turn_id") if isinstance(payload, dict) else None
    if not turn_id:
        logger.warning("[memory-consumer] 消息缺少 turn_id，丢弃：%s", payload)
        return {"result": "skipped", "reason": "no_turn_id"}

    last_exc: Optional[Exception] = None
    for attempt in range(1, settings.MEMORY_MAX_ATTEMPTS + 1):
        try:
            return await ingest_turn(turn_id, store=store, llm=llm)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            last_exc = e
            logger.warning(
                "[memory-consumer] 抽取失败 turn=%s attempt=%d/%d：%s",
                turn_id, attempt, settings.MEMORY_MAX_ATTEMPTS, e,
            )
            if attempt < settings.MEMORY_MAX_ATTEMPTS:
                await asyncio.sleep(settings.MEMORY_RETRY_BACKOFF * attempt)

    MEMORY_INGEST.labels(result="dlq").inc()
    await _publish_dlq(payload, last_exc)
    logger.error("[memory-consumer] 重试耗尽进 DLQ turn=%s err=%s", turn_id, last_exc)
    return {"result": "dlq", "reason": str(last_exc)}


async def consume_memory_events(
    stop_event: asyncio.Event,
    *,
    worker_id: str = "memory",
    store: Optional[MemoryStore] = None,
    consumer_factory: Optional[ConsumerFactory] = None,
    standby_state: Optional[dict] = None,
    topic: Optional[str] = None,
    group_id: Optional[str] = None,
) -> None:
    """消费 ``memory-events`` 并驱动记忆写入（手动提交；broker 不可达退化为仅心跳）。"""
    topic = topic or settings.KAFKA_TOPIC_MEMORY
    group_id = group_id or MEMORY_GROUP_ID
    factory = consumer_factory or make_consumer
    consumer = factory([topic], group_id=group_id)

    started = False
    try:
        try:
            await asyncio.wait_for(consumer.start(), timeout=20)
            started = True
        except Exception as e:
            if standby_state is not None:
                standby_state["kafka"] = "degraded"
            logger.warning("[memory-consumer] 启动失败（仅心跳待命）：%s", e)
            try:
                await asyncio.wait_for(consumer.stop(), timeout=5)
            except Exception as stop_err:
                logger.debug("[memory-consumer] 启动失败后清理异常：%s", stop_err)
            return

        if standby_state is not None:
            standby_state["kafka"] = "consuming"
        logger.info("[memory-consumer] 就绪 topic=%s group=%s", topic, group_id)

        poll_count = 0
        while not stop_event.is_set():
            data = await consumer.getmany(timeout_ms=1000, max_records=10)
            count = 0
            for msgs in data.values():
                for msg in msgs:
                    count += 1
                    payload = getattr(msg, "value", msg)
                    try:
                        await handle_memory_message(payload, store=store)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:  # 兜底隔离：一条毒消息不拖垮消费循环
                        logger.warning("[memory-consumer] 消息处理异常（已隔离）：%s", e)
            if count:
                KAFKA_CONSUMER_MESSAGES.labels(group=group_id, topic=topic).inc(count)
                await consumer.commit()
            poll_count += 1
            if poll_count % 10 == 0:
                try:
                    await record_kafka_lag(consumer, group_id)
                except Exception as e:
                    logger.debug("[memory-consumer] lag 探针失败：%s", e)
    finally:
        if started:
            try:
                await consumer.stop()
                logger.info("[memory-consumer] 已停止 topic=%s", topic)
            except Exception as e:
                logger.debug("[memory-consumer] 停止异常：%s", e)
