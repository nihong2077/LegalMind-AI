"""T0.6 结构化日志与 X-Request-ID 中间件单测。"""
import io
import json
import logging
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, ".")

from app.core.logging import RequestContextMiddleware, setup_logging  # noqa: E402
from app.core.response import (  # noqa: E402
    EnvelopeRouter,
    get_request_id,
    register_exception_handlers,
    success,
)
from app.core.security import create_access_token  # noqa: E402


def _build_app():
    app = FastAPI()
    register_exception_handlers(app)

    router = EnvelopeRouter()

    @router.get("/ping")
    async def ping():
        # 信封里的 request_id 必须与中间件绑定的一致
        return success({"rid": get_request_id()})

    @router.get("/boom")
    async def boom():
        raise ValueError("炸了")

    app.include_router(router)
    # 与 main.py 一致：request-id 中间件必须在最外层（包住 ServerErrorMiddleware）
    return RequestContextMiddleware(app)


@pytest.fixture(scope="module")
def client():
    return TestClient(_build_app())


@pytest.fixture
def capture_access_log():
    """把 root handler 的输出临时重定向到 StringIO，解析所有 JSON 日志行。"""
    setup_logging()
    root = logging.getLogger()
    handler = root.handlers[0]
    stream = io.StringIO()
    old_stream = handler.stream
    handler.stream = stream
    try:
        yield stream
    finally:
        handler.stream = old_stream


def _json_lines(stream: io.StringIO) -> list[dict]:
    out = []
    for line in stream.getvalue().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))  # 每行必须是合法 JSON
    return out


# ---------- request id 生成 / 透传 / 回显 ----------

def test_generated_request_id_when_absent(client):
    r = client.get("/ping")
    rid = r.headers.get("x-request-id")
    assert rid and rid.startswith("req_") and len(rid) == 16
    body = r.json()
    assert body["request_id"] == rid          # 信封
    assert body["data"]["rid"] == rid         # contextvar
    assert body["code"] == 0


def test_inbound_request_id_is_echoed(client):
    r = client.get("/ping", headers={"X-Request-ID": "req_trace_abc12345"})
    assert r.headers["x-request-id"] == "req_trace_abc12345"
    assert r.json()["request_id"] == "req_trace_abc12345"


@pytest.mark.parametrize("bad", [
    "abc",                      # 过短
    "req_with\nnewline",        # 日志注入：换行
    "req with space",           # 非法字符
    "x" * 65,                   # 超长
])
def test_malicious_request_id_is_replaced(client, bad):
    r = client.get("/ping", headers={"X-Request-ID": bad})
    rid = r.headers["x-request-id"]
    assert rid.startswith("req_") and rid != bad
    assert "\n" not in rid


def test_request_id_unique_per_request(client):
    r1 = client.get("/ping")
    r2 = client.get("/ping")
    assert r1.headers["x-request-id"] != r2.headers["x-request-id"]


# ---------- 错误响应也带 request id ----------

def test_request_id_header_present_on_error():
    # 未捕获异常：ServerErrorMiddleware 发出 500 后仍 re-raise（供服务器记录），
    # TestClient 默认会把它转成客户端异常，这里显式取真实 500 响应。
    c = TestClient(_build_app(), raise_server_exceptions=False)
    r = c.get("/boom", headers={"X-Request-ID": "req_err_trace_01"})
    assert r.status_code == 500
    assert r.headers["x-request-id"] == "req_err_trace_01"
    assert r.json()["request_id"] == "req_err_trace_01"


# ---------- user_id 尽力解析（不影响鉴权） ----------

def test_user_id_bound_from_jwt(client, capture_access_log):
    token = create_access_token({"sub": "user42", "username": "tester"})
    client.get("/ping", headers={"Authorization": f"Bearer {token}"})
    rows = _json_lines(capture_access_log)
    access = [r for r in rows if r.get("event") == "http.request"]
    assert access and access[-1]["user_id"] == "user42"


def test_anonymous_request_user_id_none(client, capture_access_log):
    client.get("/ping")
    rows = _json_lines(capture_access_log)
    access = [r for r in rows if r.get("event") == "http.request"]
    assert access and access[-1].get("user_id") is None


def test_garbage_token_does_not_break_request(client, capture_access_log):
    r = client.get("/ping", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 200  # 该端点本就不鉴权；日志解析失败被静默
    rows = _json_lines(capture_access_log)
    assert any(x.get("event") == "http.request" for x in rows)


# ---------- 结构化访问日志字段 ----------

def test_access_log_is_json_with_required_fields(client, capture_access_log):
    client.get("/ping", headers={"X-Request-ID": "req_field_test_1"})
    rows = _json_lines(capture_access_log)
    a = next(r for r in rows if r.get("event") == "http.request")
    assert a["request_id"] == "req_field_test_1"
    assert a["method"] == "GET"
    assert a["route"] == "/ping"
    assert a["status"] == 200
    assert isinstance(a["latency_ms"], (int, float)) and a["latency_ms"] >= 0
    assert "timestamp" in a and a.get("level") == "info"


def test_stdlib_logger_bridged_to_json_with_request_id(capture_access_log):
    """现有代码用的 stdlib logger 也必须输出 JSON 并自动合并 request_id。"""
    import structlog
    structlog.contextvars.bind_contextvars(request_id="req_bridge_9")
    logging.getLogger("some.legacy.module").warning("旧模块日志 %s", "ok")
    structlog.contextvars.clear_contextvars()

    rows = _json_lines(capture_access_log)
    row = next(r for r in rows if r.get("event", "").startswith("旧模块日志"))
    assert row["request_id"] == "req_bridge_9"
    assert row["logger"] == "some.legacy.module"
