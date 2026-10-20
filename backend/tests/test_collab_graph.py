"""T1.3 星型图结构与护栏测试（注入假注册表 + 假回调，不依赖 DB/LLM）。

验收对齐计划 §3 T1.3 行与规格 §2.1/§2.4/§2.6：
- 无 host → 业务节点的固定边（走向全部运行时决定）；
- scheduler 为隐藏内部节点：不在 agent_registry、不出现在白名单；
- 三类护栏：跳转白名单 / max_rounds 硬顶 / 排序失败降级兜底（D15③）；
- 每个辐条 → host 的固定回边；ask_user 走原生 interrupt()。
"""
import sys

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

sys.path.insert(0, ".")

from app.services.collab import graph as graph_mod
from app.services.collab.graph import (
    ASK_USER_NODE,
    CONCLUDE_NODE,
    HOST_NODE,
    SCHEDULER_NODE,
    agent_node_name,
    build_collab_graph,
    tool_node_name,
)
from app.services.collab.registry import RegistryService
from app.services.collab.state import initial_state


# ============================================================
# 假数据（与 05-seed 同构的精简版）
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

TEMPLATES = [
    {
        "case_type": "court", "name": "模拟庭审", "icon": "gavel", "description": "d",
        "host_agent_id": "judge",
        "roster": [
            {"agent_id": "plaintiff_lawyer", "stage": "opening", "order": 1},
            {"agent_id": "defense_lawyer", "stage": "debate", "order": 2},
            {"agent_id": "clerk", "stage": "debate", "order": 3},
        ],
        "max_rounds": 3, "opening_enabled": True, "minutes_enabled": True,
        "adapter": "court", "enabled": True,
    },
]

SPEAKING = ["legal_analyst", "mediator", "plaintiff_lawyer", "defense_lawyer", "judge", "clerk"]
TOOLS = ["legal_researcher", "case_searcher"]


def make_registry() -> RegistryService:
    async def agent_loader():
        return [dict(a) for a in AGENTS]

    async def template_loader():
        return [dict(t) for t in TEMPLATES]

    return RegistryService(agent_loader=agent_loader, template_loader=template_loader)


@pytest.fixture
def reg():
    return make_registry()


async def _build(reg, **kwargs):
    return await build_collab_graph(registry=reg, **kwargs)


# ============================================================
# 图结构评审
# ============================================================

@pytest.mark.asyncio
async def test_agent_and_tool_nodes_from_registry(reg):
    g = await _build(reg)
    nodes = set(g.builder.nodes)
    for a in SPEAKING:
        assert agent_node_name(a) in nodes
    for t in TOOLS:
        assert tool_node_name(t) in nodes
    assert {ASK_USER_NODE, CONCLUDE_NODE, HOST_NODE, SCHEDULER_NODE} <= nodes


@pytest.mark.asyncio
async def test_no_fixed_edge_from_host_or_scheduler(reg):
    """host 与 scheduler 的去向必须 100% 由运行时 Command(goto=) 决定。"""
    g = await _build(reg)
    edges = g.builder.edges
    assert not [e for e in edges if e[0] == HOST_NODE]
    assert not [e for e in edges if e[0] == SCHEDULER_NODE]


@pytest.mark.asyncio
async def test_only_spoke_to_host_return_edges(reg):
    """固定回边：所有辐条 / ask_user → host；无其它业务固定边。"""
    g = await _build(reg)
    targets_by_source: dict[str, set[str]] = {}
    for src, dst in g.builder.edges:
        targets_by_source.setdefault(src, set()).add(dst)
    for a in SPEAKING:
        assert targets_by_source[agent_node_name(a)] == {HOST_NODE}
    for t in TOOLS:
        assert targets_by_source[tool_node_name(t)] == {HOST_NODE}
    assert targets_by_source[ASK_USER_NODE] == {HOST_NODE}


