"""T2.2 记忆抽取/写入管线测试（假 store + 假 LLM，不依赖 PG/Qdrant/LLM/Redis）。

覆盖：抽取输出稳健解析、三重去重动作（合并/去重提示/新增）、consumer 重试耗尽进 DLQ、
Kafka 关闭时的进程内派发。
"""
import sys
from typing import Any, Optional

import pytest

sys.path.insert(0, ".")

from app.core.config import settings
from app.services.memory import extractor as extractor_mod
from app.services.memory import pipeline as pipeline_mod
from app.worker.consumers import memory as memory_consumer_mod
from app.worker.consumers.memory import handle_memory_message


# ============================================================
# 假件
# ============================================================

class FakeMemoryStore:
    def __init__(self, hits: Optional[list[dict]] = None, rows: Optional[dict] = None):
        self.hits = hits or []
        self.rows = rows or {}
        self._seq = 0

    async def similar(self, user_id, vector, *, case_id=None, top_k=5, score_threshold=0.0):
        return self.hits

    async def get(self, user_id, memory_id):
        row = self.rows.get(memory_id)
        if row is None or row.get("user_id") != user_id:
            return None
        return dict(row)

    async def update(self, user_id, memory_id, *, content=None, summary=None,
                     importance=None, memory_type=None, status=None):
        row = self.rows.get(memory_id)
        if row is None or row.get("user_id") != user_id:
            return None
        if content is not None:
            row["content"] = content
        if importance is not None:
            row["importance"] = importance
        return dict(row)

    async def create(self, user_id, *, scope, memory_type, content, summary=None,
                     importance=3, case_id=None, source_conversation_id=None,
                     source_message_id=None):
        self._seq += 1
        mid = f"m{self._seq}"
        self.rows[mid] = {
            "id": mid, "user_id": user_id, "scope": scope,
            "memory_type": memory_type, "content": content,
            "importance": importance,
        }
        return dict(self.rows[mid])


def _hit(memory_id: str, score: float) -> dict:
    return {"id": memory_id, "score": score, "payload": {"memory_id": memory_id, "status": "active"}}


def _cand(content="用户要求结论先行", **kw) -> dict:
    base = {"memory_type": "preference", "content": content, "summary": None,
            "importance": 4, "scope": "user", "case_id": None}
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _fast_embed(monkeypatch):
    async def _embed(text):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(pipeline_mod, "embed_text", _embed)


# ============================================================
# 抽取器：稳健解析
# ============================================================

def test_parse_candidates_handles_fenced_json_and_coercion():
    raw = '```json\n{"memories": [{"memory_type": "偏好", "content": "用户偏好中文", "importance": 99}]}\n```'
    out = extractor_mod.parse_candidates(raw)
    assert len(out) == 1
    assert out[0]["memory_type"] == "fact"      # 非法 type 归 fact
    assert out[0]["importance"] == 5            # 越界夹取到 1-5
    assert out[0]["scope"] == "user"            # 缺省 scope


def test_parse_candidates_dedupes_and_drops_invalid():
    raw = ('{"memories": [{"content": "甲"}, {"content": "甲"}, '
           '{"content": ""}, {"no_content": 1}, "not-a-dict"]}')
    out = extractor_mod.parse_candidates(raw)
    assert [c["content"] for c in out] == ["甲"]


def test_parse_candidates_returns_empty_on_garbage():
    assert extractor_mod.parse_candidates("完全不是 JSON") == []


def test_build_extract_messages_marks_senders():
    msgs = extractor_mod.build_extract_messages(
        [{"sender_type": "user", "sender_name": "张三", "content": "我下周要开庭"},
         {"sender_type": "agent", "sender_name": "助手", "content": "好的"}]
    )
    assert msgs[0]["role"] == "system"
    assert "[user:张三] 我下周要开庭" in msgs[1]["content"]


# ============================================================
# 三重去重动作
# ============================================================

