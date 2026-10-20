"""T3.4 文档异步任务消费器测试（假消费者/假 OCR/假状态回写，不依赖 Kafka/Redis/PG）。

覆盖：OCR 成功回写 status=completed、缺 task_id 跳过、毒消息重试耗尽进 DLQ 且任务置 failed、
空文本视同失败、文件路径无法解析即失败、消费循环毒消息隔离、broker 不可达退化为仅心跳。
"""
import asyncio
import sys

import pytest

sys.path.insert(0, ".")

from app.core.config import settings
from app.worker.consumers import doc as doc_consumer_mod
from app.worker.consumers.doc import consume_doc_tasks, handle_doc_message

pytestmark = pytest.mark.asyncio


# ============================================================
# 假件
# ============================================================

class FakeMsg:
    def __init__(self, value):
        self.value = value


class FakeConsumer:
    """按批次吐出消息；批次耗尽即置 stop 事件（避免空转）。"""

    def __init__(self, batches, *, start_error=None, stop_event=None, topic="doc-tasks"):
        self._batches = batches
        self._i = 0
        self.commits = 0
        self.started = False
        self.stopped = False
        self._start_error = start_error
        self._stop_event = stop_event
        self._topic = topic

    async def start(self):
        if self._start_error:
            raise self._start_error
        self.started = True

    async def stop(self):
        self.stopped = True

    async def getmany(self, timeout_ms=1000, max_records=10):
        if self._i >= len(self._batches):
            if self._stop_event is not None:
                self._stop_event.set()
            return {}
        batch = self._batches[self._i]
        self._i += 1
        return {f"{self._topic}-0": [FakeMsg(v) for v in batch]}

    async def commit(self):
        self.commits += 1


class RecordingWriter:
    """记录状态回写调用。"""

    def __init__(self):
        self.calls: list[tuple] = []

    async def __call__(self, task_id, status, *, result=None, error=None):
        self.calls.append((task_id, status, result, error))


# ============================================================
# 单条消息处理
# ============================================================

async def test_handle_doc_message_success_writes_completed():
    writer = RecordingWriter()

    async def _runner(path):
        assert path == "/tmp/a.pdf"
        return "合同正文……"

    res = await handle_doc_message(
        {"task_id": "t1", "doc_id": "d1", "path": "/tmp/a.pdf"},
        ocr_runner=_runner, status_writer=writer,
    )
    assert res["result"] == "ok"
    assert writer.calls == [("t1", "completed", "合同正文……", None)]


async def test_handle_doc_message_without_task_id_is_skipped():
    res = await handle_doc_message({"doc_id": "d1"})
    assert res == {"result": "skipped", "reason": "no_task_id"}


async def test_handle_doc_message_retries_then_dlq(monkeypatch):
    monkeypatch.setattr(settings, "DOC_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "DOC_RETRY_BACKOFF", 0.0)
    calls = {"n": 0}
    published: list[tuple[str, dict]] = []
    writer = RecordingWriter()

    async def _boom(path):
        calls["n"] += 1
        raise RuntimeError("ocr api down")

    async def _publish(topic, value, **kw):
        published.append((topic, value))
        return True

    monkeypatch.setattr(doc_consumer_mod.event_bus, "publish", _publish)

    res = await handle_doc_message(
        {"task_id": "t2", "doc_id": "d2", "path": "/tmp/b.png"},
        ocr_runner=_boom, status_writer=writer,
    )
    assert res["result"] == "dlq"
    assert calls["n"] == 2                                   # 重试到上限
    assert published and published[0][0] == settings.KAFKA_TOPIC_DOC_DLQ
    assert published[0][1]["attempts"] == 2
    assert writer.calls[-1][1] == "failed"


async def test_handle_doc_message_empty_text_treated_as_failure(monkeypatch):
    monkeypatch.setattr(settings, "DOC_MAX_ATTEMPTS", 1)
    monkeypatch.setattr(settings, "DOC_RETRY_BACKOFF", 0.0)
    writer = RecordingWriter()

    async def _empty(path):
        return "   "

    async def _noop_publish(*a, **k):
        return True

    monkeypatch.setattr(doc_consumer_mod.event_bus, "publish", _noop_publish)

    res = await handle_doc_message(
        {"task_id": "t3", "doc_id": "d3", "path": "/tmp/c.pdf"},
        ocr_runner=_empty, status_writer=writer,
    )
    assert res["result"] == "dlq"
    assert writer.calls[-1][1] == "failed"


async def test_handle_doc_message_unresolved_path_fails(monkeypatch):
    """无 path 且无 doc_id → 路径无法解析，任务直接置 failed（不空转）。"""
    writer = RecordingWriter()
    published: list[tuple[str, dict]] = []

    async def _publish(topic, value, **kw):
        published.append((topic, value))
        return True

    monkeypatch.setattr(doc_consumer_mod.event_bus, "publish", _publish)

    res = await handle_doc_message({"task_id": "t4"}, status_writer=writer)
    assert res == {"result": "failed", "reason": "no_file_path"}
    assert writer.calls[-1][1] == "failed"
    assert published and published[0][0] == settings.KAFKA_TOPIC_DOC_DLQ


# ============================================================
# 消费循环
# ============================================================

async def test_consume_doc_tasks_dispatches_and_commits(monkeypatch):
    processed: list[str] = []

    async def _handle(payload, **_):
        processed.append(payload.get("task_id"))
        return {"result": "ok"}

    monkeypatch.setattr(doc_consumer_mod, "handle_doc_message", _handle)
    stop = asyncio.Event()
    consumer = FakeConsumer([[{"task_id": "t1"}, {"task_id": "t2"}]], stop_event=stop)
    standby: dict = {}

    await asyncio.wait_for(
        consume_doc_tasks(
            stop, worker_id="w-doc", consumer_factory=lambda *a, **k: consumer,
            standby_state=standby,
        ),
        timeout=2,
    )
    assert processed == ["t1", "t2"]
    assert consumer.commits == 1
    assert consumer.stopped and standby["kafka"] == "consuming"


async def test_consume_doc_tasks_isolates_poison_message(monkeypatch):
    """一条消息处理抛异常，其余仍被处理并提交（不阻塞消费循环）。"""
    seen: list[str] = []

    async def _handle(payload, **_):
        tid = payload.get("task_id")
        seen.append(tid)
        if tid == "bad":
            raise RuntimeError("boom")
        return {"result": "ok"}

    monkeypatch.setattr(doc_consumer_mod, "handle_doc_message", _handle)
    stop = asyncio.Event()
    consumer = FakeConsumer([[{"task_id": "bad"}, {"task_id": "good"}]], stop_event=stop)

    await asyncio.wait_for(
        consume_doc_tasks(stop, worker_id="w", consumer_factory=lambda *a, **k: consumer),
        timeout=2,
    )
    assert seen == ["bad", "good"]
    assert consumer.commits == 1


async def test_consume_doc_tasks_degrades_when_start_fails():
    """broker 不可达：退化为仅心跳，不抛异常、不提交。"""
    stop = asyncio.Event()
    consumer = FakeConsumer([], start_error=ConnectionError("broker down"))
    standby: dict = {}

    await asyncio.wait_for(
        consume_doc_tasks(
            stop, worker_id="w", consumer_factory=lambda *a, **k: consumer,
            standby_state=standby,
        ),
        timeout=2,
    )
    assert standby["kafka"] == "degraded"
    assert consumer.commits == 0
