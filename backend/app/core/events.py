"""
Kafka 事件总线（T0.8）

设计约束（实施计划 §3 T0.8 + §6 风险 5）：
- **懒连**：进程启动不连 broker，首次 publish 时才建连（ENABLE_KAFKA=false 零开销）；
- **失败降级不阻断业务**：开关关闭 / 建连超时 / 发送异常 → publish 返回 False 并告警，
  调用方可据此走进程内降级（如直接入队/仅记库），绝不让 MQ 故障冒泡到请求链路；
- 消息体 JSON（ensure_ascii=False），headers 自动带 request_id，与 T0.6 日志/trace 对账；
- 消费者工厂留给 T0.10 worker 复用（手动提交、earliest、JSON 反序列化）。

用法：
    from app.core.events import event_bus
    sent = await event_bus.publish(settings.KAFKA_TOPIC_TURNS, {"turn_id": "..."}, key="conv_1")
    # sent=False 即已降级，调用方走本地兜底
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from .config import settings
from .metrics import KAFKA_PUBLISH
from .response import get_request_id

logger = logging.getLogger(__name__)


class EventBus:
    """aiokafka 生产者封装（进程内单例见 module 级 ``event_bus``）。"""

    def __init__(self, producer_factory=None):
        # producer_factory 可注入，便于单测用 fake；默认延迟导入避免无 broker 环境强依赖
        self._producer = None
        self._connect_lock = asyncio.Lock()
        self._factory = producer_factory
        self._last_error: Optional[str] = None
        # 停机标志：close() 后拒绝重建生产者（避免停机窗口的连接泄漏竞态）
        self._closed = False
        # 持有后台发送任务的强引用，避免被 GC（asyncio 仅弱引用未托管任务）
        self._inflight: set[asyncio.Future] = set()

    # ---------------- 连接管理 ----------------

    async def _get_producer(self):
        """懒连；建连失败/超时或已停机返回 None（不抛异常）。"""
        if self._closed:
            return None
        if self._producer is not None:
            return self._producer
        async with self._connect_lock:
            if self._closed:
                return None
            if self._producer is not None:
                return self._producer
            try:
                producer = await asyncio.wait_for(
                    self._create_producer(), timeout=settings.KAFKA_CONNECT_TIMEOUT
                )
            except Exception as e:
                self._last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    "[kafka] 懒连失败，事件发送已降级（不阻断业务）：%s", self._last_error
                )
                return None
            self._producer = producer
            self._last_error = None
            logger.info(
                "[kafka] 生产者已连接 bootstrap=%s client=%s",
                settings.KAFKA_BOOTSTRAP_SERVERS, settings.KAFKA_CLIENT_ID,
            )
            return producer

    async def _create_producer(self):
        from aiokafka import AIOKafkaProducer

        factory = self._factory or AIOKafkaProducer
        producer = factory(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            client_id=settings.KAFKA_CLIENT_ID,
            acks=1,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if isinstance(k, str) else k,
            max_batch_size=16384,
        )
        await producer.start()
        return producer

    # ---------------- 发送 ----------------

    async def publish(
        self,
        topic: str,
        value: dict[str, Any],
        *,
        key: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> bool:
        """发一条 JSON 事件。成功入队返回 True；开关关/降级返回 False（不抛异常）。

        采用缓冲发送（``send``）：消息先进客户端批量缓冲区，不把单条消息的
        broker RTT 挂到请求链路上；后台投递失败经 errback 记日志。
        """
        if not settings.ENABLE_KAFKA:
            KAFKA_PUBLISH.labels(topic=topic, result="disabled").inc()
            return False

        producer = await self._get_producer()
        if producer is None:
            KAFKA_PUBLISH.labels(topic=topic, result="degraded").inc()
            return False  # 建连失败已告警

        hdrs = {"request_id": get_request_id()}
        if headers:
            hdrs.update(headers)
        kafka_headers = [
            (k, v.encode("utf-8") if isinstance(v, str) else v) for k, v in hdrs.items()
        ]

        try:
            # aiokafka 的 send() 本身是协程（等元数据+入批，但不把 broker ACK RTT
            # 挂到调用方）；用后台任务托管，失败仅经回调告警，不阻断当前请求。
            task = asyncio.ensure_future(
                producer.send(topic, value=value, key=key, headers=kafka_headers)
            )
            self._inflight.add(task)
            task.add_done_callback(
                lambda t, tp=topic: self._on_send_done(t, tp)
            )
            KAFKA_PUBLISH.labels(topic=topic, result="enqueued").inc()
            return True
        except Exception as e:
            self._last_error = f"{type(e).__name__}: {e}"
            logger.warning("[kafka] 入队失败，已降级 topic=%s：%s", topic, e)
            KAFKA_PUBLISH.labels(topic=topic, result="degraded").inc()
            return False

    def _on_send_done(self, task: asyncio.Future, topic: str) -> None:
        self._inflight.discard(task)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("[kafka] 后台投递失败 topic=%s：%s", topic, exc)

    # ---------------- 生命周期 / 状态 ----------------

    async def close(self) -> None:
        """优雅停机：flush 在途消息后关闭（仅在真正建连过时执行）。"""
        self._closed = True
        producer, self._producer = self._producer, None
        if producer is None:
            return
        inflight = list(self._inflight)
        try:
            await asyncio.wait_for(producer.stop(), timeout=10)
            logger.info("[kafka] 生产者已优雅关闭")
        except Exception as e:
            logger.warning("[kafka] 关闭异常（忽略）：%s", e)
        # stop() 会 flush 批次，等待包装任务落定，消除未回收任务告警
        if inflight:
            await asyncio.gather(*inflight, return_exceptions=True)

    def status(self) -> dict[str, Any]:
        """供 /readyz（T0.11）与排查使用。"""
        return {
            "enabled": settings.ENABLE_KAFKA,
            "connected": self._producer is not None,
            "bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS,
            "last_error": self._last_error,
        }

    async def readiness(self) -> dict[str, Any]:
        """就绪探针：enabled=true 时触发一次懒连并以 connected 判定；false 免检。"""
        report = self.status()
        report["required"] = bool(report["enabled"])
        if report["enabled"]:
            await self._get_producer()  # warm；失败已内部降级，不抛
            report = self.status()
            report["required"] = True
        return report


def make_consumer(topics: list[str], group_id: str, **kwargs):
    """worker（T0.10）消费者工厂：手动提交 + earliest + JSON 反序列化。

    调用方负责 ``await consumer.start()`` / finally ``await consumer.stop()``。
    """
    from aiokafka import AIOKafkaConsumer

    return AIOKafkaConsumer(
        *topics,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        client_id=settings.KAFKA_CLIENT_ID,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        **kwargs,
    )


# 进程级单例（FastAPI 与未来同进程内组件共用）
event_bus = EventBus()
