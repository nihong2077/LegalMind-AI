"""
韧性层（Harness §7.2）：重试 / 超时 / 熔断 / 降级 / 指标，统一外部调用入口。

- 重试：tenacity 异步，指数退避 0.5s→1s→2s + 随机抖动；默认重试 3 次；
  仅对 429/502/503/504、连接错误、超时重试；总预算 30s。
- 超时：connect 5s（httpx client 内置）、普通读 30s、LLM 流式读 120s（可配置）。
- 熔断：RedisCircuitBreaker 按服务名隔离（litellm / llm_deepseek / local_model / ocr / qdrant），
  状态存 Redis（沿用 legalmind:cb:{name} 键与字段，与旧 gateway 实现完全兼容）。
- 降级：熔断/Redis 故障时 fail-open（不因熔断基础设施故障阻断业务），
  全失败时抛携带错误码的 BizException，而非裸 500。
"""
from __future__ import annotations

import asyncio
import enum
import inspect
import logging
import time
from typing import Any, Awaitable, Callable, Optional, TypeVar

import httpx
from prometheus_client import Counter, Gauge
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_base,
    stop_after_attempt,
    stop_after_delay,
)
from tenacity.wait import wait_base

from .config import settings
from .errors import (
    BizException,
    CircuitOpenError,
    LLMCallFailedError,
    RateLimitedError,
    UpstreamTimeoutError,
)
from .redis_client import get_redis

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ============================================================
# Prometheus 指标（T0.11 补 /metrics 聚合，此处先埋点）
# ============================================================

RETRY_TOTAL = Counter(
    "retry_total",
    "外部调用重试次数",
    labelnames=("service", "attempt"),
)
CIRCUIT_REJECTED_TOTAL = Counter(
    "circuit_rejected_total",
    "熔断器打开直接拒绝的调用次数",
    labelnames=("service",),
)
CIRCUIT_STATE = Gauge(
    "circuit_breaker_state",
    "熔断器状态（0=CLOSED, 1=HALF_OPEN, 2=OPEN）",
    labelnames=("service",),
)


# ============================================================
# 熔断器（自 gateway.py 迁入，Redis 键/字段保持兼容）
# ============================================================

CIRCUIT_BREAKER_PREFIX = "legalmind:cb:"


