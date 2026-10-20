"""生产图全局接线测试（F8）——按模板 adapter 分派的真实件装配

对齐「生产图接线」集成项（T1.6 M3 / T1.7 遗留唯一集成项）：
`build_production_injectables` 在**同一张星型图**上按模板 `adapter` 分派
`host_advisor / scheduler / interaction_card / conclude_producer`
（`court` → T1.7 适配件；其余 → 通用件），并接线
`AgentNodeRunner`/`ToolNodeRunner`/`host_decisions` 审计落库。

全程用**假 registry + 假 LLM + 假 verdict_runner**，不依赖 DB/Redis/LLM。
"""
import sys

import pytest
from langgraph.checkpoint.memory import InMemorySaver

sys.path.insert(0, ".")

from app.services.collab.audit import record_host_decision
from app.services.collab.graph import build_collab_graph
from app.services.collab.production import build_production_injectables
from app.services.collab.registry import RegistryService
from app.services.collab.state import initial_state

INJECTABLE_KEYS = {
    "host_advisor",
    "scheduler",
    "agent_runner",
    "tool_runner",
    "decision_recorder",
    "interaction_card",
    "conclude_producer",
    "speaker_notice",
    "memory_recall",
}


# ============================================================
# 假数据 / 假件
# ============================================================

def _agent(agent_id, name, sort_order, is_tool=False):
    return {
        "agent_id": agent_id, "name": name, "avatar": None, "role_label": name,
        "description": f"{name}的职责", "skill_ref": None, "persona": "p",
        "model_pref": {}, "is_tool": is_tool, "sort_order": sort_order, "enabled": True,
    }


AGENTS = [
    _agent("legal_analyst", "法务分析师", 20),
    _agent("legal_researcher", "法规检索员", 40, is_tool=True),
    _agent("case_searcher", "类案检索员", 50, is_tool=True),
    _agent("mediator", "调解员", 60),
    _agent("plaintiff_lawyer", "原告律师", 70),
    _agent("defense_lawyer", "被告律师", 80),
    _agent("judge", "法官", 90),
    _agent("clerk", "书记员", 100),
]

# 一个 court 模板（adapter=court）+ 一个通用模板（adapter=None）——供分派判据切换
COURT_TPL = {
    "case_type": "court", "name": "模拟庭审", "icon": "gavel", "description": "d",
    "host_agent_id": "judge",
    "roster": [
        {"agent_id": "plaintiff_lawyer", "stage": "opening", "order": 1},
        {"agent_id": "defense_lawyer", "stage": "debate", "order": 2},
        {"agent_id": "clerk", "stage": "debate", "order": 3},
    ],
    "max_rounds": 3, "opening_enabled": True, "minutes_enabled": True,
    "adapter": "court", "enabled": True,
}
GENERIC_TPL = {
    "case_type": "consult", "name": "通用会商", "icon": "chat", "description": "d",
    "host_agent_id": "mediator",
    "roster": [{"agent_id": "legal_analyst", "stage": "opening", "order": 1}],
    "max_rounds": 2, "opening_enabled": True, "minutes_enabled": False,
    "adapter": None, "enabled": True,
}


def make_registry() -> RegistryService:
    async def agent_loader():
        return [dict(a) for a in AGENTS]

    async def template_loader():
        return [dict(t) for t in (COURT_TPL, GENERIC_TPL)]

    return RegistryService(agent_loader=agent_loader, template_loader=template_loader)


@pytest.fixture
def reg():
    return make_registry()


class FakeChatClient:
    """最小 LLMClient 替身：``chat`` 逐条返回预置原始文本（验证解析/修复路径）。"""

    def __init__(self, contents):
        self._contents = list(contents)
        self.calls: list[dict] = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        raw = self._contents.pop(0) if self._contents else ""
        return {"choices": [{"message": {"content": raw}}]}


def _state(case_type, *, host, roster, **kw):
    return initial_state(
        conversation_id="c1", turn_id="t1", case_type=case_type, host_agent_id=host,
        roster=roster, **kw,
    )


def _raw(directive: str, reason: str = "r") -> str:
    return f"发言正文。\n```json\n{{\"directive\": \"{directive}\", \"reason\": \"{reason}\"}}\n```"


# ============================================================
# 装配契约
# ============================================================

@pytest.mark.asyncio
async def test_injectables_keys_and_real_bindings(reg):
    inj = await build_production_injectables(registry=reg, llm=FakeChatClient([]))
    assert set(inj) == INJECTABLE_KEYS
    assert inj["decision_recorder"] is record_host_decision
    assert callable(inj["agent_runner"]) and callable(inj["tool_runner"])


# ============================================================
# host_advisor 分派：court → 法官（开放 verdict）；通用 → HostSkill（仅 conclude）
# ============================================================

