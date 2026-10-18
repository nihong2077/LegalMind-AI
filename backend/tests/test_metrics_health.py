"""T0.11 探针与指标单测（ASGI 中间件 + readiness 聚合 + kafka lag，不依赖真实服务）。"""
import sys

import pytest
from prometheus_client import REGISTRY

sys.path.insert(0, ".")

from app.core import health
from app.core.metrics import (
    HTTP_REQUESTS,
    KAFKA_CONSUMER_LAG,
    PrometheusASGIMiddleware,
    record_kafka_lag,
)

pytestmark = pytest.mark.asyncio


# ---------- ASGI 指标中间件 ----------

class _Route:
    def __init__(self, path):
        self.path = path


def _asgi_app(route_path=None, status=200):
    async def app(scope, receive, send):
        if route_path is not None:
            scope["route"] = _Route(route_path)
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"ok"})
    return app


async def _drive(app, path="/api/x/123", method="GET"):
    import httpx
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(base_url="http://t", transport=transport) as client:
        resp = await client.request(method, path)
    return resp


async def test_middleware_records_templated_path_and_status():
    wrapped = PrometheusASGIMiddleware(
        _asgi_app(route_path="/api/x/{id}", status=201)
    )
    resp = await _drive(wrapped, "/api/x/123")
    assert resp.status_code == 201

    value = REGISTRY.get_sample_value(
        "legalmind_http_requests_total",
        {"method": "GET", "path": "/api/x/{id}", "status": "201"},
    )
    assert value is not None and value >= 1
    # 耗时直方图有观测样本
    assert REGISTRY.get_sample_value(
        "legalmind_http_request_duration_seconds_count",
        {"method": "GET", "path": "/api/x/{id}"},
    ) >= 1


async def test_middleware_unmatched_low_cardinality():
    wrapped = PrometheusASGIMiddleware(_asgi_app(route_path=None, status=404))
    await _drive(wrapped, "/this/path/does/not/exist/98765")
    value = REGISTRY.get_sample_value(
        "legalmind_http_requests_total",
        {"method": "GET", "path": "unmatched", "status": "404"},
    )
    assert value is not None and value >= 1


async def test_middleware_excludes_metrics_path():
    seen = {"called": False}

    async def inner(scope, receive, send):
        seen["called"] = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    wrapped = PrometheusASGIMiddleware(inner)
    await _drive(wrapped, "/metrics")
    # 内层出了（排除只影响埋点不影响转发）
    assert seen["called"] is True
    assert REGISTRY.get_sample_value(
        "legalmind_http_requests_total",
        {"method": "GET", "path": "/metrics", "status": "200"},
    ) is None


# ---------- kafka lag ----------

class _TP:
    def __init__(self, topic, partition):
        self.topic = topic
        self.partition = partition

    def __hash__(self):
        return hash((self.topic, self.partition))


class FakeLagConsumer:
    def __init__(self, assignment, end_offsets, positions):
        self._assignment = assignment
        self._end = end_offsets
        self._pos = positions

    def assignment(self):
        return set(self._assignment)

    async def end_offsets(self, partitions):
        return dict(self._end)

    async def position(self, tp):
        return self._pos[tp]


async def test_record_kafka_lag_gauges():
    tp0, tp1 = _TP("collab-turns", 0), _TP("collab-turns", 1)
    consumer = FakeLagConsumer(
        [tp0, tp1],
        {tp0: 10, tp1: 3},
        {tp0: 7, tp1: -1},   # tp1 未定位（-1）→ 按 earliest 全量积压=3
    )
    await record_kafka_lag(consumer, "legalmind-worker-collab")
    assert REGISTRY.get_sample_value(
        "legalmind_kafka_consumer_lag",
        {"group": "legalmind-worker-collab", "topic": "collab-turns", "partition": "0"},
    ) == 3
    assert REGISTRY.get_sample_value(
        "legalmind_kafka_consumer_lag",
        {"group": "legalmind-worker-collab", "topic": "collab-turns", "partition": "1"},
    ) == 3


async def test_record_kafka_lag_empty_assignment_skips():
    class Empty:
        def assignment(self):
            return set()
    await record_kafka_lag(Empty(), "g")  # 不抛即通过


# ---------- readiness_report 聚合 ----------

async def _ok():
    return {"status": "healthy"}


async def _down():
    return {"status": "unhealthy", "error": "boom"}


async def _disabled():
    return {"status": "disabled"}


async def test_readiness_all_healthy(monkeypatch):
    monkeypatch.setattr(health, "check_redis", _ok)
    monkeypatch.setattr(health, "check_postgres", _ok)
    monkeypatch.setattr(health, "check_qdrant", _ok)
    monkeypatch.setattr(health, "check_kafka", _ok)
    report = await health.readiness_report()
    assert report["ready"] is True
    assert set(report["checks"]) == {"redis", "postgres", "qdrant", "kafka"}
    assert report["checks"]["redis"]["latency_ms"] >= 0


async def test_readiness_redis_down_marks_not_ready(monkeypatch):
    monkeypatch.setattr(health, "check_redis", _down)
    monkeypatch.setattr(health, "check_postgres", _ok)
    monkeypatch.setattr(health, "check_qdrant", _ok)
    monkeypatch.setattr(health, "check_kafka", _disabled)
    report = await health.readiness_report()
    assert report["ready"] is False
    assert report["checks"]["redis"]["status"] == "unhealthy"
    assert report["checks"]["kafka"]["status"] == "disabled"  # 不算失败但 redis 挂了


async def test_readiness_kafka_disabled_does_not_block(monkeypatch):
    monkeypatch.setattr(health, "check_redis", _ok)
    monkeypatch.setattr(health, "check_postgres", _ok)
    monkeypatch.setattr(health, "check_qdrant", _ok)
    monkeypatch.setattr(health, "check_kafka", _disabled)
    report = await health.readiness_report()
    assert report["ready"] is True


async def test_readiness_check_exception_is_isolated(monkeypatch):
    async def _raises():
        raise RuntimeError("driver crashed")
    monkeypatch.setattr(health, "check_redis", _raises)
    monkeypatch.setattr(health, "check_postgres", _ok)
    monkeypatch.setattr(health, "check_qdrant", _ok)
    monkeypatch.setattr(health, "check_kafka", _disabled)
    report = await health.readiness_report()  # 不抛异常
    assert report["ready"] is False
    assert "driver crashed" in report["checks"]["redis"]["error"]


async def test_readiness_timeout_marks_unhealthy(monkeypatch):
    async def _slow():
        import asyncio
        await asyncio.sleep(5)
    monkeypatch.setattr(health, "check_redis", _slow)
    monkeypatch.setattr(health, "check_postgres", _ok)
    monkeypatch.setattr(health, "check_qdrant", _ok)
    monkeypatch.setattr(health, "check_kafka", _disabled)
    report = await health.readiness_report()
    assert report["checks"]["redis"]["status"] == "unhealthy"
    assert "timeout" in report["checks"]["redis"]["error"]
    assert report["ready"] is False