class CircuitState(str, enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


_STATE_NUM = {
    CircuitState.CLOSED: 0,
    CircuitState.HALF_OPEN: 1,
    CircuitState.OPEN: 2,
}


class RedisCircuitBreaker:
    def __init__(
        self,
        name: str = "default",
        failure_threshold: Optional[int] = None,
        recovery_timeout: Optional[int] = None,
        half_open_max: Optional[int] = None,
    ):
        self.name = name
        self.failure_threshold = (
            failure_threshold
            if failure_threshold is not None
            else settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD
        )
        self.recovery_timeout = (
            recovery_timeout
            if recovery_timeout is not None
            else settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT
        )
        self.half_open_max = (
            half_open_max
            if half_open_max is not None
            else settings.CIRCUIT_BREAKER_HALF_OPEN_MAX
        )

    def _key(self) -> str:
        return f"{CIRCUIT_BREAKER_PREFIX}{self.name}"

    def _observe(self, state: CircuitState) -> None:
        CIRCUIT_STATE.labels(service=self.name).set(_STATE_NUM[state])

    async def _get_state(self) -> dict:
        r = get_redis()
        data = await r.hgetall(self._key())
        if not data:
            return {
                "state": CircuitState.CLOSED.value,
                "failure_count": "0",
                "last_failure_time": "",
                "half_open_success": "0",
            }
        return data

    async def _set_state(self, updates: dict) -> None:
        r = get_redis()
        await r.hset(self._key(), mapping=updates)
        await r.expire(self._key(), self.recovery_timeout * 3)

    async def get_current_state(self) -> CircuitState:
        data = await self._get_state()
        current = CircuitState(data.get("state", CircuitState.CLOSED.value))
        if current == CircuitState.OPEN:
            last_failure = float(data.get("last_failure_time") or "0")
            if time.time() - last_failure >= self.recovery_timeout:
                await self._set_state({
                    "state": CircuitState.HALF_OPEN.value,
                    "half_open_success": "0",
                })
                current = CircuitState.HALF_OPEN
                logger.info("[熔断:%s] OPEN -> HALF_OPEN（试探放行）", self.name)
        self._observe(current)
        return current

    async def record_success(self) -> None:
        data = await self._get_state()
        current = CircuitState(data.get("state", CircuitState.CLOSED.value))
        if current == CircuitState.HALF_OPEN:
            half_open = int(data.get("half_open_success", "0")) + 1
            if half_open >= self.half_open_max:
                await self._set_state({
                    "state": CircuitState.CLOSED.value,
                    "failure_count": "0",
                    "half_open_success": "0",
                })
                logger.info("[熔断:%s] HALF_OPEN -> CLOSED（恢复）", self.name)
            else:
                await self._set_state({"half_open_success": str(half_open)})
        else:
            await self._set_state({"failure_count": "0"})
        self._observe(CircuitState.CLOSED)

    async def record_failure(self) -> None:
        data = await self._get_state()
        prev_state = CircuitState(data.get("state", CircuitState.CLOSED.value))
        failure_count = int(data.get("failure_count", "0")) + 1
        updates = {
            "failure_count": str(failure_count),
            "last_failure_time": str(time.time()),
        }
        opened = (
            prev_state != CircuitState.OPEN
            and failure_count >= self.failure_threshold
        )
        if opened:
            updates["state"] = CircuitState.OPEN.value
        await self._set_state(updates)
        self._observe(CircuitState.OPEN if opened or prev_state == CircuitState.OPEN
                      else CircuitState.HALF_OPEN
                      if prev_state == CircuitState.HALF_OPEN
                      else CircuitState.CLOSED)
        if opened:
            logger.warning("[熔断:%s] 连续失败 %d 次，熔断打开", self.name, failure_count)

    async def is_available(self) -> bool:
        state = await self.get_current_state()
        return state != CircuitState.OPEN

    async def reset(self) -> None:
        await self._set_state({
            "state": CircuitState.CLOSED.value,
            "failure_count": "0",
            "last_failure_time": "",
            "half_open_success": "0",
        })
        self._observe(CircuitState.CLOSED)


# ============================================================
# 可重试性分类（429/502/503/504 + 连接错误/超时）
# ============================================================

RETRYABLE_STATUS = {429, 502, 503, 504}

# 业务错误（携带明确错误码，如 400/401/404/409）绝不重试
_RETRYABLE_EXC_TYPES: tuple = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
    asyncio.TimeoutError,
)


