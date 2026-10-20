"""T0.12 旧端点信封中间件 + SSE error 统一形状单测（不依赖真实服务）。"""
import json
import sys

import pytest
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from pydantic import BaseModel

sys.path.insert(0, ".")

from app.core.errors import ErrorCode
from app.core.logging import RequestContextMiddleware
from app.core.response import (
    LegacyEnvelopeMiddleware,
    register_exception_handlers,
    sse_error_event,
)

pytestmark = pytest.mark.asyncio


# ---------- 裸 ASGI 驱动 ----------

def _json_app(status=200, body=None, content_type="application/json"):
    payload = json.dumps(body if body is not None else {}).encode()

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", content_type.encode())]})
        await send({"type": "http.response.body", "body": payload})
    return app


def _text_app(status=500, text="Internal Server Error"):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": text.encode()})
    return app


def _sse_app():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")]})
        await send({"type": "http.response.body",
                    "body": b'event: error\ndata: {"x":1}\n\n', "more_body": True})
        await send({"type": "http.response.body", "body": b""})
    return app


def _chunked_json_app():
    """多分片 JSON 响应（验证缓冲拼接）。"""
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"foo":', "more_body": True})
        await send({"type": "http.response.body", "body": b"1}"})
    return app


async def _drive(app, path="/api/tasks/x", method="GET", headers=None,
                 raise_app_exceptions=None):
    import httpx
    kwargs = {"app": app}
    if raise_app_exceptions is not None:
        kwargs["raise_app_exceptions"] = raise_app_exceptions
    transport = httpx.ASGITransport(**kwargs)
    async with httpx.AsyncClient(base_url="http://t", transport=transport) as client:
        return await client.request(method, path, headers=headers or {})


async def test_success_payload_sinks_into_data():
    resp = await _drive(LegacyEnvelopeMiddleware(_json_app(200, {"foo": 1, "n": [1, 2]})))
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["message"] == "ok"
    assert body["data"] == {"foo": 1, "n": [1, 2]}
    assert body["request_id"].startswith("req_")


async def test_chunked_json_body_is_buffered_and_wrapped():
    resp = await _drive(LegacyEnvelopeMiddleware(_chunked_json_app()))
    assert resp.json()["data"] == {"foo": 1}


async def test_http_exception_shape_becomes_envelope_status_unchanged():
    resp = await _drive(LegacyEnvelopeMiddleware(
        _json_app(404, {"detail": "任务不存在"})))
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 40004
    assert body["message"] == "任务不存在"
    assert body.get("data") is None
    assert "request_id" in body


async def test_422_validation_errors_keep_status_and_have_field_detail():
    detail = [{"loc": ["body", "name"], "msg": "field required", "type": "value_error"}]
    resp = await _drive(LegacyEnvelopeMiddleware(_json_app(422, {"detail": detail})))
    assert resp.status_code == 422  # HTTP 语义不变
    body = resp.json()
    assert body["code"] == 40001
    assert "name" in body["message"]
    assert body["detail"] == detail


async def test_502_maps_to_llm_code_and_hides_raw_detail():
    resp = await _drive(LegacyEnvelopeMiddleware(
        _json_app(502, {"detail": "connect timeout"})))
    body = resp.json()
    assert resp.status_code == 502
    assert body["code"] == 50201
    assert body["retryable"] is True
    assert body["message"] == "connect timeout"


async def test_plain_text_500_gets_envelope():
    resp = await _drive(LegacyEnvelopeMiddleware(_text_app(500)))
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == 50000
    assert body["request_id"].startswith("req_")


async def test_already_enveloped_body_not_double_wrapped():
    env = {"code": 50301, "message": "熔断中", "request_id": "req_fixed",
           "retryable": True, "detail": None}
    resp = await _drive(LegacyEnvelopeMiddleware(_json_app(503, env)))
    assert resp.json() == env


