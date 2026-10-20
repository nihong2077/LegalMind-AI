"""T3.1 统一案情搜索 API 测试（内存 FakeBackend，不依赖 PG/Qdrant/LLM）。"""
import sys

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, ".")

from app.core.response import register_exception_handlers
from app.core.security import get_current_user
from app.routers import search as search_mod
from app.routers.search import get_search_backend


def _law_item(content: str, score: float = 0.9) -> dict:
    return {
        "type": "law",
        "content": content,
        "source": "劳动合同法",
        "score": score,
        "domain": "law",
        "doc_type": "provision",
    }


def _message_item(content: str) -> dict:
    return {
        "type": "messages",
        "id": "m1",
        "conversation_id": "c1",
        "conversation_title": "竞业限制咨询",
        "sender_type": "user",
        "sender_name": "alice",
        "content": content,
        "round": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


class FakeBackend:
    """与 :class:`SearchBackend` 同接口的内存实现，可指定某几路抛错。"""

    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.calls: list[str] = []

    async def law(self, query, *, top_k, use_hyde):
        self.calls.append("law")
        if "law" in self.fail:
            raise RuntimeError("law boom")
        return [_law_item("竞业限制期限不得超过二年")]

    async def judge(self, query, *, top_k, use_hyde):
        self.calls.append("judge")
        if "judge" in self.fail:
            raise RuntimeError("judge boom")
        return [{"type": "judge", "content": "类案：竞业限制纠纷", "source": "某中院", "score": 0.8, "domain": "judge", "doc_type": "case"}]

    async def memory(self, user_id, query, *, top_k, case_id=None):
        self.calls.append("memory")
        if "memory" in self.fail:
            raise RuntimeError("memory boom")
        return [{"type": "memory", "id": "mem-1", "memory_type": "fact", "content": "用户在太原工作", "summary": None, "importance": 3, "case_id": None, "score": 0.7, "created_at": "2026-01-01T00:00:00+00:00"}]

    async def messages(self, user_id, query, *, limit):
        self.calls.append("messages")
        if "messages" in self.fail:
            raise RuntimeError("messages boom")
        return [_message_item("我遇到竞业限制纠纷")]


@pytest.fixture
def app_and_backend():
    backend = FakeBackend()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(search_mod.router)
    app.dependency_overrides[get_search_backend] = lambda: backend
    app.dependency_overrides[get_current_user] = lambda: {"sub": "alice"}
    return app, backend


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_unified_four_sources(app_and_backend):
    app, _ = app_and_backend
    async with _client(app) as c:
        r = await c.post("/api/search/unified", json={"query": "竞业限制"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == 0
        assert body["request_id"]
        data = body["data"]
        # 四类结果各归其位
        assert [x["content"] for x in data["results"]["law"]] == ["竞业限制期限不得超过二年"]
        assert data["results"]["judge"][0]["type"] == "judge"
        assert data["results"]["memory"][0]["memory_type"] == "fact"
        assert data["results"]["messages"][0]["conversation_title"] == "竞业限制咨询"
        assert data["counts"] == {"law": 1, "judge": 1, "memory": 1, "messages": 1, "total": 4}
        assert data["errors"] == {}


@pytest.mark.asyncio
async def test_sources_filter(app_and_backend):
    app, backend = app_and_backend
    async with _client(app) as c:
        r = await c.post("/api/search/unified", json={"query": "竞业限制", "sources": ["law"]})
        data = r.json()["data"]
        assert data["counts"] == {"law": 1, "judge": 0, "memory": 0, "messages": 0, "total": 1}
        assert backend.calls == ["law"]  # 未选中的路不触发
        # 结果字典始终四键齐全，未被检索的路为空列表
        assert data["results"]["judge"] == []


@pytest.mark.asyncio
async def test_bad_source_validation(app_and_backend):
    app, _ = app_and_backend
    async with _client(app) as c:
        r = await c.post("/api/search/unified", json={"query": "x", "sources": ["nope"]})
        assert r.status_code == 400
        assert r.json()["code"] == 40001


@pytest.mark.asyncio
async def test_empty_query_validation(app_and_backend):
    app, _ = app_and_backend
    async with _client(app) as c:
        # 空白串绕过 Pydantic，业务层判空
        blank = await c.post("/api/search/unified", json={"query": "   "})
        assert blank.status_code == 400 and blank.json()["code"] == 40001
        # 空串触发字段级校验
        empty = await c.post("/api/search/unified", json={"query": ""})
        assert empty.status_code == 400 and empty.json()["code"] == 40001


@pytest.mark.asyncio
async def test_failure_isolation(app_and_backend):
    app, _ = app_and_backend
    app.dependency_overrides[get_search_backend] = lambda: FakeBackend(fail={"judge"})
    async with _client(app) as c:
        r = await c.post("/api/search/unified", json={"query": "竞业限制"})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        # 失败路被隔离：空结果 + errors 记录，其余三路不受影响
        assert data["results"]["judge"] == []
        assert "judge" in data["errors"]
        assert data["counts"]["law"] == 1 and data["counts"]["memory"] == 1
