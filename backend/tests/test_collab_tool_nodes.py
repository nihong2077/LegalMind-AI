"""T1.9-M3 工具辐条引用卡单元测试（Fake LLM/Store/Emitter + 打桩检索，零外部依赖）。

覆盖：
- ``tool`` 进度事件：``running`` → ``done``（携带 query / result_count / elapsed_ms）；
- 引用卡：检索有结果时产出 ``msg_type=card`` 并幂等落库（event_key / 确定性 message_id）
  + 下发 ``message`` 事件（前端按 msg_type 渲染）；
- 领域映射：``law`` → ``law_citation``、``judge`` → ``case_citation``；
- 降级：无 domain/query 不发事件；检索异常发 ``tool:error`` + 空结果 + 不产出卡；
- 幂等：同轮次重跑「先查库后发」复用既有卡，不重复落库。
"""
import sys

import pytest

sys.path.insert(0, ".")

from app.services.collab import tool_nodes as tn  # noqa: E402
from app.services.collab.tool_nodes import (  # noqa: E402
    MSG_TYPE_CARD,
    TOOL_STATUS_DONE,
    TOOL_STATUS_ERROR,
    TOOL_STATUS_RUNNING,
    ToolNodeRunner,
    make_tool_runner,
)


# ============================================================
# 假件
# ============================================================

class FakeLLMClient:
    """``get_chat_model`` 返回占位（真实检索已被打桩，不实际调用 LLM）。"""

    def __init__(self):
        self.calls = []

    def get_chat_model(self, *, model, temperature=0.1, max_tokens=1024):
        self.calls.append({"model": model})
        return object()


class FakeStore:
    """内存 Store：模拟 event_key 唯一约束（ON CONFLICT DO NOTHING）。"""

    def __init__(self):
        self.records = {}

    async def get_message_by_event_key(self, conversation_id, event_key):
        return self.records.get(event_key)

    async def insert_message_once(self, conversation_id, *, event_key, **kw):
        if event_key in self.records:
            return None
        record = {"id": f"m{len(self.records) + 1}", "event_key": event_key, **kw}
        self.records[event_key] = record
        return record


class Msg:
    """最小 LangChain 消息替身（供 ``_query_of`` 读取 content / additional_kwargs）。"""

    def __init__(self, content, sender_type=None, name=""):
        self.content = content
        self.additional_kwargs = {"sender_type": sender_type} if sender_type else {}
        self.name = name


def make_emit():
    events = []

    async def emit(conversation_id, event_type, data):
        events.append((event_type, data))

    return events, emit


TOOL_LAW = {"agent_id": "law_researcher", "name": "法规检索员", "skill_ref": "RegulatoryResearcher"}
TOOL_CASE = {"agent_id": "case_searcher", "name": "类案检索员", "skill_ref": "CaseSearchSkill"}
STATE = {
    "messages": [Msg("竞业限制 经济补偿", sender_type="user")],
    "conversation_id": "c1",
    "turn_id": "t1",
    "round": 1,
}
RESULTS = [
    {"source": "劳动合同法", "content": "第二十三条：竞业限制...", "score": 0.87},
    {"source": "民法典", "content": "第五百零九条...", "score": 0.62},
]


def _fake_retrieve(results=None, boom=False):
    async def retrieve(*, query, llm, top_k=5, use_hyde=True, domain="law"):
        if boom:
            raise RuntimeError("qdrant down")
        return list(results if results is not None else RESULTS)

    return retrieve


def _runner(monkeypatch, *, results=None, boom=False, store=None, emit=None):
    monkeypatch.setattr(tn, "retrieve_legal_knowledge", _fake_retrieve(results, boom))
    return ToolNodeRunner(
        llm=FakeLLMClient(),
        store=store or FakeStore(),
        emit=emit or make_emit()[1],
    )


# ============================================================
# 进度事件
# ============================================================

