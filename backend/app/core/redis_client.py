import json
import logging
import secrets
import time
import uuid
from typing import Any, Optional

import redis.asyncio as aioredis

from .config import settings

logger = logging.getLogger(__name__)

redis_client: Optional[aioredis.Redis] = None

TASK_QUEUE_KEY = "legalmind:task_queue"
TASK_STATUS_PREFIX = "legalmind:task_status:"
TASK_STREAM_PREFIX = "legalmind:task_stream:"
STREAM_MAX_LEN = 1000

# ============================================================
# 协同会话（T1.1；key 约定见 collab-ui-refactor_plan §8.2）
# ============================================================
# 最近消息热缓存：List，index 0 最新，LTRIM 20，TTL 10min
CONV_RECENT_PREFIX = "legalmind:conv:{}:messages:recent"
CONV_RECENT_LIMIT = 20
CONV_RECENT_TTL = 600
# SSE 事件：Stream 持久回放（MAXLEN 500）+ Pub/Sub 实时桥，同名双通道
CONV_EVENTS_PREFIX = "legalmind:conv:{}:events"
CONV_EVENTS_MAXLEN = 500
# 同群轮次锁：SET NX PX 10min，持有者令牌比对释放（防误删他人锁）
CONV_LOCK_PREFIX = "legalmind:lock:conv:{}"
TURN_LOCK_TTL_MS = 10 * 60 * 1000
# SSE 一次性短票据：String，TTL 60s（EventSource 不能带 Authorization 头）
SSE_TICKET_PREFIX = "legalmind:sse_ticket:{}"
SSE_TICKET_TTL = 60

# 释放锁只删自己持有的令牌（T1.6 runner 续锁/释放复用）
_RELEASE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


def conv_recent_key(conversation_id: str) -> str:
    return CONV_RECENT_PREFIX.format(conversation_id)


def conv_events_key(conversation_id: str) -> str:
    return CONV_EVENTS_PREFIX.format(conversation_id)


def conv_lock_key(conversation_id: str) -> str:
    return CONV_LOCK_PREFIX.format(conversation_id)


def sse_ticket_key(ticket: str) -> str:
    return SSE_TICKET_PREFIX.format(ticket)


def stream_id_gt(a: str, b: str) -> bool:
    """比较 Redis Stream ID（<ms>-<seq>）。"""
    ma, sa = a.split("-", 1)
    mb, sb = b.split("-", 1)
    return (int(ma), int(sa)) > (int(mb), int(sb))


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
        max_connections=settings.REDIS_MAX_CONNECTIONS,
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


async def _write_task_record(
    r: Any, task_id: str, task_type: str, payload: dict, *, to_queue: bool
) -> None:
    """写状态 hash 行（pending）；``to_queue`` 决定是否同步投递旧 Redis 队列。"""
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
    if to_queue:
        pipe.rpush(TASK_QUEUE_KEY, task_id)
    await pipe.execute()


async def _register_task(
    task_type: str, payload: dict, task_id: Optional[str], *, to_queue: bool
) -> str:
    r = get_redis()
    if task_id is None:
        task_id = generate_task_id()

    exists = await r.hexists(f"{TASK_STATUS_PREFIX}{task_id}", "task_id")
    if exists:
        return task_id

    await _write_task_record(r, task_id, task_type, payload, to_queue=to_queue)
    return task_id


async def enqueue_task(task_type: str, payload: dict, task_id: Optional[str] = None) -> str:
    """登记任务状态行并投递旧 Redis 队列（``legalmind:task_queue``）。"""
    return await _register_task(task_type, payload, task_id, to_queue=True)


async def create_task_record(
    task_type: str, payload: dict, task_id: Optional[str] = None
) -> str:
    """仅登记任务状态行（不投递旧队列）。

    Kafka 异步链路（T3.4 doc-tasks）复用同一 task 状态行，使前端仍可经
    ``/api/tasks/{task_id}`` 轮询进度；与 ``enqueue_task`` 一样保持幂等。
    """
    return await _register_task(task_type, payload, task_id, to_queue=False)


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


# ============================================================
# 协同：SSE 短票据（T1.1）
# ============================================================

async def issue_sse_ticket(conversation_id: str, user_id: str) -> str:
    """签发一次性 SSE 票据，绑定 user+conversation，60s 有效。

    EventSource 无法携带 Authorization 头，只能走 query；票据一次性、
    短 TTL，避免 JWT 长期暴露在 URL/代理日志中。重连时前端重新换票。
    """
    r = get_redis()
    ticket = secrets.token_urlsafe(24)
    payload = json.dumps(
        {"user_id": user_id, "conversation_id": str(conversation_id)},
        ensure_ascii=False,
    )
    await r.set(sse_ticket_key(ticket), payload, ex=SSE_TICKET_TTL)
    return ticket


async def consume_sse_ticket(ticket: str, expected_conversation_id: str) -> Optional[dict]:
    """校验并立即作废票据（GETDEL，一次性）。

    无效/过期/已使用/会话不匹配一律返回 None（调用方按 401 处理）。
    """
    if not ticket:
        return None
    r = get_redis()
    raw = await r.getdel(sse_ticket_key(ticket))
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if str(payload.get("conversation_id")) != str(expected_conversation_id):
        return None
    return payload


