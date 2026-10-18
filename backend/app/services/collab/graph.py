"""
协同星型图构建（T1.3）

对齐 [docs/collab-supervisor-checkpoint_spec.md](../../../../docs/collab-supervisor-checkpoint_spec.md) §2.1，
并按计划 §1 锁定决策 **D14** / **D15** 落地：

- 一个中心 ``host`` + 若干辐条（``agent:*`` 按注册表工厂生成、``tool:*`` 工具节点）；
- **图中不存在任何 host → 业务节点的固定边**：host 只产出「程序性指令 + 口语发言」，
  用 ``Command(goto=)`` 动态跳到 ``scheduler`` / ``ask_user`` / ``conclude``；
- **scheduler 是隐藏的演讲排序智能体**（内部节点，**不进 agent_registry、不产生气泡**），
  独占「next_speaker / 是否续轮」决策；scheduler → agent/tool 亦为动态 ``Command(goto=)``；
- 唯一固定回边：所有辐条 → host（``ask_user`` resume 后亦回 host）；
- 绑 ``AsyncPostgresSaver``（checkpointer 单例，图结构无状态可复用）。

本卡只交付**图结构与护栏**；host/scheduler 的提示词与容错（T1.4）、Agent 节点的真实
Skill 映射（T1.5）、恢复引擎（T1.6）通过此处可注入的回调接入，默认给出**最小可跑桩**，
保证图在无 LLM 环境下即可编译、可单测、可结构评审。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Awaitable, Callable, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ...core.checkpoint import get_checkpointer
from .registry import RegistryService, get_registry
from .state import CollabState

logger = logging.getLogger(__name__)

# ---------------- 节点名 ----------------

PREPARE_NODE = "prepare"
HOST_NODE = "host"
SCHEDULER_NODE = "scheduler"
ASK_USER_NODE = "ask_user"
CONCLUDE_NODE = "conclude"

# 节点名前缀：LangGraph 1.x 保留 ":" 作命名空间分隔符（NS_SEP），不可用于节点名，
# 故规格中的 `agent:*` / `tool:*` 落地为 `agent__*` / `tool__*`（仅为图内部标识，
# 对外一律用 agent_id）。
AGENT_NODE_PREFIX = "agent__"
TOOL_NODE_PREFIX = "tool__"

# 隐藏排序智能体不出现在这些地方
HIDDEN_INTERNAL_NODES = (SCHEDULER_NODE,)

# B2（D11）：接管式扮演中断事件类型
TAKEOVER_TYPE = "takeover"


def _is_hand_back(resume_value: Any) -> bool:
    """resume 值是否表示「交还给 AI」：``{"action": "hand_back"}`` 或 ``{"hand_back": True}``。"""
    if isinstance(resume_value, dict):
        if resume_value.get("hand_back") is True:
            return True
        return str(resume_value.get("action") or "").lower() == "hand_back"
    return False


def _takeover_text(resume_value: Any) -> str:
    """提取用户接管发言正文（兼容纯字符串 / ``{"text": ...}`` / ``{"content": ...}``）。"""
    if isinstance(resume_value, dict):
        return str(resume_value.get("text") or resume_value.get("content") or "")
    return "" if resume_value is None else str(resume_value)

def _is_conclude(resume_value: Any) -> bool:
    """resume 值是否表示「结束会商」（用户主权）：``{"action": "conclude"}`` 或 ``{"conclude": True}``。"""
    if isinstance(resume_value, dict):
        if resume_value.get("conclude") is True:
            return True
        return str(resume_value.get("action") or "").lower() == "conclude"
    return False


def agent_node_name(agent_id: str) -> str:
    return f"{AGENT_NODE_PREFIX}{agent_id}"


def tool_node_name(agent_id: str) -> str:
    return f"{TOOL_NODE_PREFIX}{agent_id}"


def node_name_for(agent_id: str, tool_ids: set[str]) -> str:
    """agent_id → 可 goto 的节点名（工具型走 ``tool__*``，否则 ``agent__*``）。"""
    return tool_node_name(agent_id) if agent_id in tool_ids else agent_node_name(agent_id)


# ---------------- 可注入回调 ----------------

HostAdvisor = Callable[[CollabState], Awaitable[dict[str, Any]]]
# scheduler 收到的是**有序**候选白名单（agent_id；顺序＝模板默认顺序，D15① 保序依据）
SchedulerDecider = Callable[[CollabState, list[str]], Awaitable[dict[str, Any]]]
SpokeRunner = Callable[[dict[str, Any], CollabState], Awaitable[str]]
ToolRunner = Callable[[dict[str, Any], CollabState], Awaitable[dict[str, Any]]]
DecisionRecorder = Callable[[dict[str, Any]], Awaitable[None]]
# T1.7 模板适配注入点（均可选、默认 None → 通用行为完全不变）：
# - interaction_card：ask_user 中断 payload 的模板化包装（如庭审补证卡片）；
#   可为同步或异步（生产分派器需查模板 → async），ask_user 节点按需 await；
# - conclude_producer：conclude 节点在主持人收尾气泡后追加的额外产出（如 verdict → 判决书）。
InteractionCard = Callable[[CollabState], Any]
ConcludeProducer = Callable[[CollabState], Awaitable[list[Any]]]
# 轮次发言分隔条：把「下一个发言人」以中性系统提示显性化（不暴露主持人身份）。
# 入参：state、next_speaker(agent_id)、speaker_name；默认 None → 完全不产出分隔条。
SpeakerNotice = Callable[[CollabState, str, str], Awaitable[None]]


# ---------------- 默认桩（T1.4/T1.5 会替换） ----------------

async def default_host_advisor(state: CollabState) -> dict[str, Any]:
    """未注入 HostSkill 时的最小桩：默认「继续」。**不选 next**（D14 已移交 scheduler）。"""
    return {
        "directive": "continue",
        "round_summary": "",
        "reason": "未注入 HostSkill，使用最小桩",
    }


def _template_order_decision(state: CollabState, candidates: list[str]) -> dict[str, Any]:
    """模板默认顺序兜底（D15③）：按**群成员**顺序点未发言者，发完则收敛，不跳人。

    只覆盖 roster 内的发言者：工具节点是「按需取证」的辐条，不由默认顺序自动派发。
    """
    spoken = set(state.get("spoken") or [])
    roster = set(state.get("roster") or [])
    for agent_id in candidates:
        if agent_id not in roster:
            continue
        if agent_id not in spoken:
            return {
                "next_speaker": agent_id,
                "continue_round": True,
                "reason": "模板默认顺序兜底",
                "fallback": True,
            }
    return {
        "next_speaker": None,
        "continue_round": False,
        "reason": "候选名单已发言完毕",
        "fallback": True,
    }


async def default_scheduler(state: CollabState, candidates: list[str]) -> dict[str, Any]:
    """隐藏排序智能体桩：退化为模板默认顺序（= D15③ 的兜底路径本身）。"""
    return _template_order_decision(state, candidates)


async def default_agent_runner(agent: dict[str, Any], state: CollabState) -> str:
    return f"（{agent.get('name') or agent.get('agent_id')} 发言桩：T1.5 接入真实 Skill）"


async def default_tool_runner(tool: dict[str, Any], state: CollabState) -> dict[str, Any]:
    return {
        "tool_id": tool.get("agent_id"),
        "query": state.get("pending_question") or "",
        "results": [],
    }


async def default_decision_recorder(record: dict[str, Any]) -> None:  # noqa: ARG001
    """默认不落库：决策已写入 state.events；T1.4/T1.6 注入 DB 审计。"""
    return None


# ---------------- 护栏工具 ----------------

def _audit_record(
    state: CollabState,
    *,
    kind: str,
    agent_id: str,
    parsed: dict[str, Any],
    accepted: bool,
    rejection_reason: Optional[str] = None,
    raw_output: Optional[str] = None,
    latency_ms: Optional[int] = None,
) -> dict[str, Any]:
    """``host_decisions`` 形状的决策审计（D15②）。

    原始大文本单独放 ``raw_output``，供前端时间线展示与排障；``parsed_directive``
    只保留结构化字段（已剔除 ``raw_output`` 以免重复）。
    """
    return {
        "turn_id": state.get("turn_id"),
        "conversation_id": state.get("conversation_id"),
        "round": int(state.get("round", 0)),
        "host_agent_id": agent_id,
        "kind": kind,  # host | scheduler
        "parsed_directive": {k: v for k, v in parsed.items() if k != "raw_output"},
        "accepted": accepted,
        "rejection_reason": rejection_reason,
        "raw_output": raw_output,
        "latency_ms": latency_ms,
    }


def _budget_exceeded(state: CollabState) -> bool:
    budget = state.get("budget") or {}
    return (
        int(budget.get("used_llm_calls", 0)) >= int(budget.get("max_llm_calls", 20))
        or int(budget.get("used_tokens", 0)) >= int(budget.get("max_tokens", 60_000))
    )


def _charge_budget(state: CollabState, calls: int = 1) -> dict[str, int]:
    """单 turn 调用预算累加（护栏②；token 用量由 T1.6 从 LLM 响应回填）。"""
    budget = dict(state.get("budget") or {})
    budget["used_llm_calls"] = int(budget.get("used_llm_calls", 0)) + calls
    return budget


# ---------------- 图构建 ----------------

async def build_collab_graph(
    *,
    registry: Optional[RegistryService] = None,
    host_advisor: Optional[HostAdvisor] = None,
    scheduler: Optional[SchedulerDecider] = None,
    agent_runner: Optional[SpokeRunner] = None,
    tool_runner: Optional[ToolRunner] = None,
    decision_recorder: Optional[DecisionRecorder] = None,
    interaction_card: Optional[InteractionCard] = None,
    conclude_producer: Optional[ConcludeProducer] = None,
    speaker_notice: Optional[SpeakerNotice] = None,
    checkpointer: Any = None,
) -> Any:
    """构建并编译协同星型图。

    Args:
        registry: Agent/模板注册表；默认取进程单例（Node 工厂与白名单均**数据驱动**）。
        host_advisor: 主持人程序性决策 + 口语发言（T1.4 HostSkill / T1.7 court 法官）。
        scheduler: 隐藏排序智能体（T1.4 SchedulerSkill）；失败由本节点降级兜底。
        agent_runner: 真实 Agent Skill 调用（T1.5）。
        tool_runner: 工具节点（法规/类案检索，T1.5）。
        decision_recorder: 决策审计落库（host_decisions，T1.4/T1.6）。
        interaction_card: ask_user 中断 payload 的模板化包装（T1.7 court 补证卡片）；默认 None。
        conclude_producer: conclude 收尾后追加气泡的产出器（T1.7 court verdict → 判决书）；默认 None。
        speaker_notice: 轮次发言分隔条生产者（中性「下面是 X 发言」）；默认 None → 不产出。
        checkpointer: 传入则绑 AsyncPostgresSaver；为 None 时取全局（未就绪则不持久化）。
    """
    reg = registry or await get_registry()
    agents = await reg.all_agents()
    if not agents:
        raise RuntimeError("Agent 注册表为空，无法构建协同图")

    by_id = {a["agent_id"]: a for a in agents}
    speaking_agents = [a for a in agents if not a.get("is_tool")]
    tool_agents = [a for a in agents if a.get("is_tool")]
    tool_ids = {a["agent_id"] for a in tool_agents}

    _host_advisor = host_advisor or default_host_advisor
    _scheduler = scheduler or default_scheduler
    _agent_runner = agent_runner or default_agent_runner
    _tool_runner = tool_runner or default_tool_runner
    _recorder = decision_recorder or default_decision_recorder
    _interaction_card = interaction_card  # T1.7：默认 None（保持通用 payload）
    _conclude_producer = conclude_producer  # T1.7：默认 None（保持仅主持人收尾气泡）
    _speaker_notice = speaker_notice  # 分隔条：默认 None（不产出，完全保持既有行为）

    def _allowed_candidates(state: CollabState) -> list[str]:
        """scheduler 候选白名单（**有序**）：roster（去主持人，保持模板顺序）后接工具 Agent。

        A1 护栏①：顺序即模板默认顺序，既是保序建议也是硬白名单（越权一律否决）。
        """
        # B1（T1.5）：direct 会话白名单只含唯一目标 Agent，不引入其他成员与工具节点
        if (state.get("conv_type") or "") == "direct":
            target = state.get("target_agent_id")
            return [target] if target else []
        host = state.get("host_agent_id")
        candidates: list[str] = []
        for agent_id in state.get("roster") or []:
            if agent_id == host or agent_id in candidates:
                continue  # 主持人已在 host 节点发言，不再作为辐条被点
            candidates.append(agent_id)
        # 工具 Agent 始终可用：主持人/排序需要材料时可派发，无需其成为群成员
        for agent_id in sorted(tool_ids, key=lambda x: by_id.get(x, {}).get("sort_order", 100)):
            if agent_id not in candidates:
                candidates.append(agent_id)
        return candidates

    # ---- 节点 ----

    async def prepare_node(state: CollabState) -> dict[str, Any]:
        # P2（T2.3）长期记忆召回。
        # T1.9-M3：**轮首并行预取**工具辐条（法规/类案材料 + 引用卡）——
        # 对齐 [scheduling_spec §1④/§3.1](../../../../docs/collab-scheduling_spec.md)：
        # 检索类 Agent（``is_tool``）**不占主串行发言位**，由编排器在轮首一次**并行取证**，
        # 结果入共享上下文（``state.retrieved`` → 各 Agent 的资料块）；其发 ``tool`` 事件 +
        # 产出引用卡由 ToolNodeRunner 自身完成（M3）。工具 Agent 非群成员则不预取。
        if (state.get("conv_type") or "") == "direct":
            return {}
        already = state.get("retrieved") or {}
        prefetch = [
            aid for aid in (state.get("roster") or [])
            if aid in tool_ids and aid not in already
        ]
        if not prefetch:
            return {}
        results = await asyncio.gather(
            *[_tool_runner(by_id.get(aid) or {"agent_id": aid}, state) for aid in prefetch],
            return_exceptions=True,
        )
        retrieved = dict(already)
        for aid, res in zip(prefetch, results):
            if isinstance(res, BaseException):
                logger.warning("[collab] 轮首预取 %s 失败（忽略）：%s", aid, res)
                continue
            if res:
                retrieved[aid] = res
        return {"retrieved": retrieved}

    async def host_node(state: CollabState) -> Command:
        # 用户主权（F6）：上一节点（ask_user/接管）标记「结束会商」→ 不调 LLM，直接注入 goto=conclude
        if state.get("force_stop_reason") == "user_conclude":
            return Command(goto=CONCLUDE_NODE, update={})
        # B1（T1.5）：direct 会话无主持人，直接派发唯一目标 Agent（不调 host/scheduler，
        # 既省 LLM 又保证"单聊只出该 Agent 一条流"）；目标已发言则收尾。
        if (state.get("conv_type") or "") == "direct":
            target = state.get("target_agent_id")
            update: dict[str, Any] = {
                "host_directive": {
                    "directive": "continue",
                    "reason": "direct 会话直接派发目标 Agent（T1.5 B1）",
                },
            }
            if target and target not in set(state.get("spoken") or []):
                return Command(goto=node_name_for(target, tool_ids), update=update)
            update["force_stop_reason"] = "direct_done"
            return Command(goto=CONCLUDE_NODE, update=update)

        decision = await _host_advisor(state) or {}
        host_id = state.get("host_agent_id") or ""
        host_agent = by_id.get(host_id) or {}
        host_name = host_agent.get("name") or "主持人"

        directive = str(decision.get("directive") or "").lower()
        accepted = directive in ("continue", "ask_user", "verdict", "conclude")
        rejection_reason: Optional[str] = None
        if not accepted:
            # HostSkill 已内含一次反馈修复；走到这里说明两次都非法 → 护栏兜底收尾（spec §2.4④）
            directive = "conclude"
            rejection_reason = "invalid_directive"

        update: dict[str, Any] = {
            "host_directive": {**decision, "directive": directive},
            "budget": _charge_budget(state, int(decision.get("llm_calls", 1))),
            "events": [
                _audit_record(
                    state,
                    kind="host",
                    agent_id=host_id,
                    parsed={**decision, "directive": directive},
                    accepted=accepted,
                    rejection_reason=rejection_reason,
                    raw_output=decision.get("raw_output"),
                    latency_ms=decision.get("latency_ms"),
                )
            ],
        }
        # 主持人口语发言进 transcript（前端气泡）；JSON 指令已被 HostSkill 剥离，不会外泄
        utterance = (decision.get("utterance") or "").strip()
        if utterance:
            update["messages"] = [
                AIMessage(
                    content=utterance,
                    name=host_name,
                    additional_kwargs={
                        "sender_type": "host",
                        "sender_id": host_id,
                        "sender_name": host_name,
                    },
                )
            ]
        await _recorder(update["events"][0])

        if directive == "ask_user":
            update["pending_question"] = decision.get("ask_user") or decision.get("question")
            return Command(goto=ASK_USER_NODE, update=update)
        if directive in ("verdict", "conclude"):
            update["force_stop_reason"] = directive
            return Command(goto=CONCLUDE_NODE, update=update)
        # 护栏②：单 turn 预算硬顶
        if _budget_exceeded(state):
            update["force_stop_reason"] = "budget"
            return Command(goto=CONCLUDE_NODE, update=update)
        # 护栏②：max_rounds 轮次硬顶（LLM 无法突破）
        if int(state.get("round", 0)) >= int(state.get("max_rounds", 2)):
            update["force_stop_reason"] = "max_rounds"
            return Command(goto=CONCLUDE_NODE, update=update)
        # 程序性决策 OK → 交隐藏排序智能体决定「谁下一个发言 / 是否续轮」（D14）
        return Command(goto=SCHEDULER_NODE, update=update)

    async def scheduler_node(state: CollabState) -> Command:
        candidates = _allowed_candidates(state)
        decision: dict[str, Any]
        try:
            decision = await _scheduler(state, candidates) or {}
        except Exception as e:  # 护栏③：排序智能体失败降级兜底，不中断整轮（D15③）
            logger.warning("[collab] 排序智能体失败，降级模板默认顺序：%s", e)
            decision = {**_template_order_decision(state, candidates), "degraded": True, "error": str(e)}

        next_speaker = decision.get("next_speaker")
        continue_round = bool(decision.get("continue_round", bool(next_speaker)))
        accepted = True
        rejection_reason: Optional[str] = None

        if not continue_round:
            decision = {**decision, "next_speaker": None}
            next_speaker = None
            rejection_reason = None  # 正常收敛，不算否决
        elif next_speaker not in candidates:
            # 护栏①：越权/非法目标 → 回退模板默认顺序（D15③），不跳人
            logger.warning("[collab] 排序决策目标越权：%s，回退模板默认顺序", next_speaker)
            decision = {
                **_template_order_decision(state, candidates),
                "invalid_target": next_speaker,
            }
            next_speaker = decision.get("next_speaker")
            continue_round = bool(next_speaker)
            accepted = False
            rejection_reason = "invalid_target"

        record = _audit_record(
            state,
            kind="scheduler",
            agent_id=state.get("host_agent_id") or "",
            parsed=decision,
            accepted=accepted,
            rejection_reason=rejection_reason,
            raw_output=decision.get("raw_output"),
            latency_ms=decision.get("latency_ms"),
        )
        await _recorder(record)
        update: dict[str, Any] = {
            "scheduler_directive": decision,
            "events": [record],
            "budget": _charge_budget(state, int(decision.get("llm_calls", 1))),
        }

        if not continue_round or not next_speaker:
            update["force_stop_reason"] = state.get("force_stop_reason") or "no_speaker"
            return Command(goto=CONCLUDE_NODE, update=update)

        # 轮次发言分隔条（用户可见的中性提示）：进入下一轮前产出「下面是 X 发言」。
        # 主持人/调度身份全程隐藏；失败 fail-open，不阻断整轮（A1 代码只做护栏）。
        if _speaker_notice is not None:
            speaker_name = (by_id.get(next_speaker) or {}).get("name") or next_speaker
            try:
                await _speaker_notice(state, next_speaker, speaker_name)
            except Exception as e:
                logger.warning("[collab] 轮次分隔条调用失败（忽略）：%s", e)

        update["round"] = int(state.get("round", 0)) + 1
        return Command(goto=node_name_for(next_speaker, tool_ids), update=update)

    async def ask_user_node(state: CollabState) -> dict[str, Any]:
        question = state.get("pending_question") or "请补充更多信息以便继续会商"
        payload: dict[str, Any] = {
            "type": "interaction_required",
            "conversation_id": state.get("conversation_id"),
            "turn_id": state.get("turn_id"),
            "question": question,
        }
        # T1.7：模板化包装（如庭审补证卡片）；默认 None → 通用 payload 完全不变
        if _interaction_card is not None:
            extra = _interaction_card(state)
            if inspect.isawaitable(extra):  # 生产分派器为 async（需查模板 adapter）
                extra = await extra
            payload = {**payload, **(extra or {})}
        answer = interrupt(payload)
        if _is_conclude(answer):
            # 用户主权（F6）：标记「结束会商」→ 经回边交由 host 注入 Command(goto=conclude)
            return {"pending_question": None, "force_stop_reason": "user_conclude"}
        return {
            "pending_question": None,
            "messages": [
                HumanMessage(
                    content=str(answer) if answer is not None else "",
                    name="user",
                    additional_kwargs={
                        "sender_type": "user",
                        "sender_id": "user",
                        "resume_after_interrupt": True,
                    },
                )
            ],
        }

    async def conclude_node(state: CollabState) -> dict[str, Any]:
        host_id = state.get("host_agent_id") or ""
        reason = state.get("force_stop_reason") or "conclude"
        messages: list[Any] = []
        if host_id:
            host = by_id.get(host_id)
            host_name = host["name"] if host else "主持人"
            messages.append(
                AIMessage(
                    content=f"（{host_name}宣布本轮会商结束：{reason}）",
                    name=host_name,
                    additional_kwargs={
                        "sender_type": "host",
                        "sender_id": host_id,
                        "phase": "conclude",
                        "stop_reason": reason,
                    },
                )
            )
        # B1（T1.5）：direct 会话无主持人 → 不产生"宣布结束"气泡；T1.7 追加产出器默认 None。
        if _conclude_producer is not None:
            try:
                extra = await _conclude_producer(state) or []
            except Exception as e:  # fail-open：判决书生成失败不阻断 conclude
                logger.warning("[collab] conclude 追加产出失败（忽略）：%s", e)
                extra = []
            messages.extend(extra)
        update: dict[str, Any] = {"force_stop_reason": reason}
        if messages:
            update["messages"] = messages
        return update

    def make_agent_node(agent: dict[str, Any]):
        agent_id = agent["agent_id"]
        name = agent.get("name") or agent_id

        def _agent_message(content: str) -> AIMessage:
            return AIMessage(
                content=content or "",
                name=name,
                additional_kwargs={
                    "sender_type": "agent",
                    "agent_id": agent_id,
                    "sender_name": name,
                },
            )

        async def node(state: CollabState) -> dict[str, Any]:
            # B2（D11）：轮到「用户扮演的 Agent」时暂停等用户输入，AI 不代其生成；
            # 用户输入以该角色身份落库（sender_type=user + metadata.actor_agent_id）。
            if agent_id == state.get("my_role"):
                resume_val = interrupt(
                    {
                        "type": TAKEOVER_TYPE,
                        "conversation_id": state.get("conversation_id"),
                        "turn_id": state.get("turn_id"),
                        "agent_id": agent_id,
                        "agent_name": name,
                        "question": f"轮到你以「{name}」身份发言（可点击「交还给 AI」）",
                    }
                )
                if _is_conclude(resume_val):
                    # 用户主权（F6）：轮到本人时选择「结束会商」→ 标记并经回边交由 host 收尾
                    return {"force_stop_reason": "user_conclude"}
                if _is_hand_back(resume_val):
                    # 交还给 AI：撤销接管标志（本 turn 内置空 my_role）后自动续跑，由 AI 代其生成
                    return {
                        "my_role": None,
                        "messages": [_agent_message(await _agent_runner(agent, state))],
                        "spoken": [agent_id],
                    }
                text = _takeover_text(resume_val)
                return {
                    "messages": [
                        HumanMessage(
                            content=text,
                            name="user",
                            additional_kwargs={
                                "sender_type": "user",
                                "sender_id": "user",
                                "actor_agent_id": agent_id,
                                "actor_agent_name": name,
                            },
                        )
                    ],
                    "spoken": [agent_id],
                }

            content = await _agent_runner(agent, state)
            return {"messages": [_agent_message(content)], "spoken": [agent_id]}

        return node

    def make_tool_node(tool: dict[str, Any]):
        tool_id = tool["agent_id"]
        name = tool.get("name") or tool_id

        async def node(state: CollabState) -> dict[str, Any]:
            payload = await _tool_runner(tool, state) or {}
            return {
                "messages": [
                    AIMessage(
                        content=f"（{name}检索完成）",
                        name=name,
                        additional_kwargs={
                            "sender_type": "tool",
                            "tool_id": tool_id,
                            "sender_name": name,
                            "payload": payload,
                        },
                    )
                ],
                "retrieved": {**(state.get("retrieved") or {}), tool_id: payload},
                "spoken": [tool_id],
            }

        return node

    # ---- 组图 ----

    graph = StateGraph(CollabState)
    graph.add_node(PREPARE_NODE, prepare_node)
    graph.add_node(HOST_NODE, host_node)
    graph.add_node(SCHEDULER_NODE, scheduler_node)
    graph.add_node(ASK_USER_NODE, ask_user_node)
    graph.add_node(CONCLUDE_NODE, conclude_node)
    for agent in speaking_agents:
        graph.add_node(agent_node_name(agent["agent_id"]), make_agent_node(agent))
    for tool in tool_agents:
        graph.add_node(tool_node_name(tool["agent_id"]), make_tool_node(tool))

    graph.add_edge(START, PREPARE_NODE)
    graph.add_edge(PREPARE_NODE, HOST_NODE)
    # 唯一固定回边：所有辐条 / 补证 → host
    for agent in speaking_agents:
        graph.add_edge(agent_node_name(agent["agent_id"]), HOST_NODE)
    for tool in tool_agents:
        graph.add_edge(tool_node_name(tool["agent_id"]), HOST_NODE)
    graph.add_edge(ASK_USER_NODE, HOST_NODE)
    graph.add_edge(CONCLUDE_NODE, END)
    # 注意：host 与 scheduler 均无任何固定出边——去向 100% 运行时 Command(goto=) 决定

    if checkpointer is None:
        checkpointer = get_checkpointer()
    compiled = graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
    logger.info(
        "[collab] 星型图已构建：%d 发言辐条 + %d 工具辐条（scheduler 为隐藏内部节点）",
        len(speaking_agents),
        len(tool_agents),
    )
    return compiled


_graph_cache: Any = None


async def get_collab_graph() -> Any:
    """进程级复用图单例（图结构无状态；checkpointer 单独单例）。

    **生产装配**：按模板 ``adapter`` 分派真实件（HostSkill / SchedulerSkill /
    AgentNodeRunner / ToolNodeRunner / host_decisions 审计落库 + court 适配件），
    见 :func:`services.collab.production.build_production_injectables`。同一张编译图
    服务所有模板（分派在调用时按 ``state.case_type`` 查模板）。
    """
    global _graph_cache
    if _graph_cache is None:
        # 延迟导入避免 graph ↔ production(templates.court) 的模块级循环依赖
        from .production import build_production_injectables

        registry = await get_registry()
        injectables = await build_production_injectables(registry=registry)
        _graph_cache = await build_collab_graph(registry=registry, **injectables)
    return _graph_cache


def reset_collab_graph() -> None:
    """显式失效缓存（注册表变更 / 测试注入后调用）。"""
    global _graph_cache
    _graph_cache = None
