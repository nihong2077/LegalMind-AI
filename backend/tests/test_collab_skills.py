"""T1.4 HostSkill + SchedulerSkill 测试（注入假 LLM/假注册表，不依赖 DB/网络）。

覆盖计划 §3 T1.4 行验收（F13）与规格 §2.4：
- 容错提取（```json 代码块 / 裸 JSON / 夹带自然语言）；
- host 双输出：口语发言与指令 JSON 分离（JSON 绝不外泄，S1）；
- 护栏③：格式/枚举非法 → 同 super-step 内反馈修复一次；
- 护栏④ / F13：连续两次非法 → 兜底 conclude，全程无异常栈；
- scheduler 白名单校验 + 越权重调一次 + 连续两次非法收敛；
- scheduler **不产生气泡、不在 agent_registry**；
- 审计落库 fail-open（不阻断整轮）。
"""
import uuid as uuidlib

import pytest

from app.services.collab import audit as audit_mod
from app.services.collab.host_skill import HostSkill
from app.services.collab.prompts import extract_json_object, split_utterance_and_json
from app.services.collab.registry import RegistryService
from app.services.collab.scheduler_skill import SchedulerSkill
from app.services.collab.state import initial_state

from tests.test_collab_graph import AGENTS, build_collab_graph


# ============================================================
# 假数据 / 假 LLM
# ============================================================

def _template(case_type, host_agent_id, roster, adapter, max_rounds=3):
    return {
        "case_type": case_type, "name": f"{case_type} 模板", "icon": None, "description": "d",
        "host_agent_id": host_agent_id,
        "roster": [{"agent_id": a, "stage": "s", "order": i} for i, a in enumerate(roster, 1)],
        "max_rounds": max_rounds, "opening_enabled": True, "minutes_enabled": True,
        "adapter": adapter, "enabled": True,
    }


TEMPLATES = [
    _template("court", "judge", ["plaintiff_lawyer", "defense_lawyer", "clerk"], "court"),
    _template("contract", "mediator", ["legal_analyst"], "generic"),
]


def make_registry() -> RegistryService:
    async def agent_loader():
        return [dict(a) for a in AGENTS]

    async def template_loader():
        return [dict(t) for t in TEMPLATES]

    return RegistryService(agent_loader=agent_loader, template_loader=template_loader)


