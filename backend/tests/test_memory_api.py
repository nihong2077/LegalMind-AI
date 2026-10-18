"""T2.1 长期记忆 CRUD API 测试（内存 FakeStore + FakeRedis，不依赖 PG/Qdrant）。"""
import sys

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, ".")

from app.core.response import register_exception_handlers
from app.core.security import get_current_user
from app.routers import memory as memory_mod
from app.services.memory import store as store_mod
from app.services.memory.store import get_memory_store


class FakeKv:
    """记忆开关用到的 Redis String 子集。"""

    def __init__(self):
        self._data: dict[str, str] = {}

    async def get(self, key):
        return self._data.get(key)

    async def set(self, key, value):
        self._data[key] = value


class FakeMemoryStore:
    """与 :class:`MemoryStore` 同接口的内存实现（含按 user 隔离语义）。"""

    def __init__(self):
        self._rows: dict[str, dict] = {}
        self._seq = 0

    def _now(self) -> str:
        self._seq += 1
        return f"2026-01-01T00:00:{self._seq:02d}"

    async def list(self, user_id, *, scope=None, memory_type=None, case_id=None,
                   status=None, q=None, limit=20, offset=0):
        rows = [dict(r) for r in self._rows.values() if r["user_id"] == user_id]
        if scope:
            rows = [r for r in rows if r["scope"] == scope]
        if memory_type:
            rows = [r for r in rows if r["memory_type"] == memory_type]
        if case_id:
            rows = [r for r in rows if r["case_id"] == case_id]
        if status:
            rows = [r for r in rows if r["status"] == status]
        if q:
            rows = [r for r in rows if q in (r["content"] or "") or q in (r["summary"] or "")]
        rows.sort(key=lambda r: r["updated_at"], reverse=True)
        total = len(rows)
        return rows[offset:offset + limit], total

    async def get(self, user_id, memory_id):
        r = self._rows.get(memory_id)
        return dict(r) if r and r["user_id"] == user_id else None

    async def create(self, user_id, *, scope, memory_type, content, summary=None,
                     importance=3, case_id=None, source_conversation_id=None,
                     source_message_id=None):
        mid = f"mem-{len(self._rows) + 1}"
        self._rows[mid] = {
            "id": mid, "user_id": user_id, "scope": scope, "case_id": case_id,
            "memory_type": memory_type, "content": content, "summary": summary,
            "importance": importance,
            "source_conversation_id": source_conversation_id,
            "source_message_id": source_message_id,
            "status": "active", "embedding_status": "pending",
            "created_at": self._now(), "updated_at": self._now(),
        }
        return dict(self._rows[mid])

    async def update(self, user_id, memory_id, *, content=None, summary=None,
                     importance=None, memory_type=None, status=None):
        r = self._rows.get(memory_id)
        if not r or r["user_id"] != user_id:
            return None
        if content is not None:
            r["content"] = content
        if summary is not None:
            r["summary"] = summary
        if importance is not None:
            r["importance"] = importance
        if memory_type is not None:
            r["memory_type"] = memory_type
        if status is not None:
            r["status"] = status
        r["updated_at"] = self._now()
        return dict(r)

    async def delete(self, user_id, memory_id):
        r = self._rows.get(memory_id)
        if not r or r["user_id"] != user_id:
            return False
        del self._rows[memory_id]
        return True


@pytest.fixture
def app_and_store(monkeypatch):
    fake_kv = FakeKv()
    monkeypatch.setattr(store_mod, "get_redis", lambda: fake_kv)
    store = FakeMemoryStore()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(memory_mod.router)
    app.dependency_overrides[get_memory_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: {"sub": "alice"}
    return app, store


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_crud_roundtrip(app_and_store):
    app, _ = app_and_store
    async with _client(app) as c:
        r = await c.post("/api/memories", json={"memory_type": "fact", "content": "用户在太原工作"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["content"] == "用户在太原工作"
        assert body["request_id"]
        mid = body["data"]["id"]

        r = await c.get("/api/memories")
        assert r.json()["data"]["total"] == 1

        r = await c.get(f"/api/memories/{mid}")
        assert r.status_code == 200 and r.json()["data"]["id"] == mid

        r = await c.patch(f"/api/memories/{mid}", json={"importance": 5, "summary": "工作地"})
        assert r.json()["data"]["importance"] == 5
        assert r.json()["data"]["summary"] == "工作地"

        r = await c.delete(f"/api/memories/{mid}")
        assert r.status_code == 200
        assert (await c.get(f"/api/memories/{mid}")).status_code == 404


@pytest.mark.asyncio
async def test_user_isolation(app_and_store):
    app, store = app_and_store
    async with _client(app) as c:
        await c.post("/api/memories", json={"memory_type": "fact", "content": "alice 的私有记忆"})
        mid = next(iter(store._rows))

        app.dependency_overrides[get_current_user] = lambda: {"sub": "bob"}
        assert (await c.get("/api/memories")).json()["data"]["total"] == 0
        assert (await c.get(f"/api/memories/{mid}")).status_code == 404
        assert (await c.patch(f"/api/memories/{mid}", json={"importance": 5})).status_code == 404
        assert (await c.delete(f"/api/memories/{mid}")).status_code == 404
        # 越权尝试后 alice 的记忆仍在
        app.dependency_overrides[get_current_user] = lambda: {"sub": "alice"}
        assert (await c.get(f"/api/memories/{mid}")).status_code == 200


@pytest.mark.asyncio
async def test_filters_and_validation(app_and_store):
    app, _ = app_and_store
    async with _client(app) as c:
        await c.post("/api/memories", json={"memory_type": "fact", "content": "劳动合同纠纷案件"})
        await c.post("/api/memories", json={"memory_type": "preference", "content": "偏好简洁回答"})

        assert (await c.get("/api/memories", params={"memory_type": "preference"})).json()["data"]["total"] == 1
        assert (await c.get("/api/memories", params={"q": "劳动"})).json()["data"]["total"] == 1
        assert (await c.get("/api/memories", params={"status": "archived"})).json()["data"]["total"] == 0

        bad = await c.get("/api/memories", params={"scope": "bad"})
        assert bad.status_code == 400 and bad.json()["code"] == 40001

        missing = await c.post("/api/memories", json={"memory_type": "fact"})
        assert missing.status_code == 400 and missing.json()["code"] == 40001


@pytest.mark.asyncio
async def test_memory_toggle(app_and_store):
    app, _ = app_and_store
    async with _client(app) as c:
        assert (await c.get("/api/memories/setting")).json()["data"]["enabled"] is True
        r = await c.put("/api/memories/setting", json={"enabled": False})
        assert r.json()["data"]["enabled"] is False
        assert (await c.get("/api/memories/setting")).json()["data"]["enabled"] is False
