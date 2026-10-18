"""T0.10 worker 骨架单测（fake redis + 本地 aiohttp，不依赖 Redis/Kafka）。"""
import asyncio
import sys

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

sys.path.insert(0, ".")

from app.core.config import settings
from app.worker import main as wm

pytestmark = pytest.mark.asyncio


# ---------- fakes ----------

class FakePipe:
    def __init__(self, owner: "FakeRedis"):
        self.owner = owner
        self.ops: list[tuple] = []

    def set(self, key, value, ex):
        self.ops.append(("set", key, value, ex))
        if self.owner.fail_next:
            self.owner.fail_next = False
            raise ConnectionError("redis reset")
        return self

    def zadd(self, key, mapping):
        self.ops.append(("zadd", key, dict(mapping)))
        return self

    def zremrangebyscore(self, key, min_, max_):
        self.ops.append(("zrem", key, min_, max_))
        return self

    def expire(self, key, seconds):
        self.ops.append(("expire", key, seconds))
        return self

    def delete(self, key):
        self.ops.append(("delete", key))
        return self

    def zrem(self, key, member):
        self.ops.append(("zrem", key, member))
        return self

    async def execute(self):
        self.owner.pipelines.append(self.ops)
        return []


class FakeRedis:
    def __init__(self):
        self.pipelines: list[list[tuple]] = []
        self.zmembers: dict[str, list[tuple[str, float]]] = {}
        self.fail_next = False
        self.ping_error: Exception | None = None

    def pipeline(self):
        return FakePipe(self)

    async def ping(self):
        if self.ping_error:
            raise self.ping_error
        return True

    async def zrangebyscore(self, key, min_, max_, start=0, num=None, withscores=False):
        # 仅模拟 "(cutoff" 开区间到 +inf 的过滤
        cutoff = float(min_[1:]) if isinstance(min_, str) and min_.startswith("(") else float(min_)
        rows = [(m, s) for m, s in self.zmembers.get(key, []) if s > cutoff]
        if num is not None:
            rows = rows[start:start + num]
        return rows if withscores else [m for m, _ in rows]


@pytest.fixture
def fake_redis():
    return FakeRedis()


# ---------- 纯逻辑 ----------

@pytest.mark.parametrize("role,setting", [
    ("collab", "KAFKA_TOPIC_TURNS"),
    ("memory", "KAFKA_TOPIC_MEMORY"),
    ("doc", "KAFKA_TOPIC_DOC_TASKS"),
])
def test_role_topic_mapping(role, setting):
    assert wm.role_topic(role) == getattr(settings, setting)


def test_role_topic_rejects_unknown():
    with pytest.raises(KeyError):
        wm.role_topic("judge")


def test_worker_id_and_key_shape():
    wid = wm.build_worker_id("collab")
    assert wid.startswith("collab-")
    assert wm.build_worker_id("collab") != wid  # 多实例不撞
    assert wm.heartbeat_key(wid) == f"{settings.WORKER_KEY_PREFIX}:{wid}"


async def test_beat_once_writes_key_ttl_index_and_trim(fake_redis):
    payload = await wm.beat_once(
        fake_redis, role="memory", worker_id="memory-h-1-ab12cd34",
        started_at=1000.0, now=2000.0,
    )

    assert payload == {
        "role": "memory", "worker_id": "memory-h-1-ab12cd34",
        "host": payload["host"], "pid": payload["pid"],
        "started_at": 1000.0, "ts": 2000.0,
    }
    ops = fake_redis.pipelines[0]
    kinds = [op[0] for op in ops]
    assert kinds == ["set", "zadd", "zrem", "expire"]

    _, key, value, ex = ops[0]
    assert key == f"{settings.WORKER_KEY_PREFIX}:memory-h-1-ab12cd34"
    assert ex == 30
    assert '"role": "memory"' in value  # JSON 含角色元信息

    _, idx, mapping = ops[1]
    assert idx == settings.WORKER_INDEX_KEY
    assert mapping == {"memory-h-1-ab12cd34": 2000.0}

    _, _, lo, hi = ops[2]
    assert (lo, hi) == (0, 2000.0 - 30)  # 修剪窗口外成员

    _, _, ttl = ops[3]
    assert ttl == 60  # 索引滚动 TTL = 判定窗口*2