class FakeLLM:
    """按顺序返回固定 content；元素为 Exception 时抛出（模拟 LLM 失败）。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, *, model, messages, temperature=0.0, max_tokens=0):
        self.calls.append({"model": model, "messages": messages,
                           "temperature": temperature, "max_tokens": max_tokens})
        item = self._responses.pop(0) if self._responses else ""
        if isinstance(item, Exception):
            raise item
        return {"choices": [{"message": {"content": item}}]}


def _state(case_type="court", host="judge", roster=None, max_rounds=3, **kw):
    return initial_state(
        conversation_id="c1", turn_id="t1", case_type=case_type,
        host_agent_id=host, roster=roster or ["plaintiff_lawyer", "defense_lawyer"],
        max_rounds=max_rounds, user_message="请开始", **kw,
    )


# ============================================================
# 容错提取
# ============================================================

def test_extract_json_tolerance():
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object('前缀 {"directive": "conclude"} 后缀') == {"directive": "conclude"}
    assert extract_json_object("完全没有 JSON") is None
    # 嵌套对象取最外层可解析对象
    nested = extract_json_object('说明 {"outer": {"inner": 1}, "d": "x"} 结束')
    assert nested == {"outer": {"inner": 1}, "d": "x"}


def test_split_utterance_strips_json():
    text = '现在开庭。\n```json\n{"directive": "continue", "reason": "r"}\n```'
    utterance, obj, raw = split_utterance_and_json(text)
    assert obj == {"directive": "continue", "reason": "r"}
    assert utterance == "现在开庭。"
    assert "{" not in utterance and raw in text


# ============================================================
# HostSkill
# ============================================================

@pytest.mark.asyncio
async def test_host_valid_output_splits_utterance_and_directive():
    llm = FakeLLM(['现在开庭，请双方围绕争点陈述。\n```json\n'
                   '{"round_summary": "双方分歧", "directive": "continue", "reason": "程序通过"}\n```'])
    skill = HostSkill(llm=llm, registry=make_registry())
    out = await skill.speak_and_decide(_state())

    assert out["directive"] == "continue"
    assert out["parse_ok"] is True and out["repaired"] is False
    assert out["utterance"] == "现在开庭，请双方围绕争点陈述。"
    assert "{" not in out["utterance"]          # JSON 已被服务端剥离（S1）
    assert out["reason"] == "程序通过"
    assert out["raw_output"] and out["latency_ms"] >= 0
    assert llm.calls[0]["model"] == "deepseek-v4-pro"


@pytest.mark.asyncio
async def test_host_repair_once_then_success():
    llm = FakeLLM([
        "我直接说话，忘了输出结构。",                                   # 第一次：无 JSON
        '补充如下。\n{"directive": "ask_user", "ask_user": "请提供合同原件"}',  # 第二次：修复成功
    ])
    skill = HostSkill(llm=llm, registry=make_registry())
    out = await skill.speak_and_decide(_state())

    assert out["directive"] == "ask_user"
    assert out["ask_user"] == "请提供合同原件"
    assert out["repaired"] is True and out["parse_ok"] is True
    assert len(llm.calls) == 2
    # 修复请求必须携带格式错误反馈
    assert "校验失败原因" in llm.calls[1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_host_double_failure_falls_back_to_conclude():
    llm = FakeLLM(["没有 JSON。", "还是没有合法 JSON。"])
    skill = HostSkill(llm=llm, registry=make_registry())
    out = await skill.speak_and_decide(_state())

    assert out["directive"] == "conclude"
    assert out["parse_failed"] is True and out["repaired"] is True
    assert len(llm.calls) == 2  # 只重调一次，不无界重试


@pytest.mark.asyncio
async def test_host_verdict_invalid_for_generic_template():
    """普通会商不允许 verdict：枚举非法 → 修复一次 → 修复成功取 conclude。"""
    llm = FakeLLM([
        '{"directive": "verdict", "reason": "想直接裁决"}',   # 非法枚举
        '{"directive": "conclude", "reason": "改出纪要"}',    # 修复
    ])
    skill = HostSkill(llm=llm, registry=make_registry())
    out = await skill.speak_and_decide(_state(case_type="contract", host="mediator",
                                              roster=["legal_analyst"]))
    assert out["directive"] == "conclude"
    assert out["repaired"] is True
    assert "仅允许" in llm.calls[1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_host_llm_failure_raises_for_superstep_recovery():
    """LLM 失败必须抛出（交由 T1.6 的 super-step 恢复），不得在节点内吞错。"""
    skill = HostSkill(llm=FakeLLM([RuntimeError("llm down")]), registry=make_registry())
    with pytest.raises(RuntimeError):
        await skill.speak_and_decide(_state())


# ============================================================
# SchedulerSkill（隐藏排序智能体）
# ============================================================

CANDIDATES = ["plaintiff_lawyer", "defense_lawyer"]


@pytest.mark.asyncio
async def test_scheduler_valid_then_converge():
    llm = FakeLLM([
        '{"next_speaker": "plaintiff_lawyer", "continue_round": true, "reason": "先原告"}',
        '{"next_speaker": null, "continue_round": false, "reason": "已充分对抗"}',
    ])
    skill = SchedulerSkill(llm=llm, registry=make_registry())

    first = await skill.decide(_state(), CANDIDATES)
    assert first["next_speaker"] == "plaintiff_lawyer" and first["continue_round"] is True
    assert first["parse_failed"] is False

    second = await skill.decide(_state(), CANDIDATES)
    assert second["next_speaker"] is None and second["continue_round"] is False
    assert llm.calls[0]["model"] == "deepseek-flash"  # A4：排序用 flash


@pytest.mark.asyncio
async def test_scheduler_out_of_whitelist_repairs_then_accepts():
    """F13：非法 next（ghost_agent）→ 过滤 + 反馈重调 → 第二次合法即采纳。"""
    llm = FakeLLM([
        '{"next_speaker": "ghost_agent", "continue_round": true}',
        '{"next_speaker": "defense_lawyer", "continue_round": true, "reason": "改点被告"}',
    ])
    skill = SchedulerSkill(llm=llm, registry=make_registry())
    out = await skill.decide(_state(), CANDIDATES)

    assert out["next_speaker"] == "defense_lawyer"
    assert out["repaired"] is True and out["parse_failed"] is False
    assert "不在候选名单内" in llm.calls[1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_scheduler_double_illegal_converges_without_raising():
    """F13：连续两次非法 → 收敛本轮，无异常栈。"""
    llm = FakeLLM([
        '{"next_speaker": "ghost_agent", "continue_round": true}',
        'not json at all',
    ])
    skill = SchedulerSkill(llm=llm, registry=make_registry())
    out = await skill.decide(_state(), CANDIDATES)

    assert out["next_speaker"] is None
    assert out["continue_round"] is False
    assert out["parse_failed"] is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_scheduler_llm_failure_propagates_for_graph_fallback():
    """排序失败必须抛出，由图节点降级为「模板默认顺序」（D15③），不在 Skill 内吞掉。"""
    skill = SchedulerSkill(llm=FakeLLM([RuntimeError("boom")]), registry=make_registry())
    with pytest.raises(RuntimeError):
        await skill.decide(_state(), CANDIDATES)


# ============================================================
# 审计：fail-open
# ============================================================

@pytest.mark.asyncio
async def test_audit_skips_when_ids_invalid():
    await audit_mod.record_host_decision(
        {"turn_id": "not-a-uuid", "conversation_id": None, "parsed_directive": {}}
    )  # 不抛异常、不触碰 DB


@pytest.mark.asyncio
async def test_audit_fail_open_on_db_error(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(audit_mod, "app_session_factory", boom)
    await audit_mod.record_host_decision({
        "turn_id": str(uuidlib.uuid4()), "conversation_id": str(uuidlib.uuid4()),
        "round": 1, "host_agent_id": "judge", "kind": "scheduler",
        "parsed_directive": {"next_speaker": "defense_lawyer"}, "accepted": True,
    })  # 落库失败仅告警，不阻断整轮


# ============================================================
# 图集成：真实 Skill 注入 + scheduler 无气泡
# ============================================================

@pytest.mark.asyncio
async def test_graph_with_real_skills_no_scheduler_bubble():
    reg = make_registry()
    host_llm = FakeLLM([
        '现在开庭，请原告先陈述。\n{"directive": "continue", "reason": "程序通过"}',
        '请被告回应。\n{"directive": "continue", "reason": "继续对抗"}',
        '讨论充分，现出具纪要。\n{"directive": "conclude", "reason": "收敛"}',
    ])
    sched_llm = FakeLLM([
        '{"next_speaker": "plaintiff_lawyer", "continue_round": true, "reason": "先原告"}',
        '{"next_speaker": "defense_lawyer", "continue_round": true, "reason": "再被告"}',
        '{"next_speaker": null, "continue_round": false, "reason": "收敛"}',
    ])
    recorded: list[dict] = []

    async def recorder(record):
        recorded.append(record)

    graph = await build_collab_graph(
        registry=reg,
        host_advisor=HostSkill(llm=host_llm, registry=reg).speak_and_decide,
        scheduler=SchedulerSkill(llm=sched_llm, registry=reg).decide,
        decision_recorder=recorder,
    )
    result = await graph.ainvoke(_state(max_rounds=3), config={"recursion_limit": 50})

    spokes = [m.additional_kwargs.get("agent_id") for m in result["messages"]
              if m.additional_kwargs.get("sender_type") == "agent"]
    assert spokes == ["plaintiff_lawyer", "defense_lawyer"]  # 严格保序

    # host 口语发言进气泡，且气泡内不含 JSON 指令
    host_msgs = [m for m in result["messages"] if m.additional_kwargs.get("sender_type") == "host"]
    assert host_msgs and "{" not in host_msgs[0].content

    # scheduler 不产生任何气泡
    assert not [m for m in result["messages"]
                if m.additional_kwargs.get("sender_type") == "scheduler"]
    # scheduler 不在 agent_registry / 成员名单
    registry_ids = {a["agent_id"] for a in await reg.all_agents()}
    assert "scheduler" not in registry_ids

    # 每次决策都落审计（D15②）：host 3 次（首轮/续轮/收尾）+ scheduler 2 次派发
    kinds = [r["kind"] for r in recorded]
    assert kinds.count("scheduler") == 2 and kinds.count("host") == 3
    assert all(r["accepted"] for r in recorded)
    assert recorded[0]["round"] == 0
    assert result["force_stop_reason"] == "conclude"
