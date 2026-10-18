"""T0.5 resilience 层单测：重试 / 超时 / 熔断 / 降级 fail-open / 流式首字节前重试。"""
import asyncio
import sys

import httpx
import pytest

sys.path.insert(0, ".")

from app.core import resilience as rz  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.errors import (  # noqa: E402
    CircuitOpenError,
    ErrorCode,
    LLMCallFailedError,
    UpstreamTimeoutError,
)


# ---------- 轻量替身 ----------

class FakeRedis:
    """内存版 Redis hash，供熔断器状态机使用。"""

    def __init__(self, store: dict | None = None):
        self.store = store or {}
        self.hset_calls = 0

    async def hgetall(self, key):
        return dict(self.store.get(key, {}))

    async def hset(self, key, mapping):
        self.store.setdefault(key, {}).update(mapping)
        self.hset_calls += 1

    async def expire(self, key, seconds):
        pass


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://upstream/chat/completions")
    resp = httpx.Response(status_code, request=req)
    return httpx.HTTPStatusError(f"{status_code} error", request=req, response=resp)


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    # 测试中消除退避等待（指数 0 + jitter 0 + 流式 sleep 0）
    monkeypatch.setattr(settings, "RETRY_BASE_DELAY", 0.0)
    monkeypatch.setattr(settings, "LLM_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "LLM_RETRY_DEADLINE", 30.0)


# ---------- is_retryable 分类 ----------

@pytest.mark.parametrize("code", [429, 502, 503, 504])
def test_retryable_status_codes(code):
    assert rz.is_retryable(_http_error(code)) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404, 409])
def test_non_retryable_status_codes(code):
    assert rz.is_retryable(_http_error(code)) is False


def test_retryable_exception_types():
    assert rz.is_retryable(httpx.ConnectError("x")) is True
    assert rz.is_retryable(httpx.ReadTimeout("x")) is True
    assert rz.is_retryable(asyncio.TimeoutError()) is True
    assert rz.is_retryable(ValueError("业务异常")) is False


# ---------- with_resilience：重试/成功/不可重试/超时（关熔断） ----------

@pytest.mark.asyncio
async def test_success_first_attempt_no_retry():
    calls = 0

    async def ok():
        nonlocal calls
        calls += 1
        return {"ok": True}

    result = await rz.with_resilience("svc", ok, use_breaker=False)
    assert result == {"ok": True} and calls == 1


@pytest.mark.asyncio
async def test_retry_then_success():
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ReadTimeout("slow upstream")
        return "done"

    result = await rz.with_resilience("svc", flaky, use_breaker=False)
    assert result == "done" and calls == 3


@pytest.mark.asyncio
async def test_retries_exhausted_50201():
    calls = 0

    async def always_503():
        nonlocal calls
        calls += 1
        raise _http_error(503)

    with pytest.raises(LLMCallFailedError) as ei:
        await rz.with_resilience("svc", always_503, use_breaker=False)
    assert ei.value.code == ErrorCode.LLM_CALL_FAILED.code
    assert ei.value.retryable is True
    assert calls == 4  # 首次 + 3 次重试


@pytest.mark.asyncio
async def test_connect_error_exhausted_50201():
    async def boom():
        raise httpx.ConnectError("connection refused")

    with pytest.raises(LLMCallFailedError):
        await rz.with_resilience("svc", boom, use_breaker=False)


@pytest.mark.asyncio
async def test_non_retryable_400_propagates_raw_single_attempt():
    calls = 0

    async def bad_request():
        nonlocal calls
        calls += 1
        raise _http_error(400)

    with pytest.raises(httpx.HTTPStatusError) as ei:
        await rz.with_resilience("svc", bad_request, use_breaker=False)
    assert ei.value.response.status_code == 400
    assert calls == 1  # 绝不重试


@pytest.mark.asyncio
async def test_timeout_maps_50401():
    async def too_slow():
        await asyncio.sleep(0.3)

    with pytest.raises(UpstreamTimeoutError) as ei:
        await rz.with_resilience("svc", too_slow, timeout=0.05, use_breaker=False)
    assert ei.value.code == ErrorCode.UPSTREAM_TIMEOUT.code
    assert ei.value.retryable is True


# ---------- 熔断器 ----------

@pytest.mark.asyncio
async def test_breaker_open_rejects_call(monkeypatch):
    fake = FakeRedis({
        "legalmind:cb:svc": {
            "state": "OPEN",
            "failure_count": "5",
            "last_failure_time": str(__import__("time").time()),  # 刚打开
        }
    })
    monkeypatch.setattr(rz, "get_redis", lambda: fake)

    async def should_not_run():
        raise AssertionError("熔断打开时不应执行调用")

    with pytest.raises(CircuitOpenError) as ei:
        await rz.with_resilience("svc", should_not_run)
    assert ei.value.code == ErrorCode.CIRCUIT_OPEN.code


@pytest.mark.asyncio
async def test_breaker_fail_open_when_redis_broken(monkeypatch):
    def _raise():
        raise RuntimeError("Redis 未初始化")
    monkeypatch.setattr(rz, "get_redis", _raise)

    async def ok():
        return "proceeded"

    assert await rz.with_resilience("svc", ok) == "proceeded"


@pytest.mark.asyncio
async def test_breaker_opens_after_threshold(monkeypatch):
    monkeypatch.setattr(settings, "CIRCUIT_BREAKER_FAILURE_THRESHOLD", 2)
    monkeypatch.setattr(settings, "CIRCUIT_BREAKER_RECOVERY_TIMEOUT", 30)
    fake = FakeRedis()
    monkeypatch.setattr(rz, "get_redis", lambda: fake)

    async def always_502():
        raise _http_error(502)

    for _ in range(2):
        with pytest.raises(LLMCallFailedError):
            await rz.with_resilience("svc", always_502)

    state = fake.store["legalmind:cb:svc"]
    assert state["state"] == "OPEN" and state["failure_count"] == "2"

    # 第 3 次调用被直接拒绝
    with pytest.raises(CircuitOpenError):
        await rz.with_resilience("svc", always_502)


@pytest.mark.asyncio
async def test_breaker_open_to_half_open_after_recovery(monkeypatch):
    import time as _t
    old_time = _t.time() - 999  # 远超 recovery_timeout
    fake = FakeRedis({
        "legalmind:cb:svc": {
            "state": "OPEN",
            "failure_count": "5",
            "last_failure_time": str(old_time),
        }
    })
    monkeypatch.setattr(rz, "get_redis", lambda: fake)

    async def ok():
        return "trial-pass"

    # 恢复窗口已过：OPEN 自动转 HALF_OPEN 并试探放行
    assert await rz.with_resilience("svc", ok) == "trial-pass"
    assert fake.store["legalmind:cb:svc"]["state"] == "HALF_OPEN"


# ---------- 流式：仅首字节前重试 ----------

def _mock_stream_response(raise_for_status_side=None, status_code=200):
    from unittest.mock import AsyncMock, MagicMock
    resp = MagicMock()
    resp.status_code = status_code
    if raise_for_status_side is not None:
        resp.raise_for_status = MagicMock(side_effect=raise_for_status_side)
    else:
        resp.raise_for_status = MagicMock()
    resp.aclose = AsyncMock()
    return resp


class _FakeStreamCM:
    """模拟 httpx client.stream() 返回的异步上下文管理器。"""

    def __init__(self, resp):
        self.resp = resp
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self.resp

    async def __aexit__(self, *exc):
        self.exited = True
        await self.resp.aclose()
        return False


@pytest.mark.asyncio
async def test_stream_retry_before_first_byte(monkeypatch):
    monkeypatch.setattr(rz, "get_redis", lambda: FakeRedis())
    from unittest.mock import MagicMock

    cm1, cm2, cm3 = (_FakeStreamCM(_mock_stream_response(_http_error(503))),
                     _FakeStreamCM(_mock_stream_response(_http_error(503))),
                     _FakeStreamCM(_mock_stream_response()))
    opener = MagicMock(side_effect=[cm1, cm2, cm3])

    cm, resp = await rz.open_resilient_stream("svc", opener, use_breaker=True)
    assert resp is cm3.resp and cm is cm3 and opener.call_count == 3
    # 失败尝试的上下文已退出（响应关闭，无连接泄漏）
    assert cm1.exited and cm2.exited and not cm3.exited
    cm3.resp.aclose.assert_not_awaited()  # 成功流交给调用方迭代后退出


@pytest.mark.asyncio
async def test_stream_non_retryable_400_single_attempt(monkeypatch):
    monkeypatch.setattr(rz, "get_redis", lambda: FakeRedis())
    from unittest.mock import MagicMock

    cm1 = _FakeStreamCM(_mock_stream_response(_http_error(400), status_code=400))
    opener = MagicMock(side_effect=[cm1])

    with pytest.raises(httpx.HTTPStatusError):
        await rz.open_resilient_stream("svc", opener)
    assert opener.call_count == 1
    assert cm1.exited  # 400 响应已关闭


@pytest.mark.asyncio
async def test_stream_success_returns_open_response(monkeypatch):
    monkeypatch.setattr(rz, "get_redis", lambda: FakeRedis())
    from unittest.mock import MagicMock

    cm1 = _FakeStreamCM(_mock_stream_response())
    opener = MagicMock(return_value=cm1)

    cm, resp = await rz.open_resilient_stream("svc", opener)
    assert resp is cm1.resp and cm is cm1
    assert cm1.entered and not cm1.exited
    # 调用方迭代结束后退出上下文 → 响应被关闭
    await cm.__aexit__(None, None, None)
    cm1.resp.aclose.assert_awaited_once()