def is_retryable(exc: BaseException) -> bool:
    """判断一次调用失败是否值得重试。"""
    if isinstance(exc, BizException):
        # 仅明确标记 retryable 的业务错误（如上游超时/LLM 失败）才重试
        return bool(getattr(exc, "retryable", False))
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS
    if isinstance(exc, httpx.TimeoutException):
        return True
    # 连接建立/传输中断类（ReadError/WriteError/CloseError 均属 NetworkError）
    if isinstance(exc, (httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    # UnsupportedProtocol / LocalProtocolError 等属客户端配置 bug，不重试
    return isinstance(exc, _RETRYABLE_EXC_TYPES)


class _RetryablePredicate(retry_base):
    """tenacity 谓词：仅当 is_retryable(exc) 为真时重试。"""

    def __call__(self, retry_state: RetryCallState) -> bool:
        exc = retry_state.outcome.exception()
        if exc is None:
            return False
        return is_retryable(exc)


class _JitterWait(wait_base):
    """指数退避 0.5→1→2s 后叠加最多 25% 的随机抖动。"""

    def __call__(self, retry_state: RetryCallState) -> float:
        attempt = max(1, retry_state.attempt_number)
        base = settings.RETRY_BASE_DELAY * (2 ** (attempt - 1))  # 0.5, 1.0, 2.0
        import random
        return base + random.uniform(0, base * 0.25)


def _after_retry(service: str) -> Callable[[RetryCallState], None]:
    def _log(retry_state: RetryCallState) -> None:
        # attempt_number=1 是首次调用失败（还没发生重试），不计 retry 指标/日志
        if retry_state.attempt_number <= 1:
            return
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        retry_no = retry_state.attempt_number - 1
        RETRY_TOTAL.labels(service=service, attempt=str(retry_no)).inc()
        logger.warning(
            "[重试:%s] 第 %d/%d 次重试失败：%s",
            service, retry_no, settings.LLM_RETRY_ATTEMPTS,
            type(exc).__name__ if exc else "?",
        )
    return _log


# ============================================================
# 高层入口：熔断 → 超时 → 重试
# ============================================================

async def with_resilience(
    service: str,
    func: Callable[..., Awaitable[T]],
    *args: Any,
    timeout: float = settings.LLM_CALL_TIMEOUT,
    use_breaker: bool = True,
    **kwargs: Any,
) -> T:
    """以熔断+超时+重试策略执行一次外部异步调用。

    - 熔断打开：抛 CircuitOpenError(50301)；熔断器自身故障（如 Redis 挂）fail-open
    - 超时：asyncio.wait_for，抛 UpstreamTimeoutError(50401)
    - 重试耗尽：抛 LLMCallFailedError(50201) / RateLimitedError(42901) 等
    - 非可重试错误（400/401/404/409 等）：原样向上抛，不重试、不计熔断失败
    """
    breaker = RedisCircuitBreaker(name=service) if use_breaker else None

    if breaker is not None:
        try:
            available = await breaker.is_available()
        except Exception as e:  # Redis 故障：fail-open，不阻断
            logger.warning("[熔断:%s] 状态读取失败，fail-open 放行：%s", service, e)
            available = True
        if not available:
            CIRCUIT_REJECTED_TOTAL.labels(service=service).inc()
            raise CircuitOpenError(detail=f"service={service}")

    async def _attempt() -> T:
        return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)

    retrying = AsyncRetrying(
        stop=(
            stop_after_attempt(settings.LLM_RETRY_ATTEMPTS + 1)
            if settings.LLM_RETRY_ATTEMPTS > 0
            else stop_after_attempt(1)
        ),
        wait=_JitterWait(),
        retry=_RetryablePredicate(),
        after=_after_retry(service),
        reraise=True,
    )
    # 总预算：与 attempt 上限同时生效，先到先止
    if settings.LLM_RETRY_DEADLINE > 0:
        retrying.stop = retrying.stop | stop_after_delay(settings.LLM_RETRY_DEADLINE)

    try:
        result = await retrying(_attempt)
    except (asyncio.TimeoutError, httpx.TimeoutException) as e:
        await _safe_record_failure(breaker, service)
        raise UpstreamTimeoutError(
            detail=f"service={service}: {type(e).__name__}") from e
    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        if status_code not in RETRYABLE_STATUS and status_code != 429:
            # 400/401/403/404/409 等客户端错误：不重试、不计熔断失败，原样抛
            raise
        await _safe_record_failure(breaker, service)
        if status_code == 429:
            raise RateLimitedError(detail=f"service={service} 限流") from e
        raise LLMCallFailedError(
            detail=f"service={service} HTTP {status_code}") from e
    except _RETRYABLE_EXC_TYPES as e:
        await _safe_record_failure(breaker, service)
        raise LLMCallFailedError(
            detail=f"service={service}: {type(e).__name__}") from e
    except httpx.TransportError as e:
        # ReadError/WriteError/CloseError 等其余传输错误：
        # 可重试类已在 tenacity 内重试完，此处统一转 BizException 并计熔断；
        # 配置类错误（UnsupportedProtocol/LocalProtocolError）原样抛。
        if not is_retryable(e):
            raise
        await _safe_record_failure(breaker, service)
        raise LLMCallFailedError(
            detail=f"service={service}: {type(e).__name__}") from e

    await _safe_record_success(breaker, service)
    return result


async def _safe_record_failure(breaker: Optional[RedisCircuitBreaker], service: str) -> None:
    if breaker is None:
        return
    try:
        await breaker.record_failure()
    except Exception as e:  # Redis 故障不掩盖原始业务异常
        logger.warning("[熔断:%s] record_failure 失败（忽略）：%s", service, e)


async def _safe_record_success(breaker: Optional[RedisCircuitBreaker], service: str) -> None:
    if breaker is None:
        return
    try:
        await breaker.record_success()
    except Exception as e:
        logger.warning("[熔断:%s] record_success 失败（忽略）：%s", service, e)


# ============================================================
# 流式调用：仅"首字节前"可重试；进入迭代后不再重试
# ============================================================

async def _exit_stream_cm(service: str, cm: Any) -> None:
    """关闭流式上下文管理器；关闭异常只 debug，绝不掩盖主异常。"""
    if cm is None:
        return
    try:
        await cm.__aexit__(None, None, None)
    except Exception as e:
        logger.debug("[流式:%s] 关闭上下文失败（忽略）：%s", service, e)


async def open_resilient_stream(
    service: str,
    opener: Callable[[], Any],
    *,
    timeout: float = settings.LLM_STREAM_CONNECT_TIMEOUT,
    use_breaker: bool = True,
) -> tuple[Any, httpx.Response]:
    """打开一个 SSE/分块流式响应，仅在拿到响应头之前应用熔断/超时/重试。

    ``opener`` 每次调用返回一个**未进入**的 httpx 流式异步上下文管理器
    （即 ``client.stream("POST", url, json=...)``；允许返回该对象或其 awaitable）。
    本函数负责进入并在失败/重试时退出；成功时返回 ``(cm, response)``，
    **调用方迭代结束后必须** ``await cm.__aexit__(None, None, None)``。

    注意：不能只取 ``await cm.__aenter__()`` 的响应而丢弃 cm——
    上下文管理器被 GC 会立即关闭底层流（"stream has been closed"）。
    """
    breaker = RedisCircuitBreaker(name=service) if use_breaker else None

    if breaker is not None:
        try:
            available = await breaker.is_available()
        except Exception as e:
            logger.warning("[熔断:%s] 状态读取失败，fail-open：%s", service, e)
            available = True
        if not available:
            CIRCUIT_REJECTED_TOTAL.labels(service=service).inc()
            raise CircuitOpenError(detail=f"service={service}")

    last_exc: Optional[BaseException] = None
    stream_start = time.monotonic()
    deadline = settings.LLM_RETRY_DEADLINE if settings.LLM_RETRY_DEADLINE > 0 else 0.0
    for attempt in range(1, settings.LLM_RETRY_ATTEMPTS + 2):
        # 总预算先到先止（与 with_resilience 的 30s 口径一致）
        if deadline and time.monotonic() - stream_start >= deadline:
            await _safe_record_failure(breaker, service)
            raise UpstreamTimeoutError(
                detail=f"service={service}: stream connect deadline "
                       f"{deadline}s exhausted") from last_exc
        cm: Any = None
        response: Optional[httpx.Response] = None
        entered = False
        try:
            cm = opener()
            if inspect.isawaitable(cm):
                cm = await cm
            response = await asyncio.wait_for(cm.__aenter__(), timeout=timeout)
            entered = True
            # raise_for_status 发生在首字节前——仍可安全重试
            response.raise_for_status()
            await _safe_record_success(breaker, service)
            return cm, response
        except (asyncio.TimeoutError, httpx.TimeoutException) as e:
            last_exc = e
            if entered:
                await _exit_stream_cm(service, cm)
            if not is_retryable(e) or attempt > settings.LLM_RETRY_ATTEMPTS:
                await _safe_record_failure(breaker, service)
                raise UpstreamTimeoutError(
                    detail=f"service={service}: {type(e).__name__}") from e
        except httpx.HTTPStatusError as e:
            last_exc = e
            if entered:
                await _exit_stream_cm(service, cm)
            # 非可重试 4xx：原样抛，不重试、不计熔断失败
            if not is_retryable(e):
                raise
            if attempt > settings.LLM_RETRY_ATTEMPTS:
                await _safe_record_failure(breaker, service)
                if e.response.status_code == 429:
                    raise RateLimitedError(detail=f"service={service} 限流") from e
                raise LLMCallFailedError(
                    detail=f"service={service} HTTP {e.response.status_code}") from e
        except httpx.TransportError as e:
            # ReadError/WriteError/CloseError 等传输中断
            last_exc = e
            if entered:
                await _exit_stream_cm(service, cm)
            if not is_retryable(e):
                raise
            if attempt > settings.LLM_RETRY_ATTEMPTS:
                await _safe_record_failure(breaker, service)
                raise LLMCallFailedError(
                    detail=f"service={service}: {type(e).__name__}") from e
        RETRY_TOTAL.labels(service=service, attempt=str(attempt)).inc()
        logger.warning("[流式重试:%s] 第 %d 次连接失败：%s",
                       service, attempt, type(last_exc).__name__)
        backoff = settings.RETRY_BASE_DELAY * (2 ** (attempt - 1))
        if deadline:
            remaining = deadline - (time.monotonic() - stream_start)
            backoff = min(backoff, max(0.0, remaining))
        await asyncio.sleep(backoff)

    # 理论不可达（循环内要么 return 要么 raise）
    await _safe_record_failure(breaker, service)
    raise LLMCallFailedError(detail=f"service={service}: 未知重试失败")
