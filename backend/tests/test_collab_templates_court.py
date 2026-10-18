"""T1.7 court 模板配置化测试（F7）——开庭→对抗→补证→恢复→裁决 全流程

对齐计划 §3 T1.7 行与规格 §2.5/§6：

- **JudgeSkill collab_mode 提示词分支**（M1）：True 时拼接「庭审调度权（协同群模式）」，
  默认 False 保持原提示词（旧 ``/debate/stream`` 链路零回归，A3 红线）；
- **court_scheduler**（打散串行 / 不跳人 / 庭审用语中性 / 无原被告时退化模板顺序）；
- **补证卡片群内化**（interaction_card 注入 ask_user interrupt payload）；
- **verdict → 判决书**（conclude_producer 追加书记员判决书气泡）；
- 真图 + 假件（假 LLM / 假 registry / 假回调），不依赖 DB/Redis/LLM。
"""
import sys

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

sys.path.insert(0, ".")

from app.services.agents.judge_skill import (
    COURT_COLLAB_SCHEDULING_PROMPT,
    JUDGE_SYSTEM_PROMPT,
    JudgeSkill,
    build_collab_system_prompt,
)
from app.services.collab import templates as tpl
from app.services.collab.graph import build_collab_graph
from app.services.collab.state import initial_state

from tests.test_collab_graph import make_registry

CANDIDATES = ["plaintiff_lawyer", "defense_lawyer", "clerk", "legal_researcher", "case_searcher"]


# ============================================================
# 假件
# ============================================================

class FakeChatClient:
    """最小 LLMClient 替身：``chat`` 逐条返回预置原始文本（验证解析/修复/兜底）。"""

    def __init__(self, contents: list[str]):
        self._contents = list(contents)
        self.calls: list[dict] = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        raw = self._contents.pop(0) if self._contents else ""
        return {"choices": [{"message": {"content": raw}}]}


def _court_state(**kw):
    return initial_state(
        conversation_id="c1", turn_id="t1", case_type="court", host_agent_id="judge",
        roster=["plaintiff_lawyer", "defense_lawyer", "clerk"], max_rounds=3,
        user_message="请开始庭审", **kw,
    )


# ============================================================
# M1：JudgeSkill collab_mode 提示词分支
# ============================================================

def test_judge_collab_mode_prompt_branch():
    with_collab = JudgeSkill(llm=None, collab_mode=True)
    assert with_collab.collab_mode is True
    assert with_collab.system_prompt.startswith(JUDGE_SYSTEM_PROMPT)
    assert "庭审调度权（协同群模式）" in with_collab.system_prompt
    assert COURT_COLLAB_SCHEDULING_PROMPT in with_collab.system_prompt

    # 默认 collab_mode=False：提示词与旧链路完全一致（零回归）
    legacy = JudgeSkill(llm=None)
    assert legacy.collab_mode is False
    assert legacy.system_prompt == JUDGE_SYSTEM_PROMPT
    assert "庭审调度权" not in legacy.system_prompt

    assert build_collab_system_prompt("BASE") == f"BASE\n\n{COURT_COLLAB_SCHEDULING_PROMPT}"


# ============================================================
# court_scheduler：打散串行 / 不跳人 / 退化
# ============================================================

@pytest.mark.asyncio
async def test_court_scheduler_alternates_then_converges():
    state = _court_state()

    step1 = await tpl.court_scheduler(state, CANDIDATES)
    assert step1["next_speaker"] == "plaintiff_lawyer" and step1["continue_round"] is True
    assert "陈述" in step1["reason"]  # 庭审用语中性/程序性，非"模板默认顺序兜底"
    assert "模板默认顺序" not in step1["reason"]

    state["spoken"] = ["plaintiff_lawyer"]
    step2 = await tpl.court_scheduler(state, CANDIDATES)
    assert step2["next_speaker"] == "defense_lawyer"

    state["spoken"] = ["plaintiff_lawyer", "defense_lawyer"]
    step3 = await tpl.court_scheduler(state, CANDIDATES)
    assert step3["next_speaker"] == "clerk"  # 双方陈述后传唤书记员

    # 各方均已陈述、仍有轮次额度 → 回到陈述较少一方对辩（打散固定串行）
    state["spoken"] = ["plaintiff_lawyer", "defense_lawyer", "clerk"]
    state["round"] = 3
    state["max_rounds"] = 4
    step4 = await tpl.court_scheduler(state, CANDIDATES)
    assert step4["next_speaker"] in ("plaintiff_lawyer", "defense_lawyer")
    assert step4["continue_round"] is True

    # 额度用尽 → 收敛交由主持人裁决
    state["round"] = 3
    state["max_rounds"] = 3
    step5 = await tpl.court_scheduler(state, CANDIDATES)
    assert step5["next_speaker"] is None and step5["continue_round"] is False