# ============================================================
# 协同：同群轮次锁（T1.1 提供；T1.6 runner 持有）
# ============================================================

async def acquire_turn_lock(
    conversation_id: str,
    holder: str,
    ttl_ms: int = TURN_LOCK_TTL_MS,
) -> bool:
    """尝试获取会话轮次锁。成功 True；已有轮次在跑返回 False（→ 50901）。"""
    r = get_redis()
    result = await r.set(conv_lock_key(conversation_id), holder, nx=True, px=ttl_ms)
    return bool(result)


async def release_turn_lock(conversation_id: str, holder: str) -> bool:
    """释放锁：仅当持有者令牌一致才删除，返回是否实际释放。"""
    r = get_redis()
    result = await r.eval(_RELEASE_LOCK_LUA, 1, conv_lock_key(conversation_id), holder)
    return bool(result)


async def get_turn_lock_holder(conversation_id: str) -> Optional[str]:
    r = get_redis()
    return await r.get(conv_lock_key(conversation_id))


async def refresh_turn_lock(
    conversation_id: str,
    holder: str,
    ttl_ms: int = TURN_LOCK_TTL_MS,
) -> bool:
    """续租轮次锁：仅当持有者令牌一致才续期（XX 语义），返回是否续期成功。

    长轮次（多次 LLM 调用）在 TTL 内未结束会被误判为僵死而放锁，故 runner 心跳
    与租约心跳同步续期此锁。
    """
    r = get_redis()
    result = await r.set(conv_lock_key(conversation_id), holder, px=ttl_ms, xx=True)
    return bool(result)


# ============================================================
# 协同：SSE 事件 Stream + Pub/Sub 双通道（T1.1）
# ============================================================

async def append_conv_event(
    conversation_id: str,
    event_type: str,
    data: dict[str, Any],
) -> str:
    """追加一条协同事件：先 XADD（断线缺口回放），再 PUBLISH（在线实时推送）。

    Stream 裁剪 MAXLEN≈500；Pub/Sub 消息体含 Stream ID，订阅端按 ID 去重，
    保证刷新/重连"不丢不重"。返回 Stream entry ID（即 SSE 事件 id）。
    """
    r = get_redis()
    stream_key = conv_events_key(conversation_id)
    entry_id = await r.xadd(
        stream_key,
        {"event": event_type, "data": json.dumps(data, ensure_ascii=False)},
        maxlen=CONV_EVENTS_MAXLEN,
        approximate=True,
    )
    await r.publish(
        stream_key,
        json.dumps(
            {"id": entry_id, "event": event_type, "data": data},
            ensure_ascii=False,
        ),
    )
    return entry_id


async def read_conv_events_since(
    conversation_id: str,
    last_id: str,
    count: int = 200,
) -> list[tuple[str, str, str]]:
    """读取 Stream 中严格晚于 last_id 的事件，返回 [(entry_id, event, data_json)]。"""
    if not last_id or last_id == "0":
        min_id = "-"
    else:
        # XRANGE 为闭区间，用 '(' 前缀排除自身
        min_id = "(" + last_id
    r = get_redis()
    entries = await r.xrange(
        conv_events_key(conversation_id), min=min_id, max="+", count=count
    )
    return [(eid, fields["event"], fields["data"]) for eid, fields in entries]


# ============================================================
# 协同：最近消息热缓存（T1.1；PG 为权威源）
# ============================================================

async def get_recent_messages(conversation_id: str) -> Optional[list[dict]]:
    """读取最近 20 条消息热缓存（按时间正序返回）；未命中/空返回 None。"""
    r = get_redis()
    raw_list = await r.lrange(conv_recent_key(conversation_id), 0, CONV_RECENT_LIMIT - 1)
    if not raw_list:
        return None
    messages: list[dict] = []
    for raw in reversed(raw_list):  # List 中 index 0 最新，反转为时间正序
        try:
            messages.append(json.loads(raw))
        except (TypeError, ValueError):
            continue
    return messages


async def push_recent_message(conversation_id: str, message: dict) -> None:
    """新消息入热缓存（LPUSH 最新在前 → LTRIM 20 → 续 TTL 10min）。"""
    r = get_redis()
    key = conv_recent_key(conversation_id)
    pipe = r.pipeline()
    pipe.lpush(key, json.dumps(message, ensure_ascii=False))
    pipe.ltrim(key, 0, CONV_RECENT_LIMIT - 1)
    pipe.expire(key, CONV_RECENT_TTL)
    await pipe.execute()


async def set_recent_messages(conversation_id: str, messages: list[dict]) -> None:
    """缓存未命中后整体回填（按时间正序传入，逐条 LPUSH 使最新在 index 0）。"""
    r = get_redis()
    key = conv_recent_key(conversation_id)
    pipe = r.pipeline()
    pipe.delete(key)
    for msg in messages:
        pipe.lpush(key, json.dumps(msg, ensure_ascii=False))
    pipe.ltrim(key, 0, CONV_RECENT_LIMIT - 1)
    pipe.expire(key, CONV_RECENT_TTL)
    await pipe.execute()


async def invalidate_recent_messages(conversation_id: str) -> None:
    r = get_redis()
    await r.delete(conv_recent_key(conversation_id))
