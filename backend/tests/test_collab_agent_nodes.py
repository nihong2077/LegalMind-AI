"""T1.5 Agent/Tool 节点工厂测试（注入假 LLM/假 Store/假 emit，不依赖真实模型/DB/Redis）。

覆盖计划 §3 T1.5 行验收与规格 §3.2/§4.1：
- **群上下文块**：§3.2 版式渲染（协同群/角色/指引/资料/发言记录/输出要求）；
- **零侵入 adapter**：注册表 ``skill_ref`` → 现有 9 Skill 流式方法的映射（无匹配走通用人设）；
- **S1 三事件**：``message_start`` → 多帧 ``message_delta`` → ``message_end``，token 级流式；
- **确定性幂等**：``event_key``/``message_id`` 稳定；「先查库后发」命中即复用，不重复 emit / 不重复调 LLM；
- **ON CONFLICT**：``insert_message_once`` 冲突→返回 None（不重复落库）；
- **工具辐条**：``skill_ref`` → 检索领域映射 + 异常 fail-open；
- **B1 单聊**：``direct`` 会话只驱动 ``target_agent_id`` 一条流，conclude 无主持人气泡；
- **F2 顺序气泡**：群聊发言气泡严格按模板顺序。
"""
import sys
import uuid as uuidlib

import pytest

sys.path.insert(0, ".")

from app.services.collab import agent_nodes as an
from app.services.collab import tool_nodes as tn
from app.services.collab.agent_nodes import (
    EVENT_DELTA,
    EVENT_END,
    EVENT_START,
    AgentNodeRunner,
    GroupContext,
    build_group_context,
    make_event_key,
    message_id_for,
    resolve_adapter,
)
from app.services.collab.graph import build_collab_graph
from app.services.collab.state import initial_state

from tests.test_collab_graph import AGENTS, make_registry


# ============================================================
# 假件：LLM / Store / emit
# ============================================================

class _Chunk:
    """LangChain 流式 chunk 的最小替身（仅需 ``.content``）。"""

    def __init__(self, content: str):
        self.content = content


class FakeChatModel:
    """``astream`` 逐帧产出给定文本片段（模拟 token 级流式）。"""

    def __init__(self, chunks: list[str]):
        self._chunks = list(chunks)

    async def astream(self, messages, **kwargs):  # noqa: ARG002
        for c in self._chunks:
            yield _Chunk(c)


class FakeLLMClient:
    """最小 LLMClient 替身：``get_chat_model`` 记录调用并返回 FakeChatModel。"""

    def __init__(self, chunks: list[str] | None = None):
        self._chunks = list(chunks or ["甲", "乙", "丙"])
        self.created: list[dict] = []

    def get_chat_model(self, **kwargs):
        self.created.append(kwargs)
        return FakeChatModel(self._chunks)


class FakeStore:
    """内存 Store：模拟 ``event_key`` 唯一约束（ON CONFLICT DO NOTHING）。"""

    def __init__(self):
        self.records: dict[str, dict] = {}

    async def get_message_by_event_key(self, conversation_id: str, event_key: str):
        return self.records.get(event_key)

    async def insert_message_once(self, conversation_id: str, *, event_key: str, **kw):
        if event_key in self.records:
            return None  # 冲突：不重复落库
        record = {"id": str(len(self.records) + 1), "event_key": event_key, **kw}
        self.records[event_key] = record
        return record


def make_emit() -> tuple[list[tuple[str, dict]], an.Emitter]:
    events: list[tuple[str, dict]] = []

    async def emit(conversation_id: str, event_type: str, data: dict) -> None:
        events.append((event_type, data))

    return events, emit


def _agent(agent_id: str) -> dict:
    for a in AGENTS:
        if a["agent_id"] == agent_id:
            return dict(a)
    raise KeyError(agent_id)


def _runner(**kwargs) -> AgentNodeRunner:
    return AgentNodeRunner(
        llm=kwargs.pop("llm", FakeLLMClient()),
        store=kwargs.pop("store", FakeStore()),
        registry=kwargs.pop("registry", make_registry()),
        **kwargs,
    )