@pytest.mark.asyncio
async def test_court_scheduler_falls_back_without_litigants():
    state = initial_state(
        conversation_id="c1", turn_id="t1", case_type="court", host_agent_id="judge",
        roster=["legal_analyst"], max_rounds=2, user_message="会商",
    )
    decision = await tpl.court_scheduler(state, ["legal_analyst"])
    assert decision["next_speaker"] == "legal_analyst"  # 无原/被告 → 模板默认顺序
    assert "模板默认顺序" in decision.get("reason", "")


# ============================================================
# 补证卡片群内化
# ============================================================

def test_court_interaction_card_payload():
    card = tpl.build_court_interaction_card({"pending_question": "请补充合同原件"})
    assert card["card_type"] == "evidence_supplement"
    assert card["title"] == "补证通知"
    assert card["question"] == "请补充合同原件"
    assert "补充证据" in card["hint"]


# ============================================================
# host_advisor：解析 / 一次修复 / 兜底（无 LLM）
# ============================================================

@pytest.mark.asyncio
async def test_court_host_advisor_parse_repair_and_fallback():
    # 正常：口语发言 + 合法程序指令
    ok = tpl.build_court_host_advisor(
        llm=FakeChatClient(['开场白。\n```json\n{"directive":"continue","round_summary":"x","reason":"y"}\n```']),
        registry=make_registry(),
    )
    out = await ok(_court_state())
    assert out["parse_ok"] is True and out["directive"] == "continue"
    assert out["utterance"] == "开场白。" and out["repaired"] is False

    # court 指令枚举：conclude 非法 → 同一 super-step 内修复为 verdict
    repair = tpl.build_court_host_advisor(
        llm=FakeChatClient(['```json {"directive":"conclude"}```', '```json {"directive":"verdict"}```']),
        registry=make_registry(),
    )
    out2 = await repair(_court_state())
    assert out2["parse_ok"] is True and out2["directive"] == "verdict" and out2["repaired"] is True

    # 连续两次非法 → 兜底 conclude（不误判为 verdict，无异常栈）
    fallback = tpl.build_court_host_advisor(
        llm=FakeChatClient(["没有任何 JSON", "依然没有 JSON"]),
        registry=make_registry(),
    )
    out3 = await fallback(_court_state())
    assert out3["parse_ok"] is False and out3["directive"] == "conclude"
    assert out3["parse_failed"] is True


# ============================================================
# verdict → 判决书（conclude_producer）
# ============================================================

@pytest.mark.asyncio
async def test_court_conclude_producer_only_on_verdict():
    async def fake_runner(state):  # noqa: ARG001
        return "本院判决如下：一、被告向原告支付货款。"

    producer = tpl.make_court_conclude_producer(verdict_runner=fake_runner)

    no = await producer({"force_stop_reason": "max_rounds"})
    assert no == []

    msgs = await producer({"force_stop_reason": "verdict", "messages": []})
    assert len(msgs) == 1
    assert isinstance(msgs[0], AIMessage)
    assert msgs[0].additional_kwargs["agent_id"] == "clerk"
    assert msgs[0].additional_kwargs["phase"] == "verdict"
    assert "判决如下" in msgs[0].content


# ============================================================
# F7：庭审全流程（开庭→对抗→补证→恢复→裁决）
# ============================================================

