"""对话链路长期记忆召回单元测试（P2 T2.3，假 Store/Emitter/嵌入）。

覆盖：
- 开关：``enabled=False`` → 零召回/零事件；用户总开关关 → 既不读也不写（零事件）；
- 短路：无 user_id / 无本轮问题 → 直接空，不触达检索；
- 正常召回：``similar`` 命中 → 回 PG 补水 ``content`` + 下发 ``memory_recall``
  工具事件（running/done + ``result_count``）；
- 过滤：``get`` 返回 None（已删除）/ 非 active / 无正文 → 剔除；
- 降级：``similar`` 抛错 → fail-open 返回 ``{}`` + 末条 ``tool:error``。
"""
import sys

import pytest
from langchain_core.messages import HumanMessage

sys.path.insert(0, ".")

from app.services.collab import memory_recall as mr  # noqa: E402
from app.services.collab.memory_recall import (  # noqa: E402
    MEMORY_SENDER_ID,
    TOOL_MEMORY_RECALL,
    make_memory_recall,
)


# ============================================================
# 假件
# ============================================================

class FakeMemoryStore:
    def __init__(self, hits=None, rows=None, raise_on_similar=False):
        self.hits = hits or []
        self.rows = rows or {}
        self.raise_on_similar = raise_on_similar
        self.similar_calls: list[dict] = []
        self.get_calls: list[str] = []

    async def similar(self, user_id, vector, *, top_k=5, score_threshold=0.0, case_id=None):
        self.similar_calls.append(
            {"user_id": user_id, "top_k": top_k, "score_threshold": score_threshold}
        )
        if self.raise_on_similar:
            raise RuntimeError("qdrant down")
        return self.hits

    async def get(self, user_id, memory_id):
        self.get_calls.append(memory_id)
        return self.rows.get(memory_id)


def make_emit():
    events = []

    async def emit(conversation_id, event_type, data):
        events.append((event_type, data))

    return events, emit


def _human(text: str) -> HumanMessage:
    return HumanMessage(content=text, name="user", additional_kwargs={"sender_type": "user"})


def make_state(**kw):
    base = {
        "conversation_id": "c1",
        "turn_id": "t1",
        "round": 0,
        "user_id": "u1",
        "messages": [_human("我想咨询离婚财产分割")],
    }
    base.update(kw)
    return base


def _patch(monkeypatch, *, embed=None, enabled=True, embed_raises=False):
    async def _embed(text):
        if embed_raises:
            raise RuntimeError("embed down")
        return embed or [0.1, 0.2]

    async def _enabled(user_id):
        return enabled

    monkeypatch.setattr(mr, "embed_text", _embed)
    monkeypatch.setattr(mr, "is_memory_enabled", _enabled)


ROW = {
    "id": "m1",
    "user_id": "u1",
    "scope": "user",
    "memory_type": "preference",
    "content": "用户倾向于优先调解",
    "summary": None,
    "importance": 4,
    "status": "active",
    "embedding_status": "done",
}


def _provider(store, emit, **kw):
    return make_memory_recall(memory_store=store, emit=emit, **kw)


# ============================================================
# 开关 / 短路
# ============================================================

@pytest.mark.asyncio
async def test_disabled_short_circuits(monkeypatch):
    _patch(monkeypatch)
    store = FakeMemoryStore(hits=[{"id": "m1", "score": 0.9}], rows={"m1": dict(ROW)})
    events, emit = make_emit()
    p = _provider(store, emit, enabled=False)
    assert await p(make_state()) == {}
    assert store.similar_calls == [] and events == []


@pytest.mark.asyncio
async def test_user_toggle_off_no_read_no_write(monkeypatch):
    _patch(monkeypatch, enabled=False)  # 用户总开关关闭
    store = FakeMemoryStore(hits=[{"id": "m1", "score": 0.9}], rows={"m1": dict(ROW)})
    events, emit = make_emit()
    p = _provider(store, emit)
    assert await p(make_state()) == {}
    assert store.similar_calls == [] and events == []  # 不读，也不发事件


@pytest.mark.asyncio
async def test_no_user_id_skips(monkeypatch):
    _patch(monkeypatch)
    store = FakeMemoryStore(hits=[{"id": "m1", "score": 0.9}], rows={"m1": dict(ROW)})
    events, emit = make_emit()
    p = _provider(store, emit)
    assert await p(make_state(user_id="")) == {}
    assert store.similar_calls == [] and events == []


