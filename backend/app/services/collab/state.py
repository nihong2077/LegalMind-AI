"""
协同星型图状态定义（T1.3）

对齐 [docs/collab-supervisor-checkpoint_spec.md](../../../../docs/collab-supervisor-checkpoint_spec.md) §2.2，
并按计划 §1 锁定决策 **D14** 修订：
- **host** 只产出「程序性指令 + 口语发言」，**不再选下一位发言者**；
- **scheduler（隐藏演讲排序智能体）** 独占「next_speaker / 是否续轮」决策权；
- 状态需可被 LangGraph Postgres Checkpointer 序列化（仅用 dict/list/str/int/None）。

字段语义：
- ``messages``     统一 transcript（user / host / agent / tool），由 ``add_messages`` 归并；
- ``turn_id``      本次用户发言触发的一轮会商 = checkpoint thread 的子命名空间；
- ``round``        已派发的发言次数，由 scheduler 每次续轮 +1（轮次硬顶依据）；
- ``spoken``       本轮 turn 已发言的 agent_id（保序续跑与兜底排序的依据，D15①）；
- ``events``       host/scheduler 决策审计投影（``host_decisions`` 形状，D15②）；
- ``budget``       单 turn LLM 调用/token 预算（护栏，超出强制收尾）。
"""
from __future__ import annotations

from typing import Annotated, Any, Optional, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

# 主持人程序性指令取值（D14：不含「谁下一个发言」）
HOST_DIRECTIVES = ("continue", "ask_user", "verdict", "conclude")

DEFAULT_MAX_ROUNDS = 2
DEFAULT_BUDGET: dict[str, int] = {"max_llm_calls": 20, "max_tokens": 60_000}


def append_unique(left: list[str], right: list[str]) -> list[str]:
    """保序并集归并器：``spoken`` 累积不重复（D15① 保序依据）。"""
    out = list(left or [])
    for item in right or []:
        if item not in out:
            out.append(item)
    return out


def append_list(left: list, right: list) -> list:
    """追加归并器：``events`` 审计记录只增不减。"""
    return [*(left or []), *(right or [])]


class CollabState(TypedDict, total=False):
    """星型图共享状态（全部可选，节点用 ``Command(update=...)`` 增量更新）。"""

    # 统一 transcript（含角色标记的 additional_kwargs）
    messages: Annotated[list[AnyMessage], add_messages]
    conversation_id: str
    user_id: str  # 会话属主（T2.3：记忆召回按用户隔离，prepare 读取）
    turn_id: str
    case_type: str
    host_agent_id: str
    my_role: Optional[str]  # 用户接管扮演的 agent_id（空＝不扮演，D11）

    # B1 单聊：direct 会话只驱动 target_agent_id（T1.5 执行层依据）
    conv_type: str
    target_agent_id: Optional[str]

    # 编排
    roster: list[str]  # 当前群成员 agent_id（白名单来源，运行时可变）
    round: int
    max_rounds: int
    spoken: Annotated[list[str], append_unique]  # 本轮已派发发言的 agent_id

    # 决策与材料
    host_directive: dict[str, Any]  # 最近一次主持人程序性指令
    scheduler_directive: dict[str, Any]  # 最近一次排序智能体决策
    memories: list[dict[str, Any]]  # prepare 召回（P2 注入）
    retrieved: dict[str, Any]  # 共享法规/类案材料
    pending_question: Optional[str]  # ask_user 需用户补充的内容
    force_stop_reason: Optional[str]  # max_rounds / budget / no_speaker / verdict …

    # 审计与预算
    events: Annotated[list[dict[str, Any]], append_list]  # host_decisions 形状审计
    budget: dict[str, int]  # {max_llm_calls, max_tokens, used_llm_calls, used_tokens}


def initial_state(
    *,
    conversation_id: str,
    turn_id: str,
    user_id: str = "",
    case_type: str,
    host_agent_id: str,
    roster: list[str],
    my_role: Optional[str] = None,
    conv_type: str = "group",
    target_agent_id: Optional[str] = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    user_message: Optional[str] = None,
    budget: Optional[dict[str, int]] = None,
) -> CollabState:
    """构造一轮会商的初始状态（每次用户发言 = 一次图执行）。"""
    state: CollabState = {
        "messages": [],
        "conversation_id": conversation_id,
        "user_id": user_id,
        "turn_id": turn_id,
        "case_type": case_type,
        "host_agent_id": host_agent_id,
        "my_role": my_role,
        "conv_type": conv_type,
        "target_agent_id": target_agent_id,
        "roster": list(roster),
        "round": 0,
        "max_rounds": max_rounds,
        "spoken": [],
        "host_directive": {},
        "scheduler_directive": {},
        "memories": [],
        "retrieved": {},
        "pending_question": None,
        "force_stop_reason": None,
        "events": [],
        "budget": {**DEFAULT_BUDGET, **(budget or {})},
    }
    if user_message:
        state["messages"] = [_user_message(user_message)]
    return state


def _user_message(content: str) -> AnyMessage:
    from langchain_core.messages import HumanMessage

    return HumanMessage(
        content=content,
        name="user",
        additional_kwargs={"sender_type": "user", "sender_id": "user"},
    )
