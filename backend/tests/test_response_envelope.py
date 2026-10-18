"""T0.4 统一信封/错误码/全局处理器单测。

覆盖：
1. ErrorCode 错误码 → HTTP/retryable/文案映射
2. 信封工厂 success/error 形状
3. 新路由（EnvelopeRouter + BizException）走信封
4. 旧路由 HTTPException/422/500 保持 FastAPI 默认形状（T0.12 前零变化）
"""
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

sys.path.insert(0, ".")

from app.core.errors import (  # noqa: E402
    BizException,
    ErrorCode,
    InvalidParamsError,
    LLMCallFailedError,
    NotFoundError,
    RateLimitedError,
    TurnLockConflictError,
)
from app.core.response import (  # noqa: E402
    EnvelopeRouter,
    error,
    register_exception_handlers,
    success,
)


# ---------- 错误码映射 ----------

@pytest.mark.parametrize("ec,code,http,retryable", [
    (ErrorCode.SUCCESS, 0, 200, False),
    (ErrorCode.INVALID_PARAMS, 40001, 400, False),
    (ErrorCode.NOT_FOUND, 40004, 404, False),
    (ErrorCode.CONFLICT, 40009, 409, False),
    (ErrorCode.UNAUTHORIZED, 40101, 401, False),
    (ErrorCode.TOKEN_EXPIRED, 40102, 401, False),
    (ErrorCode.FORBIDDEN, 40301, 403, False),
    (ErrorCode.RATE_LIMITED, 42901, 429, True),
    (ErrorCode.TURN_LOCK_CONFLICT, 50901, 409, True),
    (ErrorCode.INTERNAL_ERROR, 50000, 500, False),
    (ErrorCode.LLM_CALL_FAILED, 50201, 502, True),
    (ErrorCode.CIRCUIT_OPEN, 50301, 503, True),
    (ErrorCode.KAFKA_DEGRADED, 50310, 503, False),
    (ErrorCode.UPSTREAM_TIMEOUT, 50401, 504, True),
])
def test_error_code_mapping(ec, code, http, retryable):
    assert ec.code == code
    assert ec.http_status == http
    assert ec.retryable is retryable
    assert ec.message


def test_biz_exception_carries_envelope_fields():
    exc = LLMCallFailedError(detail="upstream 500")
    assert exc.code == 50201 and exc.http_status == 502
    assert exc.retryable is True and exc.detail == "upstream 500"
    assert exc.message == ErrorCode.LLM_CALL_FAILED.message


def test_envelope_factories_shape():
    ok = success({"id": 1})
    assert set(ok) == {"code", "message", "data", "request_id"}
    assert ok["code"] == 0 and ok["data"] == {"id": 1}
    assert ok["request_id"].startswith("req_")

    err = error(ErrorCode.RATE_LIMITED)
    assert err["code"] == 42901 and err["retryable"] is True
    assert "detail" not in err  # detail 为空时不出现在响应里


# ---------- 迷你应用：新/旧两组路由 ----------

class _Body(BaseModel):
    n: int


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    new = EnvelopeRouter(prefix="/new")

    @new.get("/ok")
    async def new_ok():
        return success({"hello": "world"})

    @new.get("/biz-llm")
    async def new_biz():
        raise LLMCallFailedError(detail="重试3次仍失败")

    @new.get("/biz-lock")
    async def new_lock():
        raise TurnLockConflictError()

    @new.get("/biz-invalid")
    async def new_invalid():
        raise InvalidParamsError("案号格式不正确")

    @new.get("/http-404")
    async def new_http_404():
        raise HTTPException(status_code=404, detail="会话不存在")

    @new.get("/http-429")
    async def new_http_429():
        raise HTTPException(status_code=429, detail="慢一点")

    @new.post("/validate")
    async def new_validate(body: _Body):
        return success(body.model_dump())

    @new.get("/boom")
    async def new_boom():
        raise ValueError("意料之外")

    app.include_router(new)

    # 旧路由：普通 APIRouter，模拟 gateway.py 现状
    from fastapi import APIRouter
    old = APIRouter(prefix="/old")

    @old.get("/http-404")
    async def old_http_404():
        raise HTTPException(status_code=404, detail="文档不存在")

    @old.post("/validate")
    async def old_validate(body: _Body):
        return {"raw": "legacy", "n": body.n}

    @old.get("/boom")
    async def old_boom():
        raise ValueError("legacy boom")

    app.include_router(old)
    return app


@pytest.fixture(scope="module")
def client():
    return TestClient(_build_app(), raise_server_exceptions=False)


# ---------- 新路由：信封 ----------

def test_new_route_success_envelope(client):
    r = client.get("/new/ok")
    assert r.status_code == 200
    b = r.json()
    assert b["code"] == 0 and b["data"] == {"hello": "world"}
    assert b["request_id"].startswith("req_")


def test_new_route_biz_exception_envelope(client):
    r = client.get("/new/biz-llm")
    assert r.status_code == 502
    b = r.json()
    assert b["code"] == 50201 and b["retryable"] is True
    assert b["detail"] == "重试3次仍失败"
    assert b["request_id"].startswith("req_")


def test_new_route_turn_lock_conflict(client):
    r = client.get("/new/biz-lock")
    assert r.status_code == 409
    assert r.json()["code"] == 50901
    assert r.json()["retryable"] is True


def test_new_route_http_exception_mapped_to_envelope(client):
    r = client.get("/new/http-404")
    assert r.status_code == 404
    b = r.json()
    assert b["code"] == 40004 and "会话不存在" in b["detail"]
    assert b["retryable"] is False


def test_new_route_429_retryable(client):
    r = client.get("/new/http-429")
    assert r.status_code == 429 and r.json()["code"] == 42901


def test_new_route_validation_error_envelope(client):
    r = client.post("/new/validate", json={"n": "not-int"})
    assert r.status_code == 400
    b = r.json()
    assert b["code"] == 40001
    assert isinstance(b["detail"], list) and b["detail"]


def test_new_route_unhandled_error_envelope(client):
    r = client.get("/new/boom")
    assert r.status_code == 500
    b = r.json()
    assert b["code"] == 50000 and b["request_id"].startswith("req_")


# ---------- 旧路由：FastAPI 默认形状，零变化 ----------

def test_old_route_http_exception_unchanged(client):
    r = client.get("/old/http-404")
    assert r.status_code == 404
    assert r.json() == {"detail": "文档不存在"}  # 不是信封、无 request_id


def test_old_route_validation_422_unchanged(client):
    r = client.post("/old/validate", json={"n": "x"})
    assert r.status_code == 422
    b = r.json()
    assert set(b) == {"detail"} and isinstance(b["detail"], list)


def test_old_route_unhandled_500_unchanged(client):
    r = client.get("/old/boom")
    assert r.status_code == 500
    # Starlette 默认 500 是纯文本，不含信封 code 字段
    assert "code" not in r.text
