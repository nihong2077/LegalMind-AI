import json
import logging
import time
import uuid
from typing import Optional

import redis.asyncio as aioredis

from .config import settings

logger = logging.getLogger(__name__)

redis_client: Optional[aioredis.Redis] = None

TASK_QUEUE_KEY = "legalmind:task_queue"
TASK_STATUS_PREFIX = "legalmind:task_status:"
TASK_STREAM_PREFIX = "legalmind:task_stream:"
STREAM_MAX_LEN = 1000


async def init_redis() -> aioredis.Redis:
    global redis_client
    try:
        from redis.retry import Retry
        from redis.backoff import ExponentialBackoff
        retry = Retry(ExponentialBackoff(base=1, cap=10), retries=3)
    except ImportError:
        retry = None

    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry=retry,
        retry_on_timeout=True,
    )
    # 验证连接
    await redis_client.ping()
    logger.info("Redis 连接成功: %s", settings.REDIS_URL)
    return redis_client


async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.aclose()


def get_redis() -> aioredis.Redis:
    if redis_client is None:
        raise RuntimeError("Redis 未初始化，请先调用 init_redis()")
    return redis_client


def generate_task_id() -> str:
    return str(uuid.uuid4())


async def enqueue_task(task_type: str, payload: dict, task_id: Optional[str] = None) -> str:
    r = get_redis()
    if task_id is None:
        task_id = generate_task_id()

    exists = await r.hexists(f"{TASK_STATUS_PREFIX}{task_id}", "task_id")
    if exists:
        return task_id

    task_data = {
        "task_id": task_id,
        "task_type": task_type,
        "payload": json.dumps(payload, ensure_ascii=False),
        "status": "pending",
        "progress": "0",
        "created_at": str(time.time()),
        "updated_at": str(time.time()),
    }
    pipe = r.pipeline()
    pipe.hset(f"{TASK_STATUS_PREFIX}{task_id}", mapping=task_data)
    pipe.rpush(TASK_QUEUE_KEY, task_id)
    await pipe.execute()

    return task_id


async def get_task_status(task_id: str) -> Optional[dict]:
    r = get_redis()
    data = await r.hgetall(f"{TASK_STATUS_PREFIX}{task_id}")
    if not data:
        return None
    return data


async def update_task_status(
    task_id: str,
    status: str,
    progress: Optional[str] = None,
    result: Optional[str] = None,
    error: Optional[str] = None,
) -> bool:
    r = get_redis()
    exists = await r.exists(f"{TASK_STATUS_PREFIX}{task_id}")
    if not exists:
        return False

    updates: dict = {
        "status": status,
        "updated_at": str(time.time()),
    }
    if progress is not None:
        updates["progress"] = progress
    if result is not None:
        updates["result"] = result
    if error is not None:
        updates["error"] = error

    event = {
        "status": status,
        "progress": progress or "",
        "updated_at": updates["updated_at"],
    }
    if result:
        event["result"] = result
    if error:
        event["error"] = error

    pipe = r.pipeline()
    pipe.hset(f"{TASK_STATUS_PREFIX}{task_id}", mapping=updates)
    pipe.xadd(
        f"{TASK_STREAM_PREFIX}{task_id}",
        {"data": json.dumps(event, ensure_ascii=False)},
        maxlen=STREAM_MAX_LEN,
        approximate=True,
    )
    await pipe.execute()

    return True


async def pop_task() -> Optional[str]:
    r = get_redis()
    result = await r.lpop(TASK_QUEUE_KEY)
    return result


async def get_stream_events(
    task_id: str,
    last_id: str = "0",
    count: int = 10,
    block: int = 3000,
) -> list:
    r = get_redis()
    stream_key = f"{TASK_STREAM_PREFIX}{task_id}"
    resp = await r.xread({stream_key: last_id}, block=block, count=count)
    if not resp:
        return []
    _, messages = resp[0]
    return [(msg_id, msg) for msg_id, msg in messages]


async def redis_health_check() -> dict:
    try:
        r = get_redis()
        start = time.time()
        await r.ping()
        latency_ms = round((time.time() - start) * 1000, 2)
        info = await r.info("memory")
        used_memory = info.get("used_memory_human", "unknown")
        return {
            "status": "healthy",
            "latency_ms": latency_ms,
            "used_memory": used_memory,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }
