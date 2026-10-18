"""发言前置联网决策单元测试（P2-WebSearch Step2，假 LLM/客户端/Store/Emitter）。

覆盖：
- 开关：``enabled=False`` → 零 LLM/零网络/零事件；
- 决策：无需检索（无 tool_calls）→ 空串、无产物；
- 搜索：tool 事件（running/done）+ 联网引用卡（``card_type=web_citation``，
  ``event_key={turn}:r{round}:{agent}:web`` 幂等）+ 资料块；
- 抓取：``web_fetch`` → 走 ``fetch_url``；
- 幂等：重跑复用既有引用卡，不重复落库；
- 降级：决策/检索异常 → 返回空串且不抛出（照常发言）；
- 接线：``AgentNodeRunner`` 把资料块并入 ``ctx.materials``（零侵入）。
"""
import sys

import pytest

sys.path.insert(0, ".")

from app.services.collab.agent_nodes import AgentNodeRunner, GroupContext  # noqa: E402
from app.services.collab.registry import RegistryService  # noqa: E402
from app.services.collab.web_decision import (  # noqa: E402
    CARD_TYPE_WEB,
    TOOL_WEB_FETCH,
    TOOL_WEB_SEARCH,
    make_web_context,
)


# ============================================================
# 假件
# ============================================================

class FakeStore:
    def __init__(self):
        self.records: dict[str, dict] = {}

    async def get_message_by_event_key(self, conversation_id, event_key):
        return self.records.get(event_key)

    async def insert_message_once(self, conversation_id, *, event_key, **kw):
        if event_key in self.records:
            return None
        record = {"id": f"m{len(self.records) + 1}", "event_key": event_key, **kw}
        self.records[event_key] = record
        return record


class _Resp:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


class _FakeModel:
    def __init__(self, tool_calls, raise_on_invoke=False):
        self._tc = tool_calls
        self._raise = raise_on_invoke
        self.bound_tools = None
        self.messages = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        if self._raise:
            raise RuntimeError("llm down")
        return _Resp(self._tc)


class FakeLLM:
    def __init__(self, tool_calls=None, raise_on_invoke=False):
        self.tool_calls = tool_calls or []
        self.raise_on_invoke = raise_on_invoke
        self.model_calls: list[dict] = []
        self.model: _FakeModel | None = None

    def get_chat_model(self, model="", temperature=0.0, max_tokens=0, streaming=False):
        self.model_calls.append({"model": model, "temperature": temperature})
        self.model = _FakeModel(self.tool_calls, self.raise_on_invoke)
        return self.model


class FakeWebClient:
    def __init__(self, results=None, fetched=None, raise_on_search=False):
        self.results = results or []
        self.fetched = fetched or {}
        self.raise_on_search = raise_on_search
        self.search_calls: list[dict] = []
        self.fetch_calls: list[str] = []

    async def search_web(self, query, *, ori_question=None, need_content=None,
                         localization=None, site=None, top_n=None):
        if self.raise_on_search:
            raise RuntimeError("web down")
        self.search_calls.append({"query": query, "top_n": top_n, "ori_question": ori_question})
        return self.results

    async def fetch_url(self, url):
        self.fetch_calls.append(url)
        return self.fetched


def make_emit():
    events = []

    async def emit(conversation_id, event_type, data):
        events.append((event_type, data))

    return events, emit


AGENT = {"agent_id": "agent1", "name": "原告律师", "model_pref": {}, "skill_ref": None}
STATE = {"conversation_id": "c1", "turn_id": "t1", "round": 1}
CTX = GroupContext(
    case_type="consult", case_type_label="通用会商", title="演示",
    question="最新的彩礼返还司法解释是什么？",
)

RESULTS = [
    {"title": "彩礼返还司法解释", "url": "https://a.example/1", "content": "正文A",
     "snippet": "摘要A", "site_name": "法院网", "date": "2024-01-01", "rerank_score": 0.9},
    {"title": "相关批复", "url": "https://b.example/2", "content": "正文B",
     "snippet": "摘要B", "site_name": "普法网", "date": "2023-05-01", "rerank_score": 0.8},
]


def _provider(llm, client, store, emit, **kw):
    return make_web_context(llm=llm, store=store, emit=emit, client=client, **kw)


def _search_call(query="彩礼 司法解释"):
    return [{"name": TOOL_WEB_SEARCH, "args": {"query": query}}]


# ============================================================
# 开关 / 决策
# ============================================================

@pytest.mark.asyncio
async def test_disabled_short_circuits():
    llm, store = FakeLLM(_search_call()), FakeStore()
    events, emit = make_emit()
    p = _provider(llm, FakeWebClient(RESULTS), store, emit, enabled=False)
    assert await p.maybe_search(AGENT, STATE, CTX, "c1") == ""
    assert llm.model_calls == [] and events == [] and store.records == {}


@pytest.mark.asyncio
async def test_no_search_decision_is_noop():
    llm, store = FakeLLM(None), FakeStore()
    events, emit = make_emit()
    p = _provider(llm, FakeWebClient(RESULTS), store, emit)
    assert await p.maybe_search(AGENT, STATE, CTX, "c1") == ""
    assert llm.model_calls and events == [] and store.records == {}
    # 决策调用绑定了两个 function schema
    assert {t["function"]["name"] for t in llm.model.bound_tools} == {TOOL_WEB_SEARCH, TOOL_WEB_FETCH}


@pytest.mark.asyncio
async def test_empty_question_skips():
    llm, store = FakeLLM(_search_call()), FakeStore()
    events, emit = make_emit()
    p = _provider(llm, FakeWebClient(RESULTS), store, emit)
    ctx = GroupContext(case_type="consult", case_type_label="", title="t", question="")
    assert await p.maybe_search(AGENT, STATE, ctx, "c1") == ""
    assert llm.model_calls == []