@pytest.mark.asyncio
async def test_scheduler_is_hidden_internal_node(reg):
    """scheduler 不进 agent_registry、不在任何可见名单里（D14）。"""
    g = await _build(reg)
    assert SCHEDULER_NODE in set(g.builder.nodes)
    registry_ids = {a["agent_id"] for a in await reg.all_agents()}
    assert SCHEDULER_NODE not in registry_ids
    assert HOST_NODE not in registry_ids
    assert graph_mod.HIDDEN_INTERNAL_NODES == (SCHEDULER_NODE,)


# ============================================================
# 运行：模板默认顺序 + 收敛
# ============================================================

async def _run(reg, *, roster, host="judge", max_rounds=3, **kwargs):
    g = await _build(reg, **kwargs)
    state = initial_state(
        conversation_id="c1", turn_id="t1", case_type="court",
        host_agent_id=host, roster=roster, max_rounds=max_rounds,
        user_message="请开始庭审",
    )
    result = await g.ainvoke(state, config={"recursion_limit": 50})
    return g, result


def _spoken(result):
    return [
        m.additional_kwargs["agent_id"]
        for m in result["messages"]
        if m.additional_kwargs.get("sender_type") == "agent"
    ]


@pytest.mark.asyncio
async def test_default_order_and_converge(reg):
    _, result = await _run(
        reg, roster=["plaintiff_lawyer", "defense_lawyer", "clerk"], max_rounds=4
    )
    assert _spoken(result) == ["plaintiff_lawyer", "defense_lawyer", "clerk"]
    assert result["force_stop_reason"] == "no_speaker"
    # 决策审计：3 次派发 + 1 次收敛，全部落 events（D15②）
    kinds = [e["kind"] for e in result["events"]]
    assert kinds.count("scheduler") == 4


@pytest.mark.asyncio
async def test_max_rounds_hard_cap(reg):
    """max_rounds=2：第 3 次进入 host 被护栏强制 goto conclude。"""
    _, result = await _run(reg, roster=["plaintiff_lawyer", "defense_lawyer", "clerk"], max_rounds=2)
    assert _spoken(result) == ["plaintiff_lawyer", "defense_lawyer"]
    assert result["force_stop_reason"] == "max_rounds"


@pytest.mark.asyncio
async def test_host_verdict_goes_conclude(reg):
    async def advisor(state):
        return {"directive": "verdict", "reason": "事实清楚，可以裁决"}

    _, result = await _run(reg, roster=["plaintiff_lawyer"], host_advisor=advisor)
    assert _spoken(result) == []
    assert result["force_stop_reason"] == "verdict"


@pytest.mark.asyncio
async def test_scheduler_out_of_whitelist_falls_back(reg):
    """越权目标 → 白名单护栏否决 +回落模板顺序，且 rejection_reason 落审计。"""
    async def bad_scheduler(state, candidates):
        return {"next_speaker": "ghost_agent", "continue_round": True}

    _, result = await _run(
        reg, roster=["plaintiff_lawyer", "defense_lawyer"], scheduler=bad_scheduler, max_rounds=2
    )
    assert _spoken(result) == ["plaintiff_lawyer", "defense_lawyer"]  # 未被 ghost 带偏
    rejected = [e for e in result["events"] if e.get("rejection_reason") == "invalid_target"]
    assert rejected and rejected[0]["accepted"] is False


@pytest.mark.asyncio
async def test_scheduler_failure_degrades_without_breaking_turn(reg):
    """D15③：排序智能体抛异常 → 降级模板默认顺序，整轮不中断。"""
    async def broken(state, allowed):
        raise RuntimeError("scheduler boom")

    _, result = await _run(
        reg, roster=["plaintiff_lawyer", "defense_lawyer"], scheduler=broken, max_rounds=2
    )
    assert _spoken(result) == ["plaintiff_lawyer", "defense_lawyer"]
    assert result["scheduler_directive"].get("degraded") is True