@pytest.mark.asyncio
async def test_court_template_full_flow_f7():
    async def fake_agent_runner(agent, state):  # noqa: ARG001
        return f"{agent['agent_id']}·陈述"

    async def court_advisor(state):
        msgs = state.get("messages") or []
        resumed = any(
            getattr(m, "additional_kwargs", {}).get("resume_after_interrupt") for m in msgs
        )
        spoken = [
            m.additional_kwargs.get("agent_id")
            for m in msgs
            if m.additional_kwargs.get("sender_type") == "agent"
        ]
        if resumed:
            return {"directive": "verdict", "utterance": "本庭认为事实已查清，现在宣判。",
                    "reason": "证据充分，作出裁决"}
        if len(spoken) >= 2:
            return {"directive": "ask_user", "ask_user": "请补充合同原件及付款凭证",
                    "utterance": "本庭认为关键证据不足，请予补充。", "reason": "证据不足，补证"}
        return {"directive": "continue", "utterance": "本庭继续庭审。", "reason": "继续对抗"}

    async def fake_verdict_runner(state):  # noqa: ARG001
        return "【判决书】本院判决如下：被告向原告支付货款并承担诉讼费。"

    g = await build_collab_graph(
        registry=make_registry(),
        host_advisor=court_advisor,
        scheduler=tpl.court_scheduler,
        agent_runner=fake_agent_runner,
        interaction_card=tpl.build_court_interaction_card,
        conclude_producer=tpl.make_court_conclude_producer(verdict_runner=fake_verdict_runner),
        checkpointer=InMemorySaver(),
    )
    cfg = {"configurable": {"thread_id": "t1"}, "recursion_limit": 50}

    # 开庭 → 对抗（原/被告交替）→ 补证中断
    first = await g.ainvoke(_court_state(), config=cfg)
    interrupts = first.get("__interrupt__")
    assert interrupts, "证据不足应触发 ask_user 中断"
    payload = interrupts[0].value
    assert payload["type"] == "interaction_required"
    assert payload["card_type"] == "evidence_supplement"  # 补证卡片群内化
    assert "补充" in payload["question"]

    # 恢复：补证后从 ask_user 之后续跑到裁决
    resumed = await g.ainvoke(Command(resume="补充：合同原件及银行转账凭证各一份"), config=cfg)
    assert not resumed.get("__interrupt__")
    assert resumed["force_stop_reason"] == "verdict"

    agent_msgs = [
        m for m in resumed["messages"]
        if m.additional_kwargs.get("sender_type") == "agent"
    ]
    # 原/被告交替、各仅一次（恢复不重复）；书记员产出判决书
    assert [m.additional_kwargs["agent_id"] for m in agent_msgs] == [
        "plaintiff_lawyer", "defense_lawyer", "clerk"
    ]
    assert [m.content for m in agent_msgs[:2]] == [
        "plaintiff_lawyer·陈述", "defense_lawyer·陈述"
    ]
    verdict_msg = agent_msgs[-1]
    assert verdict_msg.additional_kwargs.get("phase") == "verdict"
    assert "判决书" in verdict_msg.content

    # 主持人收尾气泡存在
    assert any(m.additional_kwargs.get("sender_type") == "host" for m in resumed["messages"])


@pytest.mark.asyncio
async def test_generic_payload_unchanged_without_court_injection():
    """向后兼容：未注入 interaction_card / conclude_producer 时，通用行为完全不变。"""
    async def advisor(state):  # noqa: ARG001
        return {"directive": "ask_user", "ask_user": "请补充材料"}

    g = await build_collab_graph(
        registry=make_registry(), host_advisor=advisor, checkpointer=InMemorySaver()
    )
    cfg = {"configurable": {"thread_id": "g1"}, "recursion_limit": 50}
    first = await g.ainvoke(
        initial_state(
            conversation_id="c1", turn_id="g1", case_type="court", host_agent_id="judge",
            roster=["plaintiff_lawyer"], max_rounds=2, user_message="开始",
        ),
        config=cfg,
    )
    payload = first["__interrupt__"][0].value
    assert "card_type" not in payload  # 默认 payload 不含模板化卡片字段
