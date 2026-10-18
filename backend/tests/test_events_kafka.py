"""T0.8 Kafka 事件总线单测：fake producer，不依赖真实 broker（计划 §6 风险 5）。"""
import asyncio
import json

import pytest

import sys
sys.path.insert(0, ".")

from app.core import events as events_mod
from app.core.events import EventBus
from app.core.response import request_id_ctx

pytestmark = pytest.mark.asyncio


# ---------- fakes ----------

class FakeProducer:
    """记录调用的 AIOKafkaProducer 替身（aiokafka 的 send 是协程）。"""
    def __init__(self, *, start_raises=None, send_raises=None,
                 start_delay=0.0, **kwargs):
        self.init_kwargs = kwargs
        self.start_raises = start_raises
        self.send_raises = send_raises
        self.start_delay = start_delay
        self.sent = []
        self.stopped = False

    async def start(self):
        if self.start_delay:
            await asyncio.sleep(self.start_delay)
        if self.start_raises:
            raise self.start_raises

    async def send(self, topic, value=None, key=None, headers=None):
        if self.send_raises:
            raise self.send_raises
        self.sent.append({"topic": topic, "value": value, "key": key, "headers": headers})
        return {"topic": topic, "partition": 0, "offset": len(self.sent) - 1}

    async def stop(self):
        self.stopped = True


def make_factory(producer):
    def factory(**kwargs):
        factory.calls += 1
        factory.last_kwargs = kwargs
        return producer
    factory.calls = 0
    factory.last_kwargs = None
    return factory


async def _drain(bus, rounds=10):
    """等待后台 send 任务及其 done_callback 全部落定（两者相隔一个循环迭代）。"""
    for _ in range(rounds):
        await asyncio.sleep(0)
        if not bus._inflight:
            await asyncio.sleep(0)  # callback 在任务完成后的下一迭代触发
            return


@pytest.fixture(autouse=True)
def _kafka_on(monkeypatch):
    monkeypatch.setattr(events_mod.settings, "ENABLE_KAFKA", True)
    monkeypatch.setattr(events_mod.settings, "KAFKA_CONNECT_TIMEOUT", 1.0)
    # request_id 固定可断言
    tok = request_id_ctx.set("req_kafka_test_9")
    yield
    request_id_ctx.reset(tok)


# ---------- 开关 ----------

async def test_publish_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(events_mod.settings, "ENABLE_KAFKA", False)
    factory = make_factory(FakeProducer())
    bus = EventBus(producer_factory=factory)
    assert await bus.publish("t", {"a": 1}) is False
    assert factory.calls == 0
    assert bus.status()["enabled"] is False and bus.status()["connected"] is False


# ---------- 成功路径 ----------

async def test_publish_success_serialization_headers_and_key():
    p = FakeProducer()
    factory = make_factory(p)
    bus = EventBus(producer_factory=factory)

    sent = await bus.publish(
        "collab-turns", {"turn_id": "t1", "中文": "值"}, key="conv_1",
        headers={"agent_id": "host"},
    )
    assert sent is True
    await _drain(bus)

    # 构造参数透传
    assert factory.last_kwargs["bootstrap_servers"] == events_mod.settings.KAFKA_BOOTSTRAP_SERVERS
    assert factory.last_kwargs["client_id"] == "legalmind-backend"

    rec = p.sent[0]
    assert rec["topic"] == "collab-turns"
    assert rec["key"] == "conv_1"

    # 生产环境由真实 producer 用 value_serializer 序列化；这里验证序列化器可用且保留中文
    raw = factory.last_kwargs["value_serializer"](rec["value"])
    assert json.loads(raw.decode())["中文"] == "值"

    # headers：request_id 自动注入 + 自定义 header，值为 utf-8 bytes
    hdrs = dict(rec["headers"])
    assert hdrs["request_id"] == b"req_kafka_test_9"
    assert hdrs["agent_id"] == b"host"

    await bus.close()
    assert p.stopped is True


async def test_lazy_connect_and_reuse():
    p = FakeProducer()
    factory = make_factory(p)
    bus = EventBus(producer_factory=factory)
    assert factory.calls == 0  # 构造时不连
    await bus.publish("t", {"x": 1})
    await bus.publish("t", {"x": 2})
    await _drain(bus)
    assert factory.calls == 1  # 懒连一次，复用连接
    assert len(p.sent) == 2
    await bus.close()


# ---------- 降级（均不得抛异常） ----------

async def test_start_failure_degrades_gracefully():
    p = FakeProducer(start_raises=ConnectionError("broker down"))
    bus = EventBus(producer_factory=make_factory(p))

    r1 = await bus.publish("t", {"x": 1})
    r2 = await bus.publish("t", {"x": 2})  # 失败后不缓存半成品连接
    assert r1 is False and r2 is False
    assert "broker down" in bus.status()["last_error"]
    await bus.close()  # 未建连成功，close 必须安全空操作
    assert p.stopped is False


async def test_connect_timeout_degrades(monkeypatch):
    monkeypatch.setattr(events_mod.settings, "KAFKA_CONNECT_TIMEOUT", 0.05)
    p = FakeProducer(start_delay=0.5)
    bus = EventBus(producer_factory=make_factory(p))
    assert await bus.publish("t", {}) is False
    assert bus.status()["connected"] is False


async def test_background_send_failure_does_not_crash():
    # send 协程内部失败（如 broker reset）：publish 已返回 True，
    # 后台任务回调只记 last_error + 告警，不向调用方抛异常
    p = FakeProducer(send_raises=ConnectionError("reset by peer"))
    bus = EventBus(producer_factory=make_factory(p))
    assert await bus.publish("t", {"x": 1}) is True  # 入队动作本身成功
    await _drain(bus)
    assert "reset by peer" in bus.status()["last_error"]
    await bus.close()  # close 回收失败任务也不抛
    assert p.stopped is True