@pytest.mark.asyncio
async def test_host_dispatch_court_vs_generic(reg):
    court_llm = FakeChatClient([_raw("verdict")])
    inj = await build_production_injectables(registry=reg, llm=court_llm)
    out = await inj["host_advisor"](_state("court", host="judge", roster=["plaintiff_lawyer"]))
    assert out["directive"] == "verdict" and out["parse_ok"] is True
    assert len(court_llm.calls) == 1  # court 一次成功，无修复

    # 通用 HostSkill 不开放 verdict：首条非法 → 同 super-step 修复一次 → conclude
    generic_llm = FakeChatClient([_raw("verdict"), _raw("conclude")])
    inj2 = await build_production_injectables(registry=reg, llm=generic_llm)
    out2 = await inj2["host_advisor"](_state("consult", host="mediator", roster=["legal_analyst"]))
    assert out2["directive"] == "conclude" and out2["repaired"] is True
    assert len(generic_llm.calls) == 2


# ============================================================
# scheduler 分派：court → court_scheduler（无 LLM）；通用 → SchedulerSkill（LLM）
# ============================================================

@pytest.mark.asyncio
async def test_scheduler_dispatch_court_vs_generic(reg):
    inj = await build_production_injectables(registry=reg, llm=FakeChatClient([]))
    court_state = _state("court", host="judge", roster=["plaintiff_lawyer", "defense_lawyer"])
    d = await inj["scheduler"](court_state, ["plaintiff_lawyer", "defense_lawyer"])
    assert d["next_speaker"] == "plaintiff_lawyer"  # 庭审程序：优先未陈述一方

    gen_llm = FakeChatClient(
        ['```json\n{"next_speaker": "legal_analyst", "continue_round": true, "reason": "r"}\n```']
    )
    inj2 = await build_production_injectables(registry=reg, llm=gen_llm)
    generic_state = _state("consult", host="mediator", roster=["legal_analyst"])
    d2 = await inj2["scheduler"](generic_state, ["legal_analyst"])
    assert d2["next_speaker"] == "legal_analyst"


# ============================================================
# interaction_card / conclude_producer 分派
# ============================================================

@pytest.mark.asyncio
async def test_interaction_card_dispatch(reg):
    inj = await build_production_injectables(registry=reg, llm=FakeChatClient([]))
    court_state = _state("court", host="judge", roster=["plaintiff_lawyer"])
    court_state["pending_question"] = "请补充合同"
    card = await inj["interaction_card"](court_state)
    assert card["card_type"] == "evidence_supplement"

    generic_state = _state("consult", host="mediator", roster=["legal_analyst"])
    assert await inj["interaction_card"](generic_state) == {}


@pytest.mark.asyncio
async def test_conclude_producer_dispatch(reg):
    async def fake_verdict(state):
        return "判决书正文"

    inj = await build_production_injectables(
        registry=reg, llm=FakeChatClient([]), verdict_runner=fake_verdict
    )
    verdict_state = _state("court", host="judge", roster=["plaintiff_lawyer"])
    verdict_state["force_stop_reason"] = "verdict"
    msgs = await inj["conclude_producer"](verdict_state)
    assert len(msgs) == 1 and msgs[0].content == "判决书正文"

    # court 非 verdict：不产出
    other = _state("court", host="judge", roster=["plaintiff_lawyer"])
    other["force_stop_reason"] = "no_speaker"
    assert await inj["conclude_producer"](other) == []

    # 通用模板：即使 verdict 也不产出（通用件无判决书概念）
    generic = _state("consult", host="mediator", roster=["legal_analyst"])
    generic["force_stop_reason"] = "verdict"
    assert await inj["conclude_producer"](generic) == []


# ============================================================
# 端到端：真实分派件接入图（含 async interaction_card 由 ask_user 节点 await）
# ============================================================

@pytest.mark.asyncio
async def test_production_graph_awaitable_interaction_card(reg):
    inj = await build_production_injectables(registry=reg, llm=FakeChatClient([]))

    async def advisor(state):
        return {"directive": "ask_user", "ask_user": "请补充证据材料"}

    court_graph = await build_collab_graph(
        registry=reg, **{**inj, "host_advisor": advisor}, checkpointer=InMemorySaver()
    )
    cfg = {"configurable": {"thread_id": "t1"}, "recursion_limit": 50}

    first = await court_graph.ainvoke(
        _state("court", host="judge", roster=["plaintiff_lawyer", "defense_lawyer"]),
        config=cfg,
    )
    interrupts = first.get("__interrupt__")
    assert interrupts
    value = interrupts[0].value
    assert value["question"] == "请补充证据材料"
    assert value["card_type"] == "evidence_supplement"  # 异步分派器已 await 并入

    # 通用模板：同一张图（另编译）→ 空卡片，payload 无 court 字段
    generic_state = _state("consult", host="mediator", roster=["legal_analyst"])
    generic_graph = await build_collab_graph(
        registry=reg, **{**inj, "host_advisor": advisor}, checkpointer=InMemorySaver()
    )
    first2 = await generic_graph.ainvoke(
        generic_state, config={"configurable": {"thread_id": "t2"}, "recursion_limit": 50}
    )
    assert "card_type" not in first2["__interrupt__"][0].value