def _state(**kw):
    return initial_state(
        conversation_id="c1", turn_id="t1", case_type="court",
        host_agent_id="judge", roster=["legal_analyst"], max_rounds=2,
        user_message=kw.pop("user_message", "请分析该合同是否有效"), **kw,
    )


# ============================================================
# 群上下文块（§3.2）
# ============================================================

def test_group_context_render_sections():
    ctx = GroupContext(
        case_type="court", case_type_label="模拟庭审", title="合同纠纷会商",
        question="合同是否有效？",
        transcript=[
            {"speaker_id": "plaintiff_lawyer", "speaker_name": "原告律师", "content": "主张有效"},
            {"speaker_id": "defense_lawyer", "speaker_name": "被告律师", "content": "主张无效"},
        ],
        materials="◇ 法规检索：民法典第X条",
        memories="用户为甲公司",
        host_guidance="围绕合同效力展开",
    )
    text = ctx.render()
    assert "【协同群】合同纠纷会商" in text
    assert "模拟庭审" in text
    assert "【主持人本轮指引】围绕合同效力展开" in text
    assert "【已召回的用户背景记忆】" in text and "用户为甲公司" in text
    assert "【共享资料】" in text and "民法典第X条" in text
    assert "【本轮发言记录】" in text
    assert "原告律师：主张有效" in text and "被告律师：主张无效" in text
    assert "【本轮问题】合同是否有效？" in text
    assert "【输出要求】" in text and "不要输出 JSON" in text

    assert ctx.speeches_by("plaintiff_lawyer") == ["主张有效"]
    assert ctx.speeches_by("defense_lawyer") == ["主张无效"]
    assert ctx.speeches_by("nobody") == []


def test_build_group_context_from_state():
    state = _state()
    state["host_directive"] = {"round_summary": "围绕效力与履行"}
    state["memories"] = [{"content": "用户为甲公司法定代表人"}]
    state["retrieved"] = {
        "legal_researcher": {"results": [{"title": "民法典第143条", "excerpt": "有效要件"}]}
    }
    ctx = build_group_context(_agent("legal_analyst"), state, case_type_label="模拟庭审")
    assert ctx.case_type_label == "模拟庭审"
    assert ctx.question == "请分析该合同是否有效"
    assert ctx.host_guidance == "围绕效力与履行"
    assert "用户为甲公司法定代表人" in ctx.memories
    assert "民法典第143条" in ctx.materials and "有效要件" in ctx.materials
    # 用户发言进 transcript（最新问题来源）
    assert any(e["speaker_type"] == "user" for e in ctx.transcript)


# ============================================================
# 确定性幂等键（spec §4.1）
# ============================================================

def test_event_key_and_message_id_deterministic():
    assert make_event_key("t9", 2, "judge") == "t9:r2:judge:0"
    assert make_event_key("t9", 2, "judge", 3) == "t9:r2:judge:3"
    a = message_id_for("t9:r2:judge:0")
    b = message_id_for("t9:r2:judge:0")
    assert a == b
    assert uuidlib.UUID(a).version == 5
    assert a != message_id_for("t9:r2:judge:1")


# ============================================================
# 零侵入 adapter 映射
# ============================================================

def test_resolve_adapter_mapping():
    assert resolve_adapter({"skill_ref": "LegalAnalyzer"}) is an._stream_legal_analyzer
    assert resolve_adapter({"skill_ref": "RegulatoryResearcher"}) is an._stream_regulatory_researcher
    assert resolve_adapter({"skill_ref": "PlaintiffSkill"}) is an._stream_plaintiff
    assert resolve_adapter({"skill_ref": "DefendantSkill"}) is an._stream_defendant
    assert resolve_adapter({"skill_ref": "JudgeSkill"}) is an._stream_judge
    assert resolve_adapter({"skill_ref": "MediatorSkill"}) is an._stream_mediator
    assert resolve_adapter({"skill_ref": "JudgmentReportSkill"}) is an._stream_judgment_report
    # 无现成流式方法 / 未知 skill_ref → 通用人设 adapter（S1 不破）
    assert resolve_adapter({"skill_ref": "chat_rag"}) is an._stream_generic
    assert resolve_adapter({"skill_ref": None}) is an._stream_generic
    assert resolve_adapter({"skill_ref": "ContractReviewSkill"}) is an._stream_generic


# ============================================================
# S1 三事件流式 + 幂等落库
# ============================================================

@pytest.mark.asyncio
async def test_stream_emits_start_delta_end_and_persists_once():
    llm = FakeLLMClient(["你", "好", "世界"])
    store = FakeStore()
    events, emit = make_emit()
    runner = _runner(llm=llm, store=store, emit=emit)

    agent = _agent("legal_analyst")  # skill_ref=None → 通用人设适配器
    content = await runner(agent, _state())

    assert content == "你好世界"
    types = [t for t, _ in events]
    assert types[0] == EVENT_START
    assert types[-1] == EVENT_END
    assert types.count(EVENT_DELTA) == 3

    start = events[0][1]
    assert start["event_key"] == "t1:r0:legal_analyst:0"
    assert start["message_id"] == message_id_for("t1:r0:legal_analyst:0")
    assert start["sender"] == {"type": "agent", "id": "legal_analyst", "name": "法务分析师"}

    end = events[-1][1]
    assert end["content"] == "你好世界"
    assert end["message_id"] == start["message_id"]

    # 幂等落库：恰好一条，且 content 一致
    assert len(store.records) == 1
    rec = store.records["t1:r0:legal_analyst:0"]
    assert rec["content"] == "你好世界" and rec["sender_id"] == "legal_analyst"


@pytest.mark.asyncio
async def test_event_key_hit_reuses_without_regen():
    """「先查库后发」：event_key 已存在 → 复用既有发言，不再 emit、不再调 LLM。"""
    llm = FakeLLMClient(["原始", "内容"])
    store = FakeStore()
    events, emit = make_emit()
    runner = _runner(llm=llm, store=store, emit=emit)
    agent = _agent("legal_analyst")
    state = _state()

    first = await runner(agent, state)
    created_after_first = len(llm.created)
    emitted_after_first = len(events)
    assert first == "原始内容"

    second = await runner(agent, state)  # 同一 turn/round/agent → 同一 event_key
    assert second == "原始内容"                       # 复用既有内容
    assert len(llm.created) == created_after_first     # 未再调 LLM
    assert len(events) == emitted_after_first          # 未再 emit


@pytest.mark.asyncio
async def test_insert_message_once_conflict_returns_none():
    """ON CONFLICT DO NOTHING：同一 event_key 二次写入返回 None。"""
    store = FakeStore()
    kw = dict(
        sender_type="agent", sender_id="judge", sender_name="法官",
        content="裁决", msg_type="text", round=1, metadata={},
    )
    first = await store.insert_message_once("c1", event_key="t1:r1:judge:0", **kw)
    second = await store.insert_message_once("c1", event_key="t1:r1:judge:0", **kw)
    assert first is not None and second is None
    assert len(store.records) == 1


@pytest.mark.asyncio
async def test_adapters_invoke_existing_skills(monkeypatch):
    """零侵入：已验证适配器把群上下文块映射到现有 Skill 流式方法入参。"""
    captured: dict[str, dict] = {}

    async def fake_analyze_stream(self, query, context=""):
        captured["legal"] = {"query": query, "context": context}
        yield "分析结果"

    async def fake_research_stream(self, query, area=""):
        captured["research"] = {"query": query, "area": area}
        yield "检索结果"

    monkeypatch.setattr(an.LegalAnalyzer, "analyze_stream", fake_analyze_stream)
    monkeypatch.setattr(an.RegulatoryResearcher, "research_stream", fake_research_stream)

    ctx = GroupContext(
        case_type="court", case_type_label="模拟庭审", title="会商",
        question="竞业限制是否有效", materials="◇ 民法典第X条",
    )
    model = FakeChatModel([])

    out = "".join([c async for c in an._stream_legal_analyzer(_agent("legal_analyst"), ctx, model)])
    assert out == "分析结果"
    assert "【协同群】" in captured["legal"]["query"]
    assert "【本轮问题】竞业限制是否有效" in captured["legal"]["query"]
    assert captured["legal"]["context"] == "◇ 民法典第X条"

    out2 = "".join([c async for c in an._stream_regulatory_researcher(_agent("legal_researcher"), ctx, model)])
    assert out2 == "检索结果"
    assert captured["research"]["area"] == "模拟庭审"


