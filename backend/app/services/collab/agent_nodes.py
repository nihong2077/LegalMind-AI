"""Agent 辐条节点工厂（T1.5）——零侵入映射现有 Skill + 流式 message 事件

对齐
[docs/collab-scheduling_spec.md](../../../../docs/collab-scheduling_spec.md) §3.2（群上下文协议）、
[docs/collab-supervisor-checkpoint_spec.md](../../../../docs/collab-supervisor-checkpoint_spec.md) §4.1
与计划 §1 **S1/B1**：

- **群上下文块**：在**不改动 9 个现有 Skill 人设 prompt** 的前提下，由本模块统一拼接
  「协同群 + 你的角色 + 主持人指引 + 共享资料 + 本轮发言记录 + 输出要求」前缀，
  再由 **adapter** 把它映射为各 Skill 现有方法的入参（`query/context`、`case_facts/...`）。
- **S1 流式**：每个 Agent 的发言一律 token 级流式，SSE 采用
  `message_start`（分配 `message_id` + `event_key`）→ 多帧 `message_delta` → `message_end`（定稿落库）。
- **幂等**：`message_id = uuid5(event_key)`、`event_key = {turn_id}:r{round}:{agent_id}:{seq}`；
  「先查库后发」——`event_key` 已落库则直接复用，不重复生成/推送；落库走
  `INSERT ... ON CONFLICT (event_key) DO NOTHING`。
- **B1 单聊**：`direct` 会话由 graph 白名单收窄到唯一 `target_agent_id`（见 graph.py），
  本模块只负责「被点到的那一个 Agent 出一条流」。

无适用流式方法的 Skill（`chat_rag`、`CaseSearchSkill`、`ContractReviewSkill` 等）走
**通用人设 adapter**（`persona` + 群上下文块 → `LLMClient.chat_stream`），保证 S1 不破。
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from ...core.llm_client import LLMClient, get_llm_client
from ...core.redis_client import append_conv_event, push_recent_message
from ..agents.defendant_skill import DefendantSkill
from ..agents.judge_skill import JudgeSkill
from ..agents.judgment_report_skill import JudgmentReportSkill
from ..agents.legal_analyzer import LegalAnalyzer
from ..agents.mediator_skill import MediatorSkill
from ..agents.plaintiff_skill import PlaintiffSkill
from ..agents.regulatory_researcher import RegulatoryResearcher
from .conversation_store import ConversationStore, pg_store
from .registry import RegistryService, get_registry

logger = logging.getLogger(__name__)

DEFAULT_AGENT_MODEL = "deepseek-v4-pro"

# S1 三事件（对齐计划 §1）
EVENT_START = "message_start"
EVENT_DELTA = "message_delta"
EVENT_END = "message_end"

# uuid5 命名空间：由 event_key 派生确定性 message_id（重跑/恢复保持同一 id，前端可幂等合并）
MESSAGE_ID_NS = uuid.UUID("6f1a4b7e-0c1d-4a5e-9b3c-c0ffee5eed01")

# 事件发射器：默认走 Redis Stream + Pub/Sub；测试可注入假实现
Emitter = Callable[[str, str, dict[str, Any]], Awaitable[None]]


async def _default_emit(conversation_id: str, event_type: str, data: dict[str, Any]) -> None:
    await append_conv_event(conversation_id, event_type, data)


# ---------------- 群上下文块 ----------------

@dataclass
class GroupContext:
    """统一群上下文（§3.2）——渲染成块供 Skill 消费，同时暴露适配器所需的结构化字段。"""

    case_type: str
    case_type_label: str
    title: str
    question: str
    transcript: list[dict[str, Any]] = field(default_factory=list)
    materials: str = ""
    memories: str = ""
    host_guidance: str = ""
    instruction: str = ""

    def speeches_by(self, speaker_id: str) -> list[str]:
        """按发言人取本轮（含本轮之前 chat 历史）发言文本，供 Skill 入参复用。"""
        return [
            str(e.get("content") or "")
            for e in self.transcript
            if e.get("speaker_id") == speaker_id and str(e.get("content") or "").strip()
        ]

    def render(self) -> str:
        """渲染为人读的群上下文块（§3.2 版式）。"""
        lines = [
            f"【协同群】{self.title or '未命名会商'}　案情类型：{self.case_type_label or self.case_type or '通用'}",
        ]
        if self.host_guidance:
            lines.append(f"【主持人本轮指引】{self.host_guidance}")
        if self.memories:
            lines.append(f"【已召回的用户背景记忆】\n{self.memories}")
        if self.materials:
            lines.append(f"【共享资料】（系统检索，供引用，勿逐条罗列）\n{self.materials}")
        if self.transcript:
            lines.append("【本轮发言记录】（按时间顺序，最新在最后）")
            for e in self.transcript:
                speaker = e.get("speaker_name") or e.get("speaker_id") or "?"
                lines.append(f"  {speaker}：{str(e.get('content') or '').strip()}")
        if self.question:
            lines.append(f"【本轮问题】{self.question}")
        lines.append(
            "【输出要求】\n"
            "  - 只输出你这一角色的专业意见，口语化、有条理，使用 Markdown 短段落\n"
            "  - 不要重复上面别人已说过的话；可引用《法律全称》第X条\n"
            "  - 不要输出 JSON 或调度指令；长度建议 200-500 字"
        )
        if self.instruction:
            lines.append(self.instruction)
        return "\n".join(lines)


def _transcript(state: dict[str, Any]) -> list[dict[str, Any]]:
    """从图内 transcript（AnyMessage + additional_kwargs）提炼有序发言记录。"""
    out: list[dict[str, Any]] = []
    for msg in state.get("messages") or []:
        kwargs = getattr(msg, "additional_kwargs", None) or {}
        content = str(getattr(msg, "content", "") or "").strip()
        if not content:
            continue
        speaker_id = kwargs.get("agent_id") or kwargs.get("sender_id") or kwargs.get("tool_id")
        sender_type = kwargs.get("sender_type")
        if not sender_type:
            # 兜底：HumanMessage 无 kwargs 时按 name 推断
            sender_type = "user" if getattr(msg, "type", "") == "human" else "agent"
        out.append(
            {
                "speaker_type": sender_type,
                "speaker_id": speaker_id or getattr(msg, "name", "") or sender_type,
                "speaker_name": kwargs.get("sender_name") or getattr(msg, "name", "") or "",
                "content": content,
            }
        )
    return out


def _latest_question(state: dict[str, Any]) -> str:
    """最近一条用户消息＝本轮问题。"""
    for msg in reversed(state.get("messages") or []):
        kwargs = getattr(msg, "additional_kwargs", None) or {}
        if kwargs.get("sender_type") == "user" or getattr(msg, "name", "") == "user":
            text = str(getattr(msg, "content", "") or "").strip()
            if text:
                return text
    return ""


def _render_materials(state: dict[str, Any]) -> str:
    """把共享检索结果（``retrieved``）渲染为资料块；P2 之前通常为空。"""
    blocks: list[str] = []
    for tool_id, payload in (state.get("retrieved") or {}).items():
        results = payload.get("results") if isinstance(payload, dict) else None
        if not results:
            continue
        lines = [f"◇ {tool_id}："]
        for r in results[:5]:
            if isinstance(r, dict):
                title = r.get("title") or r.get("law_name") or r.get("case_number") or ""
                snippet = r.get("excerpt") or r.get("content") or r.get("summary") or ""
                lines.append(f"  - {title}：{str(snippet)[:200]}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def build_group_context(
    agent: dict[str, Any],
    state: dict[str, Any],
    *,
    case_type_label: str = "",
) -> GroupContext:
    """构造统一群上下文块（纯函数，无 IO，便于单测）。"""
    directive = state.get("host_directive") or {}
    guidance = str(directive.get("round_summary") or directive.get("reason") or "").strip()
    memories = "\n".join(
        str(m.get("content") or "") for m in (state.get("memories") or [])[:5] if m.get("content")
    )
    return GroupContext(
        case_type=str(state.get("case_type") or ""),
        case_type_label=case_type_label or str(state.get("case_type") or ""),
        title=str(state.get("title") or ""),
        question=_latest_question(state),
        transcript=_transcript(state),
        materials=_render_materials(state),
        memories=memories,
        host_guidance=guidance,
    )


# ---------------- Skill 适配器（零侵入：只调现有方法） ----------------

AgentStream = Callable[[dict[str, Any], GroupContext, Any], AsyncIterator[str]]


def _block_with_question(ctx: GroupContext) -> str:
    """Skill 无独立 context 入参时，按 §3.2 把群上下文块拼进 query 前缀。"""
    return f"{ctx.render()}\n\n【本轮问题】{ctx.question}" if ctx.question else ctx.render()


def _stream_legal_analyzer(agent: dict[str, Any], ctx: GroupContext, llm: Any) -> AsyncIterator[str]:
    return LegalAnalyzer(llm).analyze_stream(query=_block_with_question(ctx), context=ctx.materials)


def _stream_regulatory_researcher(agent: dict[str, Any], ctx: GroupContext, llm: Any) -> AsyncIterator[str]:
    return RegulatoryResearcher(llm).research_stream(
        query=_block_with_question(ctx), area=ctx.case_type_label
    )


def _stream_mediator(agent: dict[str, Any], ctx: GroupContext, llm: Any) -> AsyncIterator[str]:
    return MediatorSkill(llm).propose_mediation_stream(
        plaintiff_position=_last_of(ctx, "plaintiff_lawyer"),
        defendant_position=_last_of(ctx, "defense_lawyer"),
        case_facts=_block_with_question(ctx),
        kfe={},
    )


def _stream_plaintiff(agent: dict[str, Any], ctx: GroupContext, llm: Any) -> AsyncIterator[str]:
    skill = PlaintiffSkill(llm)
    plaintiff_args = ctx.speeches_by("plaintiff_lawyer")
    defendant_args = ctx.speeches_by("defense_lawyer")
    if not plaintiff_args:
        return skill.opening_statement_stream(
            case_facts=_block_with_question(ctx),
            focus_points=ctx.host_guidance,
            legal_knowledge=ctx.materials,
        )
    return skill.rebuttal_stream(
        defendant_arg=_last_of(ctx, "defense_lawyer"),
        case_facts=_block_with_question(ctx),
        round_num=len(plaintiff_args) + 1,
        plaintiff_args=plaintiff_args,
        defendant_args=defendant_args,
        judge_comment=ctx.host_guidance,
        legal_knowledge=ctx.materials,
    )


def _stream_defendant(agent: dict[str, Any], ctx: GroupContext, llm: Any) -> AsyncIterator[str]:
    skill = DefendantSkill(llm)
    defendant_args = ctx.speeches_by("defense_lawyer")
    plaintiff_args = ctx.speeches_by("plaintiff_lawyer")
    if not defendant_args:
        return skill.opening_statement_stream(
            case_facts=_block_with_question(ctx),
            plaintiff_claim=_last_of(ctx, "plaintiff_lawyer") or ctx.question,
            focus_points=ctx.host_guidance,
            legal_knowledge=ctx.materials,
        )
    return skill.rebuttal_stream(
        plaintiff_arg=_last_of(ctx, "plaintiff_lawyer"),
        case_facts=_block_with_question(ctx),
        round_num=len(defendant_args) + 1,
        plaintiff_args=plaintiff_args,
        defendant_args=defendant_args,
        judge_comment=ctx.host_guidance,
        legal_knowledge=ctx.materials,
    )


def _stream_judge(agent: dict[str, Any], ctx: GroupContext, llm: Any) -> AsyncIterator[str]:
    return JudgeSkill(llm).preside_opening_stream(
        plaintiff_claim=ctx.question or _block_with_question(ctx),
        defendant_response=_last_of(ctx, "defense_lawyer"),
    )


def _stream_judgment_report(agent: dict[str, Any], ctx: GroupContext, llm: Any) -> AsyncIterator[str]:
    return JudgmentReportSkill(llm).generate_judgment_stream(
        verdict=ctx.host_guidance or ctx.question,
        case_info={"case_type": ctx.case_type_label or ctx.case_type},
        plaintiff_args=ctx.speeches_by("plaintiff_lawyer"),
        defendant_args=ctx.speeches_by("defense_lawyer"),
    )


def _stream_generic(agent: dict[str, Any], ctx: GroupContext, llm: Any) -> AsyncIterator[str]:
    """通用人设 adapter：persona + 群上下文块 → 流式（覆盖 chat_rag 等无现成流式方法的 Skill）。"""
    return _astream_generic(llm, agent, ctx)


async def _astream_generic(llm: Any, agent: dict[str, Any], ctx: GroupContext) -> AsyncIterator[str]:
    persona = (agent.get("persona") or "").strip() or "你是一名专业法律助手。"
    messages = [
        {"role": "system", "content": persona},
        {"role": "user", "content": _block_with_question(ctx)},
    ]
    async for chunk in llm.astream(messages):  # type: ignore[union-attr]
        text = getattr(chunk, "content", "") or ""
        if text:
            yield text


def _last_of(ctx: GroupContext, speaker_id: str) -> str:
    items = ctx.speeches_by(speaker_id)
    return items[-1] if items else ""


# skill_ref → 适配器（数据驱动：注册表 skill_ref 决定绑定，代码只做映射，不硬编码名单）
SKILL_STREAM_ADAPTERS: dict[str, AgentStream] = {
    "LegalAnalyzer": _stream_legal_analyzer,
    "RegulatoryResearcher": _stream_regulatory_researcher,
    "MediatorSkill": _stream_mediator,
    "PlaintiffSkill": _stream_plaintiff,
    "DefendantSkill": _stream_defendant,
    "JudgeSkill": _stream_judge,
    "JudgmentReportSkill": _stream_judgment_report,
}


def resolve_adapter(agent: dict[str, Any]) -> AgentStream:
    """按注册表 ``skill_ref`` 取适配器；无匹配走通用人设 adapter（S1 不破）。"""
    return SKILL_STREAM_ADAPTERS.get(str(agent.get("skill_ref") or ""), _stream_generic)


# ---------------- 确定性幂等键 ----------------

def make_event_key(turn_id: str, round_no: int, agent_id: str, seq: int = 0) -> str:
    """``{turn_id}:r{round}:{agent_id}:{seq}``（supervisor-checkpoint spec §4.1）。"""
    return f"{turn_id}:r{int(round_no)}:{agent_id}:{seq}"


def message_id_for(event_key: str) -> str:
    """由 event_key 派生确定性 message_id（重跑/恢复保持同一 id）。"""
    return str(uuid.uuid5(MESSAGE_ID_NS, event_key))


# ---------------- 节点执行（流式 + 事件 + 幂等落库） ----------------

def _model_for(agent: dict[str, Any], llm_client: LLMClient) -> Any:
    prefs = agent.get("model_pref") or {}
    return llm_client.get_chat_model(
        model=prefs.get("model") or DEFAULT_AGENT_MODEL,
        temperature=float(prefs.get("temperature", 0.5)),
        max_tokens=int(prefs.get("max_tokens", 2048)),
        streaming=True,
    )


class AgentNodeRunner:
    """辐条执行器：注入 ``build_collab_graph(agent_runner=...)``。"""

    def __init__(
        self,
        *,
        llm: Optional[LLMClient] = None,
        store: Optional[ConversationStore] = None,
        registry: Optional[RegistryService] = None,
        emit: Optional[Emitter] = None,
    ) -> None:
        self._llm = llm
        self._store = store
        self._registry = registry
        self._emit = emit or _default_emit

    @property
    def llm(self) -> LLMClient:
        return self._llm or get_llm_client()

    @property
    def store(self) -> ConversationStore:
        return self._store or pg_store

    async def __call__(self, agent: dict[str, Any], state: dict[str, Any]) -> str:
        conversation_id = str(state.get("conversation_id") or "")
        if not conversation_id:
            # 无会话上下文（纯单测/冒烟）→ 直接流式返回，不落库不推送
            return await self._stream_only(agent, state)

        reg = self._registry or await get_registry()
        tpl = await reg.get_template(str(state.get("case_type") or ""))
        ctx = build_group_context(
            agent, state, case_type_label=(tpl or {}).get("name") or ""
        )
        return await self._stream_persist(agent, state, ctx, conversation_id)

    # ---- 主路径 ----

    async def _stream_persist(
        self, agent: dict[str, Any], state: dict[str, Any], ctx: GroupContext, conversation_id: str
    ) -> str:
        agent_id = str(agent["agent_id"])
        name = str(agent.get("name") or agent_id)
        round_no = int(state.get("round", 0))
        event_key = make_event_key(str(state.get("turn_id") or ""), round_no, agent_id, 0)
        message_id = message_id_for(event_key)

        # 「先查库后发」：已存在同一 event_key → 直接复用，不重复生成/推送（幂等续跑）
        existing = await self.store.get_message_by_event_key(conversation_id, event_key)
        if existing is not None:
            logger.info("[collab] event_key 已存在，复用既有发言（幂等）：%s", event_key)
            return str(existing.get("content") or "")

        sender = {"type": "agent", "id": agent_id, "name": name}
        base = {"message_id": message_id, "event_key": event_key, "round": round_no, "sender": sender}
        await self._emit(conversation_id, EVENT_START, {**base, "type": "text"})

        chunks: list[str] = []
        async for chunk in self._stream(agent, ctx):
            if not chunk:
                continue
            chunks.append(chunk)
            await self._emit(conversation_id, EVENT_DELTA, {"message_id": message_id, "delta": chunk})
        content = "".join(chunks)

        await self._emit(conversation_id, EVENT_END, {**base, "content": content, "metadata": {}})

        record = await self.store.insert_message_once(
            conversation_id,
            event_key=event_key,
            sender_type="agent",
            sender_id=agent_id,
            sender_name=name,
            content=content,
            msg_type="text",
            round=round_no,
            metadata={"message_id": message_id},
        )
        if record is not None:
            try:
                await push_recent_message(conversation_id, record)
            except Exception as e:  # 热缓存仅加速，降级不影响业务
                logger.warning("[collab] 热缓存写入失败（忽略）：%s", e)
        return content

    def _stream(self, agent: dict[str, Any], ctx: GroupContext) -> AsyncIterator[str]:
        adapter = resolve_adapter(agent)
        return adapter(agent, ctx, _model_for(agent, self.llm))

    async def _stream_only(self, agent: dict[str, Any], state: dict[str, Any]) -> str:
        ctx = build_group_context(agent, state)
        chunks: list[str] = []
        async for chunk in self._stream(agent, ctx):
            if chunk:
                chunks.append(chunk)
        return "".join(chunks)


def make_agent_runner(
    *,
    llm: Optional[LLMClient] = None,
    store: Optional[ConversationStore] = None,
    registry: Optional[RegistryService] = None,
    emit: Optional[Emitter] = None,
) -> AgentNodeRunner:
    """构造 agent_runner（graph 可注入扩展点）。"""
    return AgentNodeRunner(llm=llm, store=store, registry=registry, emit=emit)