@pytest.mark.asyncio
async def test_no_question_skips(monkeypatch):
    _patch(monkeypatch)
    store = FakeMemoryStore()
    events, emit = make_emit()
    p = _provider(store, emit)
    assert await p(make_state(messages=[])) == {}
    assert store.similar_calls == [] and events == []


# ============================================================
# 正常召回 → memories + 事件
# ============================================================

@pytest.mark.asyncio
async def test_recall_hits_hydrates_and_emits(monkeypatch):
    _patch(monkeypatch)
    hits = [{"id": "m1", "score": 0.91}, {"id": "m2", "score": 0.80}]
    rows = {"m1": dict(ROW), "m2": {**ROW, "id": "m2", "content": "用户是乙方代理人"}}
    store = FakeMemoryStore(hits=hits, rows=rows)
    events, emit = make_emit()
    p = _provider(store, emit)

    out = await p(make_state())

    assert [m["id"] for m in out["memories"]] == ["m1", "m2"]
    assert out["memories"][0]["content"] == "用户倾向于优先调解"
    assert out["memories"][0]["score"] == 0.91  # 保留向量相似度
    # 检索参数：默认 top_k=5、阈值 0.0
    assert store.similar_calls[0]["user_id"] == "u1"
    assert store.similar_calls[0]["top_k"] == 5
    assert store.similar_calls[0]["score_threshold"] == 0.0
    # 事件：running + done
    tool_events = [e[1] for e in events if e[0] == "tool"]
    assert [t["status"] for t in tool_events] == ["running", "done"]
    assert all(t["tool"] == TOOL_MEMORY_RECALL for t in tool_events)
    assert all(t["agent_id"] == MEMORY_SENDER_ID for t in tool_events)
    assert tool_events[-1]["result_count"] == 2


@pytest.mark.asyncio
async def test_recall_filters_deleted_and_inactive(monkeypatch):
    _patch(monkeypatch)
    hits = [{"id": "m1", "score": 0.9}, {"id": "gone", "score": 0.8}, {"id": "arch", "score": 0.7}]
    rows = {
        "m1": dict(ROW),
        # "gone" 不在 rows → get 返回 None（已删除）
        "arch": {**ROW, "id": "arch", "status": "archived"},
    }
    store = FakeMemoryStore(hits=hits, rows=rows)
    events, emit = make_emit()
    p = _provider(store, emit)

    out = await p(make_state())

    assert [m["id"] for m in out["memories"]] == ["m1"]
    assert [e[1] for e in events if e[0] == "tool"][-1]["result_count"] == 1


@pytest.mark.asyncio
async def test_recall_empty_hits_no_memories(monkeypatch):
    _patch(monkeypatch)
    store = FakeMemoryStore(hits=[], rows={})
    events, emit = make_emit()
    p = _provider(store, emit)

    assert await p(make_state()) == {}
    # 仍下发 running/done（result_count=0），便于前端展示「未命中」
    tool_events = [e[1] for e in events if e[0] == "tool"]
    assert [t["status"] for t in tool_events] == ["running", "done"]
    assert tool_events[-1]["result_count"] == 0


# ============================================================
# 降级（fail-open）
# ============================================================

@pytest.mark.asyncio
async def test_similar_error_fail_open(monkeypatch):
    _patch(monkeypatch)
    store = FakeMemoryStore(hits=[], raise_on_similar=True)
    events, emit = make_emit()
    p = _provider(store, emit)

    assert await p(make_state()) == {}  # 不抛出
    tool_events = [e[1] for e in events if e[0] == "tool"]
    assert tool_events[-1]["status"] == "error"


@pytest.mark.asyncio
async def test_embed_error_fail_open(monkeypatch):
    _patch(monkeypatch, embed_raises=True)
    store = FakeMemoryStore(hits=[{"id": "m1", "score": 0.9}], rows={"m1": dict(ROW)})
    events, emit = make_emit()
    p = _provider(store, emit)

    assert await p(make_state()) == {}
    assert store.similar_calls == []  # 嵌入失败即不再检索
    tool_events = [e[1] for e in events if e[0] == "tool"]
    assert tool_events[-1]["status"] == "error"


@pytest.mark.asyncio
async def test_emit_error_does_not_break(monkeypatch):
    _patch(monkeypatch)

    async def _boom(conversation_id, event_type, data):
        raise RuntimeError("sse down")

    store = FakeMemoryStore(hits=[{"id": "m1", "score": 0.9}], rows={"m1": dict(ROW)})
    p = _provider(store, _boom)

    out = await p(make_state())
    assert out["memories"][0]["id"] == "m1"  # 事件推送失败不影响召回结果
