"""T3.4 文档异步任务 worker 消费器（``doc-tasks``）。

文档分析入口（``routers/gateway.py::analyze_document``）在 Kafka 开启时把
``{task_id, doc_id, doc_name, path}`` 投递到 ``doc-tasks``；本消费器拉到后驱动
OCR 异步链路（``services/ocr_service.ocr_file``：提交 → 轮询 → 拉取文本），
并把结果回写到任务状态行（``update_task_status`` → 前端可经 ``/api/tasks/{id}`` 轮询）。

与 ``collab`` / ``memory`` 消费器同构：手动提交 + **单条毒消息隔离**（逐条 try/except，
失败重试 ``DOC_MAX_ATTEMPTS`` 次后发 ``doc-tasks-dlq`` 并把任务置 failed 后 ack 本条，
不阻塞后续消息）。broker 不可达退化为仅心跳待命；Kafka 关闭时入口回退旧 ``enqueue_task``。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from ...core.config import settings
from ...core.events import event_bus, make_consumer
from ...core.metrics import DOC_TASK, KAFKA_CONSUMER_MESSAGES, record_kafka_lag

logger = logging.getLogger(__name__)

DOC_GROUP_ID = "legalmind-worker-doc"

# 与 routers/gateway.py 的 DOCUMENTS_PREFIX 保持一致：仅当 payload 未带 path 时回查用
DOCS_PREFIX = "legalmind:docs:"

# 回写到任务状态行的文本预览上限（避免把整篇 OCR 正文塞进 Redis hash）
RESULT_PREVIEW_MAX = 2000

ConsumerFactory = Callable[..., Any]
OcrRunner = Callable[[str], Awaitable[str]]
StatusWriter = Callable[..., Awaitable[Any]]


async def _publish_dlq(payload: Any, error: Optional[Exception]) -> None:
    """重试耗尽的消息转入 ``doc-tasks-dlq``（DLQ 发布失败仅告警，不阻断消费循环）。"""
    body = {
        **(payload if isinstance(payload, dict) else {}),
        "attempts": settings.DOC_MAX_ATTEMPTS,
        "error": {
            "type": type(error).__name__ if error else "UnknownError",
            "message": str(error) if error else "",
        },
    }
    try:
        await event_bus.publish(
            settings.KAFKA_TOPIC_DOC_DLQ, body, key=str(body.get("doc_id") or "")
        )
    except Exception as e:  # fail-open
        logger.warning("[doc-consumer] DLQ 发布失败（忽略）：%s", e)


async def run_ocr_chain(file_path: str) -> str:
    """默认 OCR 执行器：委托 ``ocr_service.ocr_file``（失败返回空串，不抛）。"""
    from ...services.ocr_service import ocr_file

    return await ocr_file(file_path)


async def _default_status_writer(
    task_id: str, status: str, *, result: Optional[str] = None, error: Optional[str] = None
) -> None:
    """默认状态回写：更新任务状态行 + 追加 SSE 事件流（异常仅告警，fail-open）。"""
    from ...core.redis_client import update_task_status

    try:
        await update_task_status(task_id, status, progress="100" if status == "completed" else None,
                                 result=result, error=error)
    except Exception as e:  # pragma: no cover - 回写失败不影响消费循环
        logger.warning("[doc-consumer] 状态回写失败 task=%s：%s", task_id, e)


async def _resolve_file_path(payload: dict) -> Optional[str]:
    """解析待 OCR 文件路径：优先 payload.path；缺则回查 Redis 文档元信息（fail-open）。"""
    path = payload.get("path")
    if path:
        return path
    doc_id = payload.get("doc_id")
    if not doc_id:
        return None
    try:
        from ...core.redis_client import get_redis

        data = await get_redis().hgetall(f"{DOCS_PREFIX}{doc_id}")
        return (data or {}).get("path") or None
    except Exception as e:
        logger.warning("[doc-consumer] 文档路径回查失败 doc=%s：%s", doc_id, e)
        return None


async def handle_doc_message(
    payload: Any,
    *,
    ocr_runner: Optional[OcrRunner] = None,
    status_writer: Optional[StatusWriter] = None,
) -> dict[str, Any]:
    """处理一条文档任务：OCR 重试 ``DOC_MAX_ATTEMPTS`` 次；仍失败 → DLQ + 任务置 failed（不阻塞）。"""
    doc = payload if isinstance(payload, dict) else {}
    task_id = doc.get("task_id")
    if not task_id:
        logger.warning("[doc-consumer] 消息缺少 task_id，丢弃：%s", payload)
        DOC_TASK.labels(result="skipped").inc()
        return {"result": "skipped", "reason": "no_task_id"}

    runner = ocr_runner or run_ocr_chain
    writer = status_writer or _default_status_writer

    file_path = await _resolve_file_path(doc)
    if not file_path:
        logger.warning("[doc-consumer] 无法解析文件路径，任务置 failed：%s", payload)
        DOC_TASK.labels(result="failed").inc()
        await _publish_dlq(payload, RuntimeError("doc file path unresolved"))
        await writer(task_id, "failed", error="doc file path unresolved")
        return {"result": "failed", "reason": "no_file_path"}

    last_exc: Optional[Exception] = None
    for attempt in range(1, settings.DOC_MAX_ATTEMPTS + 1):
        try:
            text = await runner(file_path)
            if not (text or "").strip():
                raise RuntimeError("OCR 返回空文本")
            await writer(task_id, "completed", result=(text or "")[:RESULT_PREVIEW_MAX])
            DOC_TASK.labels(result="ok").inc()
            logger.info("[doc-consumer] OCR 完成 task=%s text_len=%d", task_id, len(text or ""))
            return {"result": "ok", "task_id": task_id, "text_len": len(text or "")}
        except asyncio.CancelledError:
            raise
        except Exception as e:
            last_exc = e
            logger.warning(
                "[doc-consumer] OCR 失败 task=%s attempt=%d/%d：%s",
                task_id, attempt, settings.DOC_MAX_ATTEMPTS, e,
            )
            if attempt < settings.DOC_MAX_ATTEMPTS:
                await asyncio.sleep(settings.DOC_RETRY_BACKOFF * attempt)

    DOC_TASK.labels(result="dlq").inc()
    await _publish_dlq(payload, last_exc)
    await writer(task_id, "failed", error=str(last_exc))
    logger.error("[doc-consumer] 重试耗尽进 DLQ task=%s err=%s", task_id, last_exc)
    return {"result": "dlq", "reason": str(last_exc)}


async def consume_doc_tasks(
    stop_event: asyncio.Event,
    *,
    worker_id: str = "doc",
    ocr_runner: Optional[OcrRunner] = None,
    status_writer: Optional[StatusWriter] = None,
    consumer_factory: Optional[ConsumerFactory] = None,
    standby_state: Optional[dict] = None,
    topic: Optional[str] = None,
    group_id: Optional[str] = None,
) -> None:
    """消费 ``doc-tasks`` 并驱动 OCR（手动提交；broker 不可达退化为仅心跳）。"""
    topic = topic or settings.KAFKA_TOPIC_DOC_TASKS
    group_id = group_id or DOC_GROUP_ID
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
            logger.warning("[doc-consumer] 启动失败（仅心跳待命）：%s", e)
            try:
                await asyncio.wait_for(consumer.stop(), timeout=5)
            except Exception as stop_err:
                logger.debug("[doc-consumer] 启动失败后清理异常：%s", stop_err)
            return

        if standby_state is not None:
            standby_state["kafka"] = "consuming"
        logger.info("[doc-consumer] 就绪 topic=%s group=%s", topic, group_id)

        poll_count = 0
        while not stop_event.is_set():
            data = await consumer.getmany(timeout_ms=1000, max_records=10)
            count = 0
            for msgs in data.values():
                for msg in msgs:
                    count += 1
                    payload = getattr(msg, "value", msg)
                    try:
                        await handle_doc_message(
                            payload, ocr_runner=ocr_runner, status_writer=status_writer
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:  # 兜底隔离：一条毒消息不拖垮消费循环
                        logger.warning("[doc-consumer] 消息处理异常（已隔离）：%s", e)
            if count:
                KAFKA_CONSUMER_MESSAGES.labels(group=group_id, topic=topic).inc(count)
                await consumer.commit()
            poll_count += 1
            if poll_count % 10 == 0:
                try:
                    await record_kafka_lag(consumer, group_id)
                except Exception as e:
                    logger.debug("[doc-consumer] lag 探针失败：%s", e)
    finally:
        if started:
            try:
                await consumer.stop()
                logger.info("[doc-consumer] 已停止 topic=%s", topic)
            except Exception as e:
                logger.debug("[doc-consumer] 停止异常：%s", e)