@pytest.mark.asyncio
async def test_apply_candidate_merges_when_above_merge_threshold():
    store = FakeMemoryStore(
        hits=[_hit("m1", 0.95)],
        rows={"m1": {"id": "m1", "user_id": "u1", "content": "用户偏好中文答复", "importance": 3}},
    )
    res = await pipeline_mod._apply_candidate(store, "u1", _cand("用户要求结论先行"))
    assert res["action"] == "merge"
    assert "结论先行" in store.rows["m1"]["content"]
    assert "中文答复" in store.rows["m1"]["content"]
    assert store.rows["m1"]["importance"] == 4


@pytest.mark.asyncio
async def test_apply_candidate_prompts_between_dedup_and_merge():
    store = FakeMemoryStore(hits=[_hit("m1", 0.80)])
    res = await pipeline_mod._apply_candidate(store, "u1", _cand())
    assert res["action"] == "prompt"
    assert res["similar_memory_id"] == "m1"
    assert store.rows[res["memory_id"]]["content"] == "用户要求结论先行"


@pytest.mark.asyncio
async def test_apply_candidate_creates_when_below_dedup_threshold():
    store = FakeMemoryStore(hits=[])
    res = await pipeline_mod._apply_candidate(store, "u1", _cand())
    assert res["action"] == "new"
    assert store.rows[res["memory_id"]]["memory_type"] == "preference"


# ============================================================
# consumer：重试耗尽进 DLQ / 成功直通
# ============================================================

@pytest.mark.asyncio
async def test_handle_memory_message_retries_then_dlq(monkeypatch):
    monkeypatch.setattr(settings, "MEMORY_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "MEMORY_RETRY_BACKOFF", 0.0)
    calls = {"n": 0}
    published: list[tuple[str, dict]] = []

    async def _boom(turn_id, *, store=None, llm=None):
        calls["n"] += 1
        raise RuntimeError("pg down")

    async def _publish(topic, value, **kw):
        published.append((topic, value))
        return True

    monkeypatch.setattr(memory_consumer_mod, "ingest_turn", _boom)
    monkeypatch.setattr(memory_consumer_mod.event_bus, "publish", _publish)

    res = await handle_memory_message({"turn_id": "t1", "conversation_id": "c1", "user_id": "u1"})
    assert res["result"] == "dlq"
    assert calls["n"] == 2                       # 重试到上限
    assert published and published[0][0] == settings.KAFKA_TOPIC_MEMORY_DLQ
    assert published[0][1]["attempts"] == 2


@pytest.mark.asyncio
async def test_handle_memory_message_success_path(monkeypatch):
    async def _ok(turn_id, *, store=None, llm=None):
        return {"result": "ok", "turn_id": turn_id}

    monkeypatch.setattr(memory_consumer_mod, "ingest_turn", _ok)
    res = await handle_memory_message({"turn_id": "t1"})
    assert res["result"] == "ok"


@pytest.mark.asyncio
async def test_handle_memory_message_without_turn_id():
    res = await handle_memory_message({"conversation_id": "c1"})
    assert res == {"result": "skipped", "reason": "no_turn_id"}


# ============================================================
# 派发：Kafka 关闭 → 进程内抽取
# ============================================================

@pytest.mark.asyncio
async def test_dispatch_falls_back_to_inprocess_when_kafka_disabled(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_KAFKA", False)
    seen: list[str] = []

    async def _fake_ingest(turn_id):
        seen.append(turn_id)
        return {"result": "ok"}

    monkeypatch.setattr(pipeline_mod, "ingest_turn", _fake_ingest)
    await pipeline_mod.dispatch_memory_event({"turn_id": "t9", "conversation_id": "c1", "user_id": "u1"})
    await pipeline_mod.asyncio.gather(*list(pipeline_mod._inprocess_tasks), return_exceptions=True)
    assert seen == ["t9"]
