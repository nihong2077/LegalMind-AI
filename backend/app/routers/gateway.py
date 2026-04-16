import asyncio
import functools
import json
import time
from enum import Enum
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sse_starlette.sse import EventSourceResponse

from ..core.config import settings
from ..core.redis_client import (
    enqueue_task,
    generate_task_id,
    get_redis,
    get_stream_events,
    get_task_status,
    update_task_status,
)
from ..core.security import create_access_token, get_current_user

router = APIRouter(prefix="/api", tags=["gateway"])

CIRCUIT_BREAKER_PREFIX = "legalmind:cb:"
SSE_PING_INTERVAL = 15


class SlidingWindowRateLimiter:
    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def is_allowed(self, key: str) -> bool:
        r = get_redis()
        now = time.time()
        window_start = now - self.window_seconds
        pipe = r.pipeline()
        pipe.zremrangebyscore(f"ratelimit:{key}", 0, window_start)
        pipe.zcard(f"ratelimit:{key}")
        pipe.zadd(f"ratelimit:{key}", {str(now): now})
        pipe.expire(f"ratelimit:{key}", self.window_seconds + 1)
        results = await pipe.execute()
        current_count = results[1]
        if current_count >= self.max_requests:
            return False
        return True


rate_limiter = SlidingWindowRateLimiter(
    max_requests=settings.RATE_LIMIT_MAX_REQUESTS,
    window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
)


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class RedisCircuitBreaker:
    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        half_open_max: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max

    def _key(self) -> str:
        return f"{CIRCUIT_BREAKER_PREFIX}{self.name}"

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
                return CircuitState.HALF_OPEN
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
            else:
                await self._set_state({"half_open_success": str(half_open)})
        else:
            await self._set_state({"failure_count": "0"})

    async def record_failure(self) -> None:
        data = await self._get_state()
        failure_count = int(data.get("failure_count", "0")) + 1
        updates = {
            "failure_count": str(failure_count),
            "last_failure_time": str(time.time()),
        }
        if failure_count >= self.failure_threshold:
            updates["state"] = CircuitState.OPEN.value
        await self._set_state(updates)

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


def circuit_protect(name: str = "default", fallback: Optional[Callable] = None):
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            cb = RedisCircuitBreaker(
                name=name,
                failure_threshold=settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                recovery_timeout=settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
                half_open_max=settings.CIRCUIT_BREAKER_HALF_OPEN_MAX,
            )
            if not await cb.is_available():
                if fallback:
                    return await fallback(*args, **kwargs)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"服务 [{name}] 暂时不可用，熔断保护中",
                )
            try:
                result = await func(*args, **kwargs)
                await cb.record_success()
                return result
            except Exception as e:
                await cb.record_failure()
                if fallback:
                    return await fallback(*args, **kwargs)
                raise

        return wrapper

    return decorator


def _build_rate_limit_key(request: Request, user: dict) -> str:
    client_ip = request.client.host if request.client else "unknown"
    user_id = user.get("sub", "anonymous")
    route = request.url.path
    return f"{client_ip}:{user_id}:{route}"


async def check_rate_limit(request: Request, user: dict = Depends(get_current_user)):
    key = _build_rate_limit_key(request, user)
    allowed = await rate_limiter.is_allowed(key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试",
        )
    return user


@router.post("/auth/token")
async def login(username: str = Query(...), password: str = Query(...)):
    if username != "admin" or password != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    token = create_access_token(data={"sub": username})
    return {"access_token": token, "token_type": "bearer"}


@router.post("/tasks")
async def create_task(
    task_type: str,
    payload: dict,
    user: dict = Depends(check_rate_limit),
):
    task_id = generate_task_id()
    result_id = await enqueue_task(task_type=task_type, payload=payload, task_id=task_id)
    return {"task_id": result_id, "status": "pending"}


@router.get("/tasks/{task_id}")
async def query_task_status(
    task_id: str,
    user: dict = Depends(get_current_user),
):
    status_data = await get_task_status(task_id)
    if not status_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    return status_data


@router.get("/stream/{task_id}")
async def stream_task_progress(
    task_id: str,
    request: Request,
    last_event_id: Optional[str] = Query(None, alias="Last-Event-ID"),
    user: dict = Depends(get_current_user),
):
    status_data = await get_task_status(task_id)
    if not status_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )

    start_id = last_event_id or "0"

    async def event_generator():
        current_id = start_id
        last_ping = time.time()

        while True:
            if await request.is_disconnected():
                break

            events = await get_stream_events(task_id, last_id=current_id, count=10, block=3000)

            if events:
                for msg_id, msg in events:
                    current_id = msg_id
                    data = msg.get("data", "{}")
                    yield {
                        "id": msg_id,
                        "event": "message",
                        "data": data,
                    }

                    try:
                        parsed = json.loads(data)
                        if parsed.get("status") in ("completed", "failed"):
                            return
                    except json.JSONDecodeError:
                        pass
                last_ping = time.time()
            else:
                current_status = await get_task_status(task_id)
                if current_status and current_status.get("status") in ("completed", "failed"):
                    final_data = json.dumps({
                        "status": current_status["status"],
                        "progress": current_status.get("progress", "100"),
                        "result": current_status.get("result", ""),
                        "error": current_status.get("error", ""),
                    }, ensure_ascii=False)
                    yield {
                        "id": "final",
                        "event": "message",
                        "data": final_data,
                    }
                    return

            now = time.time()
            if now - last_ping >= SSE_PING_INTERVAL:
                yield {
                    "event": "ping",
                    "data": "",
                }
                last_ping = now

            await asyncio.sleep(0.1)

    return EventSourceResponse(
        event_generator(),
        ping=SSE_PING_INTERVAL,
        sep="\n",
    )


@router.get("/circuit-breaker/{name}")
async def get_circuit_status(name: str, user: dict = Depends(get_current_user)):
    cb = RedisCircuitBreaker(name=name)
    data = await cb._get_state()
    return {
        "name": name,
        "state": data.get("state", CircuitState.CLOSED.value),
        "failure_count": data.get("failure_count", "0"),
        "last_failure_time": data.get("last_failure_time", ""),
        "half_open_success": data.get("half_open_success", "0"),
    }


@router.post("/circuit-breaker/{name}/reset")
async def reset_circuit(name: str, user: dict = Depends(get_current_user)):
    cb = RedisCircuitBreaker(name=name)
    await cb.reset()
    return {"name": name, "state": CircuitState.CLOSED.value, "message": "熔断器已重置"}