async def test_sse_stream_passes_through_unwrapped():
    resp = await _drive(LegacyEnvelopeMiddleware(_sse_app()))
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert '{"x":1}' in resp.text
    assert '"code"' not in resp.text


async def test_non_api_path_not_wrapped():
    resp = await _drive(LegacyEnvelopeMiddleware(_json_app(200, {"status": "ok"})),
                        path="/healthz")
    assert resp.json() == {"status": "ok"}


async def test_204_passes_through():
    async def no_content(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})
    resp = await _drive(LegacyEnvelopeMiddleware(no_content))
    assert resp.status_code == 204
    assert resp.content == b""


async def test_incoming_request_id_is_reused():
    app = RequestContextMiddleware(LegacyEnvelopeMiddleware(_json_app(200, {"a": 1})))
    resp = await _drive(app, headers={"X-Request-ID": "req_inbound123"})
    body = resp.json()
    # 信封体 request_id 与 X-Request-ID 响应头一致（计划收口验收点）
    assert body["request_id"] == "req_inbound123"
    assert resp.headers["x-request-id"] == "req_inbound123"


# ---------- FastAPI 集成：异常处理器 → 信封 ----------

def _build_app():
    app = FastAPI()

    class Body(BaseModel):
        name: str

    @app.get("/api/boom-notfound")
    async def not_found():
        raise HTTPException(status_code=404, detail="集成：不存在")

    @app.post("/api/boom-validation")
    async def validation(body: Body):
        return {"ok": True}

    @app.get("/api/boom-valueerror")
    async def value_error():
        raise ValueError("入参值非法")

    @app.get("/api/ok")
    async def ok():
        return {"hello": "world"}

    register_exception_handlers(app)
    return RequestContextMiddleware(LegacyEnvelopeMiddleware(app))


async def test_integration_http_exception_envelope():
    resp = await _drive(_build_app(), "/api/boom-notfound")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 40004 and body["message"] == "集成：不存在"
    assert body["request_id"] == resp.headers["x-request-id"]


async def test_integration_validation_422_envelope():
    transport_app = _build_app()
    import httpx
    transport = httpx.ASGITransport(app=transport_app)
    async with httpx.AsyncClient(base_url="http://t", transport=transport) as client:
        resp = await client.post("/api/boom-validation", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 40001
    assert isinstance(body["detail"], list)


async def test_integration_unexpected_error_is_500_envelope():
    # T0.12 收口：未知异常一律 500/50000（旧 global handler 的
    # ValueError→400 等临时映射已删除，统一 FastAPI 默认语义）。
    # ServerErrorMiddleware 发完响应会按惯例 re-raise（真实 uvicorn 吞掉），
    # ASGITransport 默认会把它抛进测试，这里关闭以观察已发送的响应。
    resp = await _drive(_build_app(), "/api/boom-valueerror",
                        raise_app_exceptions=False)
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == 50000
    assert body["request_id"] == resp.headers["x-request-id"]


async def test_integration_success_and_header_rid():
    resp = await _drive(_build_app(), "/api/ok")
    body = resp.json()
    assert body["data"] == {"hello": "world"}
    assert body["request_id"] == resp.headers["x-request-id"]


# ---------- SSE error 事件 ----------

def test_sse_error_event_unified_shape():
    ev = sse_error_event(ErrorCode.LLM_CALL_FAILED, message="服务暂不可用", detail="boom")
    assert ev["event"] == "error"
    data = json.loads(ev["data"])
    assert data["code"] == 50201
    assert data["message"] == "服务暂不可用"
    assert data["error"] == "boom"          # 兼容旧前端字段
    assert data["detail"] == "boom"
    assert data["retryable"] is True
    assert data["request_id"].startswith("req_")


def test_sse_error_event_defaults_message_from_code():
    data = json.loads(sse_error_event()["data"])
    assert data["code"] == 50201
    assert data["message"] == ErrorCode.LLM_CALL_FAILED.message
    assert data["error"] == data["message"]  # 无 detail 时 error 回落到 message