@pytest.mark.asyncio
async def test_whitelist_excludes_removed_and_host(reg):
    """移除成员即时生效；主持人自身不作为辐条被点。"""
    async def greedy_scheduler(state, candidates):
        return {"next_speaker": "defense_lawyer", "continue_round": True}

    _, result = await _run(
        reg,
        roster=["plaintiff_lawyer", "judge"],  # 只留原告与主持人
        host="judge",
        scheduler=greedy_scheduler,
        max_rounds=2,
    )
    assert _spoken(result) == ["plaintiff_lawyer"]  # defense_lawyer 已不在群，被护栏挡掉
    assert "defense_lawyer" not in _spoken(result)


# ============================================================
# ask_user：原生 interrupt() 暂停与 resume
# ============================================================

@pytest.mark.asyncio
async def test_ask_user_interrupt_and_resume(reg):
    """host 判定 ask_user → 原生 interrupt() 暂停；resume 后从 ask_user 之后续跑。"""
    async def advisor(state):
        already_resumed = any(
            getattr(m, "additional_kwargs", {}).get("resume_after_interrupt")
            for m in state.get("messages", [])
        )
        if already_resumed:
            return {"directive": "conclude", "reason": "已补证，直接出具阶段性意见"}
        return {"directive": "ask_user", "ask_user": "请补充证据材料"}

    g = await _build(reg, host_advisor=advisor, checkpointer=InMemorySaver())
    state = initial_state(
        conversation_id="c1", turn_id="t1", case_type="court",
        host_agent_id="judge", roster=["plaintiff_lawyer"], max_rounds=3,
        user_message="请开始",
    )
    cfg = {"configurable": {"thread_id": "t1"}, "recursion_limit": 50}

    first = await g.ainvoke(state, config=cfg)
    interrupts = first.get("__interrupt__")
    assert interrupts, "ask_user 节点应抛出 interrupt"
    assert interrupts[0].value["question"] == "请补充证据材料"

    resumed = await g.ainvoke(Command(resume="补充：合同复印件一份"), config=cfg)
    assert not resumed.get("__interrupt__")  # 恢复后不再中断
    assert resumed["force_stop_reason"] == "conclude"
    user_msgs = [
        m for m in resumed["messages"]
        if m.additional_kwargs.get("resume_after_interrupt")
    ]
    assert user_msgs and "合同复印件" in user_msgs[0].content

@pytest.mark.asyncio
async def test_ask_user_resume_conclude_injects_goto(reg):
    """用户主权（F6）：在 ask_user 挂起时以 conclude 结束 → 直接跳 conclude 收尾。"""
    async def advisor(state):  # noqa: ARG001
        return {"directive": "ask_user", "ask_user": "请补充证据材料"}

    g = await _build(reg, host_advisor=advisor, checkpointer=InMemorySaver())
    state = initial_state(
        conversation_id="c1", turn_id="t1c", case_type="court",
        host_agent_id="judge", roster=["plaintiff_lawyer"], max_rounds=3,
        user_message="请开始",
    )
    cfg = {"configurable": {"thread_id": "t1c"}, "recursion_limit": 50}

    first = await g.ainvoke(state, config=cfg)
    assert first.get("__interrupt__"), "ask_user 节点应抛出 interrupt"

    resumed = await g.ainvoke(Command(resume={"action": "conclude"}), config=cfg)
    assert not resumed.get("__interrupt__")
    assert resumed["force_stop_reason"] == "user_conclude"
    # 控制动作不应被当作补证内容写进 transcript
    assert not any(
        m.additional_kwargs.get("resume_after_interrupt") for m in resumed["messages"]
    )


