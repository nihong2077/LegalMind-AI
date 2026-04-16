import json
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, ".")

from app.core.redis_client import (
    TASK_QUEUE_KEY,
    TASK_STATUS_PREFIX,
    TASK_STREAM_PREFIX,
    close_redis,
    enqueue_task,
    generate_task_id,
    get_redis,
    get_task_status,
    get_stream_events,
    init_redis,
    pop_task,
    redis_health_check,
    update_task_status,
)


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.pipeline = MagicMock()
    return r


@pytest.fixture(autouse=True)
def reset_global():
    import app.core.redis_client as mod
    mod.redis_client = None
    yield
    mod.redis_client = None


@pytest.mark.asyncio
async def test_init_redis():
    with patch("app.core.redis_client.aioredis") as mock_aioredis:
        mock_instance = AsyncMock()
        mock_aioredis.from_url.return_value = mock_instance
        result = await init_redis()
        assert result is mock_instance
        mock_aioredis.from_url.assert_called_once()


@pytest.mark.asyncio
async def test_close_redis():
    import app.core.redis_client as mod
    mock = AsyncMock()
    mod.redis_client = mock
    await close_redis()
    mock.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_get_redis_not_initialized():
    with pytest.raises(RuntimeError, match="Redis 未初始化"):
        get_redis()


@pytest.mark.asyncio
async def test_get_redis_initialized():
    import app.core.redis_client as mod
    mock = AsyncMock()
    mod.redis_client = mock
    assert get_redis() is mock


def test_generate_task_id():
    id1 = generate_task_id()
    id2 = generate_task_id()
    assert id1 != id2
    assert len(id1) == 36


@pytest.mark.asyncio
async def test_enqueue_task_new(mock_redis):
    import app.core.redis_client as mod
    mod.redis_client = mock_redis

    mock_redis.hexists.return_value = False
    mock_pipe = AsyncMock()
    mock_redis.pipeline.return_value = mock_pipe

    task_id = await enqueue_task("legal_analysis", {"query": "合同审查"})
    assert task_id is not None
    mock_redis.hexists.assert_called_once()
    mock_pipe.execute.assert_called_once()


@pytest.mark.asyncio
async def test_enqueue_task_idempotent(mock_redis):
    import app.core.redis_client as mod
    mod.redis_client = mock_redis

    mock_redis.hexists.return_value = True
    task_id = await enqueue_task("legal_analysis", {"query": "合同审查"}, task_id="existing-id")
    assert task_id == "existing-id"
    mock_redis.hset.assert_not_called()
    mock_redis.rpush.assert_not_called()


@pytest.mark.asyncio
async def test_get_task_status_exists(mock_redis):
    import app.core.redis_client as mod
    mod.redis_client = mock_redis

    mock_redis.hgetall.return_value = {
        "task_id": "test-id",
        "status": "running",
        "progress": "50",
    }
    result = await get_task_status("test-id")
    assert result["status"] == "running"
    assert result["progress"] == "50"


@pytest.mark.asyncio
async def test_get_task_status_not_found(mock_redis):
    import app.core.redis_client as mod
    mod.redis_client = mock_redis

    mock_redis.hgetall.return_value = {}
    result = await get_task_status("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_update_task_status_success(mock_redis):
    import app.core.redis_client as mod
    mod.redis_client = mock_redis

    mock_redis.exists.return_value = 1
    mock_pipe = AsyncMock()
    mock_redis.pipeline.return_value = mock_pipe

    result = await update_task_status("test-id", "running", progress="50")
    assert result is True
    mock_pipe.execute.assert_called_once()


@pytest.mark.asyncio
async def test_update_task_status_not_found(mock_redis):
    import app.core.redis_client as mod
    mod.redis_client = mock_redis

    mock_redis.exists.return_value = 0
    result = await update_task_status("nonexistent", "running")
    assert result is False


@pytest.mark.asyncio
async def test_update_task_status_xadd_with_maxlen(mock_redis):
    import app.core.redis_client as mod
    mod.redis_client = mock_redis

    mock_redis.exists.return_value = 1
    mock_pipe = AsyncMock()
    mock_redis.pipeline.return_value = mock_pipe

    await update_task_status("test-id", "completed", progress="100", result="done")

    mock_pipe.xadd.assert_called_once()
    call_args = mock_pipe.xadd.call_args
    assert call_args.kwargs.get("maxlen") == 1000 or call_args[1].get("maxlen") == 1000


@pytest.mark.asyncio
async def test_pop_task(mock_redis):
    import app.core.redis_client as mod
    mod.redis_client = mock_redis

    mock_redis.lpop.return_value = "task-123"
    result = await pop_task()
    assert result == "task-123"


@pytest.mark.asyncio
async def test_pop_task_empty(mock_redis):
    import app.core.redis_client as mod
    mod.redis_client = mock_redis

    mock_redis.lpop.return_value = None
    result = await pop_task()
    assert result is None


@pytest.mark.asyncio
async def test_get_stream_events_with_data(mock_redis):
    import app.core.redis_client as mod
    mod.redis_client = mock_redis

    mock_redis.xread.return_value = [
        ("stream_key", [("1234567890-0", {"data": '{"status":"running"}'})])
    ]
    events = await get_stream_events("test-id")
    assert len(events) == 1
    assert events[0][0] == "1234567890-0"


@pytest.mark.asyncio
async def test_get_stream_events_empty(mock_redis):
    import app.core.redis_client as mod
    mod.redis_client = mock_redis

    mock_redis.xread.return_value = []
    events = await get_stream_events("test-id")
    assert events == []


@pytest.mark.asyncio
async def test_redis_health_check_healthy(mock_redis):
    import app.core.redis_client as mod
    mod.redis_client = mock_redis

    mock_redis.ping.return_value = True
    mock_redis.info.return_value = {"used_memory_human": "10.5M"}
    result = await redis_health_check()
    assert result["status"] == "healthy"
    assert "latency_ms" in result


@pytest.mark.asyncio
async def test_redis_health_check_unhealthy():
    import app.core.redis_client as mod
    mod.redis_client = None

    result = await redis_health_check()
    assert result["status"] == "unhealthy"