async def test_list_online_filters_window_and_parses_role(fake_redis):
    fake_redis.zmembers[settings.WORKER_INDEX_KEY] = [
        ("collab-a", 100.0),   # 窗口外
        ("memory-b", 125.0),   # 窗口内（cutoff=120，开区间）
        ("doc-c", 130.0),
    ]
    online = await wm.list_online(fake_redis, now=150.0)
    assert [r["worker_id"] for r in online] == ["memory-b", "doc-c"]
    assert online[0]["role"] == "memory" and online[1]["role"] == "doc"


async def test_heartbeat_loop_survives_redis_error_and_stops(fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "WORKER_HEARTBEAT_INTERVAL", 0.01)
    fake_redis.fail_next = True  # 第一跳 set 抛 ConnectionError
    stop = asyncio.Event()
    task = asyncio.create_task(
        wm.heartbeat_loop(fake_redis, "collab", "collab-x", 1.0, stop)
    )
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2)  # 异常未上抛、可优雅停止
    assert len(fake_redis.pipelines) >= 2    # 失败后继续跳


async def test_deregister_removes_key_and_index_member(fake_redis):
    await wm.deregister_worker(fake_redis, "collab", "collab-h-1-ab")
    ops = fake_redis.pipelines[0]
    assert ops == [
        ("delete", f"{settings.WORKER_KEY_PREFIX}:collab-h-1-ab"),
        ("zrem", settings.WORKER_INDEX_KEY, "collab-h-1-ab"),
    ]


# ---------- HTTP 端点 ----------

async def test_healthz_ok_without_dependency_check():
    app = wm.create_app("collab", "collab-test-1", started_at=1000.0)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(server.make_url("/healthz")) as resp:
                assert resp.status == 200
                body = await resp.json()
        assert body["status"] == "ok"
        assert body["role"] == "collab"
        assert body["worker_id"] == "collab-test-1"
        assert "uptime" in body
    finally:
        await server.close()


async def test_metrics_endpoint_prometheus_format():
    app = wm.create_app("doc", "doc-test-1", started_at=1.0)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(server.make_url("/metrics")) as resp:
                assert resp.status == 200
                ctype = resp.headers["Content-Type"]
                text = await resp.text()
        assert ctype.startswith("text/plain")
        assert "python_info" in text  # prometheus_client 默认进程指标
    finally:
        await server.close()


async def test_readyz_200_when_redis_ok():
    redis = FakeRedis()
    app = wm.create_app(
        "collab", "collab-test-1", started_at=1.0,
        redis=redis, standby_state={"kafka": "standby"},
    )
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(server.make_url("/readyz")) as resp:
                assert resp.status == 200
                body = await resp.json()
        assert body["ready"] is True
        assert body["checks"]["redis"]["status"] == "healthy"
        assert body["checks"]["kafka"]["status"] in ("standby", "disabled")
    finally:
        await server.close()


async def test_readyz_503_when_redis_down_but_healthz_200():
    redis = FakeRedis()
    redis.ping_error = ConnectionError("redis reset")
    app = wm.create_app(
        "collab", "collab-test-1", started_at=1.0, redis=redis,
        standby_state={"kafka": "standby"},
    )
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(server.make_url("/readyz")) as resp:
                assert resp.status == 503
                body = await resp.json()
            async with session.get(server.make_url("/healthz")) as resp2:
                assert resp2.status == 200  # 存活探针不查依赖
        assert body["ready"] is False
        assert body["checks"]["redis"]["status"] == "unhealthy"
    finally:
        await server.close()