@pytest.mark.asyncio
async def test_takeover_resume_conclude_injects_goto(reg):
    """用户主权（F6）：轮到本人扮演时选择「结束会商」→ 直接跳 conclude 收尾。"""
    async def advisor(state):  # noqa: ARG001
        return {"directive": "continue", "reason": "ok"}

    async def sched(state, candidates):  # noqa: ARG001
        return {"next_speaker": "plaintiff_lawyer", "continue_round": True, "reason": "r"}

    g = await _build(reg, host_advisor=advisor, scheduler=sched, checkpointer=InMemorySaver())
    state = initial_state(
        conversation_id="c2", turn_id="t2c", case_type="court",
        host_agent_id="judge", roster=["plaintiff_lawyer"], max_rounds=3,
        my_role="plaintiff_lawyer", user_message="请开始",
    )
    cfg = {"configurable": {"thread_id": "t2c"}, "recursion_limit": 50}

    first = await g.ainvoke(state, config=cfg)
    assert first.get("__interrupt__"), "接管应中断"
    assert first["__interrupt__"][0].value["type"] == "takeover"

    resumed = await g.ainvoke(Command(resume={"action": "conclude"}), config=cfg)
    assert not resumed.get("__interrupt__")
    assert resumed["force_stop_reason"] == "user_conclude"

@pytest.mark.asyncio
async def test_tool_spokes_prefetched_at_round_head(reg):
    """T1.9-M3：轮首**并行预取**工具辐条——工具成员在 prepare 即被调用，
    不占主串行发言位（scheduling_spec §1④/§3.1）。"""
    calls: list[str] = []

    async def fake_tool_runner(tool, state):
        calls.append(tool["agent_id"])
        return {
            "tool_id": tool["agent_id"],
            "query": "竞业限制",
            "results": [{"source": "劳动合同法", "content": "第二十三条…", "score": 0.9}],
        }

    _, result = await _run(
        reg,
        roster=["plaintiff_lawyer", "legal_researcher"],  # legal_researcher 为 is_tool 成员
        tool_runner=fake_tool_runner,
        max_rounds=1,
    )
    # 预取发生（且只发生一次），图谱证据入 retrieved
    assert calls == ["legal_researcher"]
    assert result["retrieved"]["legal_researcher"]["results"][0]["source"] == "劳动合同法"
    # 检索员不占串行发言位：max_rounds=1 只够原告一人发言
    assert _spoken(result) == ["plaintiff_lawyer"]
    assert "legal_researcher" not in _spoken(result)


@pytest.mark.asyncio
async def test_tool_spokes_not_prefetched_when_not_member(reg):
    """非群成员的工具 Agent 不预取（避免无必要检索开销）。"""
    calls: list[str] = []

    async def fake_tool_runner(tool, state):
        calls.append(tool["agent_id"])
        return {"agent_id": tool["agent_id"], "query": "", "results": []}

    _, result = await _run(
        reg,
        roster=["plaintiff_lawyer"],  # 不含任何 is_tool 成员
        tool_runner=fake_tool_runner,
        max_rounds=1,
    )
    assert calls == []
    assert not (result.get("retrieved") or {})


# ============================================================
# T2.3：prepare 节点记忆召回接线（零侵入 + fail-open）
# ============================================================

@pytest.mark.asyncio
async def test_memory_recall_wired_into_prepare(reg):
    """注入 memory_recall → prepare 调用一次，结果落 state.memories。"""
    calls: list[dict] = []

    async def recall(state):
        calls.append(state)
        return {"memories": [{"id": "m1", "content": "用户偏好调解", "status": "active"}]}

    _, result = await _run(
        reg, roster=["plaintiff_lawyer"], max_rounds=1, memory_recall=recall
    )
    assert len(calls) == 1  # 每轮仅调用一次
    assert result["memories"][0]["content"] == "用户偏好调解"
    assert _spoken(result) == ["plaintiff_lawyer"]  # 召回不影响正常编排


@pytest.mark.asyncio
async def test_memory_recall_failure_fail_open(reg):
    """召回件抬异常 → 不阻断整轮（图节点 fail-open）。"""

    async def boom(state):  # noqa: ARG001
        raise RuntimeError("recall down")

    _, result = await _run(
        reg, roster=["plaintiff_lawyer"], max_rounds=1, memory_recall=boom
    )
    assert _spoken(result) == ["plaintiff_lawyer"]
    assert result.get("memories") in (None, [])  # 未注入记忆