# ============================================================
# 工具辐条：领域映射 + fail-open
# ============================================================

@pytest.mark.asyncio
async def test_tool_runner_domain_mapping_and_fail_open(monkeypatch):
    calls: list[dict] = []

    async def fake_retrieve(*, query, llm, top_k, use_hyde, domain):  # noqa: ARG001
        calls.append({"query": query, "domain": domain, "top_k": top_k})
        if domain == "judge":
            raise RuntimeError("类案检索炸了")
        return [{"title": "民法典第1条", "excerpt": "x"}]

    monkeypatch.setattr(tn, "retrieve_legal_knowledge", fake_retrieve)
    runner = tn.ToolNodeRunner(llm=FakeLLMClient([]), top_k=3, store=FakeStore(), emit=make_emit()[1])
    state = _state(user_message="竞业限制条款是否有效")

    law_tool = {"agent_id": "legal_researcher", "skill_ref": "RegulatoryResearcher"}
    out = await runner(law_tool, state)
    assert calls[-1]["domain"] == "law" and calls[-1]["top_k"] == 3
    assert out["tool_id"] == "legal_researcher" and out["results"]

    judge_tool = {"agent_id": "case_searcher", "skill_ref": "CaseSearchSkill"}
    out2 = await runner(judge_tool, state)
    assert calls[-1]["domain"] == "judge"
    assert out2["results"] == []  # 失败降级：空结果，不抛异常

    # 未知 skill_ref → 不触发检索
    before = len(calls)
    out3 = await runner({"agent_id": "ghost", "skill_ref": "UnknownSkill"}, state)
    assert out3["results"] == [] and len(calls) == before


# ============================================================
# 图级：B1 单聊 / F2 顺序气泡
# ============================================================

async def _build(reg, **kwargs):
    return await build_collab_graph(registry=reg, **kwargs)


@pytest.mark.asyncio
async def test_direct_conversation_only_drives_target_agent():
    """B1：direct 会话只调 target_agent_id 一条流，conclude 无主持人气泡。"""
    async def fake_agent_runner(agent, state):  # noqa: ARG001
        return f"reply-from-{agent['agent_id']}"

    g = await _build(make_registry(), agent_runner=fake_agent_runner)
    state = initial_state(
        conversation_id="c1", turn_id="t1", case_type="", host_agent_id="",
        roster=["mediator"], conv_type="direct", target_agent_id="mediator",
        user_message="你好",
    )
    result = await g.ainvoke(state, config={"recursion_limit": 50})

    spoken = [
        m.additional_kwargs["agent_id"]
        for m in result["messages"]
        if m.additional_kwargs.get("sender_type") == "agent"
    ]
    assert spoken == ["mediator"]  # 只出目标 Agent 一条流
    assert result["force_stop_reason"] == "direct_done"
    # 无主持人 → conclude 不产生「宣布结束」气泡
    assert not [
        m for m in result["messages"]
        if m.additional_kwargs.get("sender_type") == "host"
    ]


@pytest.mark.asyncio
async def test_group_bubbles_in_template_order():
    """F2：群聊发言气泡严格按模板默认顺序串行产出。"""
    async def fake_agent_runner(agent, state):  # noqa: ARG001
        return f"发言-{agent['agent_id']}"

    g = await _build(make_registry(), agent_runner=fake_agent_runner)
    state = initial_state(
        conversation_id="c1", turn_id="t1", case_type="court", host_agent_id="judge",
        roster=["plaintiff_lawyer", "defense_lawyer", "clerk"], max_rounds=4,
        user_message="请开始庭审",
    )
    result = await g.ainvoke(state, config={"recursion_limit": 50})

    agent_msgs = [
        m for m in result["messages"]
        if m.additional_kwargs.get("sender_type") == "agent"
    ]
    assert [m.additional_kwargs["agent_id"] for m in agent_msgs] == [
        "plaintiff_lawyer", "defense_lawyer", "clerk"
    ]
    assert [m.content for m in agent_msgs] == [
        "发言-plaintiff_lawyer", "发言-defense_lawyer", "发言-clerk"
    ]