# ============================================================
# 搜索 → 事件 + 引用卡 + 资料块
# ============================================================

@pytest.mark.asyncio
async def test_search_emits_events_card_and_materials():
    llm, store = FakeLLM(_search_call()), FakeStore()
    events, emit = make_emit()
    client = FakeWebClient(RESULTS)
    p = _provider(llm, client, store, emit)

    block = await p.maybe_search(AGENT, STATE, CTX, "c1")

    assert "【联网检索资料】" in block and "彩礼返还司法解释" in block
    assert client.search_calls[0]["query"] == "彩礼 司法解释"

    types = [e[0] for e in events]
    assert types.count("tool") == 2 and types.count("message") == 1
    tool_events = [e[1] for e in events if e[0] == "tool"]
    assert {t["status"] for t in tool_events} == {"running", "done"}
    assert all(t["tool"] == TOOL_WEB_SEARCH for t in tool_events)
    assert tool_events[-1]["result_count"] == 2

    card = store.records["t1:r1:agent1:web"]
    assert card["sender_type"] == "tool" and card["msg_type"] == "card"
    assert card["metadata"]["card_type"] == CARD_TYPE_WEB
    assert card["metadata"]["citations"][0]["url"] == "https://a.example/1"
    assert card["round"] == 1


@pytest.mark.asyncio
async def test_fetch_decision_uses_fetch_url():
    llm = FakeLLM([{"name": TOOL_WEB_FETCH, "args": {"url": "https://x.example/p"}}])
    store = FakeStore()
    events, emit = make_emit()
    client = FakeWebClient(fetched={"url": "https://x.example/p", "title": "某页", "content": "网页正文"})
    p = _provider(llm, client, store, emit)

    block = await p.maybe_search(AGENT, STATE, CTX, "c1")

    assert client.fetch_calls == ["https://x.example/p"]
    assert "网页正文" in block
    tool_events = [e[1] for e in events if e[0] == "tool"]
    assert all(t["tool"] == TOOL_WEB_FETCH for t in tool_events)
    assert "t1:r1:agent1:web" in store.records


@pytest.mark.asyncio
async def test_card_idempotent_on_rerun():
    llm, store = FakeLLM(_search_call()), FakeStore()
    events, emit = make_emit()
    p = _provider(llm, FakeWebClient(RESULTS), store, emit)

    await p.maybe_search(AGENT, STATE, CTX, "c1")
    await p.maybe_search(AGENT, STATE, CTX, "c1")

    assert len(store.records) == 1  # 不重复落库
    assert len([e for e in events if e[0] == "message"]) == 2  # 复用既有卡重发


# ============================================================
# 降级（fail-open）
# ============================================================

@pytest.mark.asyncio
async def test_search_error_fail_open():
    llm, store = FakeLLM(_search_call()), FakeStore()
    events, emit = make_emit()
    client = FakeWebClient(RESULTS, raise_on_search=True)
    p = _provider(llm, client, store, emit)

    assert await p.maybe_search(AGENT, STATE, CTX, "c1") == ""  # 不抛出
    assert store.records == {}
    tool_events = [e[1] for e in events if e[0] == "tool"]
    assert tool_events[-1]["status"] == "error"


@pytest.mark.asyncio
async def test_decision_error_fail_open():
    llm, store = FakeLLM(_search_call(), raise_on_invoke=True), FakeStore()
    events, emit = make_emit()
    p = _provider(llm, FakeWebClient(RESULTS), store, emit)
    assert await p.maybe_search(AGENT, STATE, CTX, "c1") == ""
    assert events == [] and store.records == {}


# ============================================================
# 接线：AgentNodeRunner 把资料块并入 ctx.materials
# ============================================================

class _CaptureRunner(AgentNodeRunner):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.captured: dict[str, str] = {}

    def _stream(self, agent, ctx):
        self.captured["materials"] = ctx.materials

        async def gen():
            yield "我的发言"

        return gen()


class _FakeWebProvider:
    def __init__(self, block):
        self.block = block
        self.calls = []

    async def maybe_search(self, agent, state, ctx, conversation_id):
        self.calls.append((agent["agent_id"], conversation_id))
        return self.block


def _registry():
    async def agent_loader():
        return [dict(AGENT)]

    async def template_loader():
        return []

    return RegistryService(agent_loader=agent_loader, template_loader=template_loader)


@pytest.mark.asyncio
async def test_agent_runner_augments_materials_zero_invasive():
    store = FakeStore()
    events, emit = make_emit()
    provider = _FakeWebProvider("【联网检索资料】\n 1. 测试资料")
    runner = _CaptureRunner(
        llm=FakeLLM(None), store=store, registry=_registry(), emit=emit, web=provider
    )
    state = {"conversation_id": "c1", "turn_id": "t1", "round": 1, "case_type": "consult"}

    out = await runner(AGENT, state)

    assert out == "我的发言"
    assert provider.calls == [("agent1", "c1")]
    assert "【联网检索资料】" in runner.captured["materials"]  # 已并入、供 Skill 消费
    assert store.records["t1:r1:agent1:0"]["content"] == "我的发言"  # 原流式发言不破


@pytest.mark.asyncio
async def test_agent_runner_without_web_unchanged():
    store = FakeStore()
    events, emit = make_emit()
    runner = _CaptureRunner(llm=FakeLLM(None), store=store, registry=_registry(), emit=emit)
    state = {"conversation_id": "c1", "turn_id": "t1", "round": 1, "case_type": "consult"}
    assert await runner(AGENT, state) == "我的发言"
    assert runner.captured["materials"] == ""  # 未注入 → 行为不变