@pytest.mark.asyncio
async def test_tool_emits_running_then_done(monkeypatch):
    events, emit = make_emit()
    runner = _runner(monkeypatch, emit=emit)
    payload = await runner(TOOL_LAW, STATE)

    tool_events = [d for (t, d) in events if t == "tool"]
    assert [d["status"] for d in tool_events] == [TOOL_STATUS_RUNNING, TOOL_STATUS_DONE]
    run_ev = tool_events[0]
    assert run_ev["agent_id"] == "law_researcher" and run_ev["tool"] == "law"
    assert run_ev["query"] == "竞业限制 经济补偿" and run_ev["status"] == TOOL_STATUS_RUNNING
    done_ev = tool_events[1]
    assert done_ev["result_count"] == 2 and isinstance(done_ev["elapsed_ms"], int)
    assert payload["results"] == RESULTS


# ============================================================
# 引用卡：落库 + message 事件 + 领域映射
# ============================================================

@pytest.mark.asyncio
async def test_tool_produces_citation_card_law(monkeypatch):
    events, emit = make_emit()
    store = FakeStore()
    runner = _runner(monkeypatch, store=store, emit=emit)
    await runner(TOOL_LAW, STATE)

    card = store.records["t1:r1:law_researcher:0"]
    assert card["msg_type"] == MSG_TYPE_CARD
    assert card["sender_type"] == "tool" and card["sender_id"] == "law_researcher"
    assert card["metadata"]["card_type"] == "law_citation"
    assert card["metadata"]["tool_type"] == "law"
    assert len(card["metadata"]["citations"]) == 2
    assert card["metadata"]["citations"][0]["source"] == "劳动合同法"
    assert "法规检索" in card["content"]
    # 下发 message 事件（前端渲染蓝边卡）
    msg_events = [d for (t, d) in events if t == "message"]
    assert msg_events and msg_events[0]["id"] == card["id"]
    assert msg_events[0]["msg_type"] == MSG_TYPE_CARD


@pytest.mark.asyncio
async def test_tool_card_judge_domain(monkeypatch):
    store = FakeStore()
    runner = _runner(monkeypatch, store=store, emit=make_emit()[1])
    await runner(TOOL_CASE, STATE)
    card = store.records["t1:r1:case_searcher:0"]
    assert card["metadata"]["card_type"] == "case_citation"
    assert card["metadata"]["tool_type"] == "judge"


# ============================================================
# 幂等
# ============================================================

@pytest.mark.asyncio
async def test_tool_card_idempotent_reuse(monkeypatch):
    events, emit = make_emit()
    store = FakeStore()
    runner = _runner(monkeypatch, store=store, emit=emit)
    await runner(TOOL_LAW, STATE)
    n_card_events = len([d for (t, d) in events if t == "message"])
    # 重跑同轮次：复用既有卡（不新增落库），仍下发 message（幂等可回放）
    await runner(TOOL_LAW, STATE)
    assert len(store.records) == 1
    assert len([d for (t, d) in events if t == "message"]) == n_card_events + 1


# ============================================================
# 降级
# ============================================================

@pytest.mark.asyncio
async def test_tool_no_domain_or_query_skips(monkeypatch):
    events, emit = make_emit()
    runner = _runner(monkeypatch, emit=emit)
    # 未知 skill_ref → 无 domain
    await runner({"agent_id": "x", "skill_ref": "Unknown"}, STATE)
    assert events == []
    # 无 query
    empty_state = {"messages": [], "conversation_id": "c1", "turn_id": "t1", "round": 1}
    await runner(TOOL_LAW, empty_state)
    assert events == []


@pytest.mark.asyncio
async def test_tool_retrieve_error_fail_open(monkeypatch):
    events, emit = make_emit()
    store = FakeStore()
    runner = _runner(monkeypatch, boom=True, store=store, emit=emit)
    payload = await runner(TOOL_LAW, STATE)

    assert payload["results"] == []  # 降级空结果
    statuses = [d["status"] for (t, d) in events if t == "tool"]
    assert statuses == [TOOL_STATUS_RUNNING, TOOL_STATUS_ERROR]
    assert store.records == {}  # 不产出引用卡


def test_make_tool_runner_type():
    assert isinstance(make_tool_runner(llm=FakeLLMClient()), ToolNodeRunner)
