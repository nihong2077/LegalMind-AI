"""工具辐条节点工厂（T1.5 / T1.9-M3）——法规 / 类案检索（按需取证）+ 引用卡

工具 Agent（``is_tool=true``）不占主串行发言位，由隐藏排序智能体按需派发；
本模块把注册表 ``skill_ref`` 映射到**现有检索链路**
（[rag_retriever.retrieve_legal_knowledge](../../../../docs/collab-scheduling_spec.md)）：
- ``RegulatoryResearcher`` → ``domain="law"``（现行法规四级 RAG）；
- ``CaseSearchSkill`` → ``domain="judge"``（裁判文书/类案）。

**T1.9-M3 引用卡**（对齐 [collab-ui-refactor_plan.md](../../../../docs/collab-ui-refactor_plan.md)
§5.3⑤ / §5.5）：
- **进度事件**：检索前后发 ``tool`` 事件（``status=running/done/error`` +
  ``query / result_count / elapsed_ms``），前端呈现「正在检索…」进度条；
- **引用卡**：检索有结果时产出 ``msg_type=card`` 的法规/类案引用卡（结构化
  ``metadata.citations`` + 可读正文），以 ``event_key={turn_id}:r{round}:{tool_id}:card``
  幂等落库，并下发 ``message`` 事件（前端按 msg_type 渲染蓝边卡）。

**失败降级**：检索异常不让整轮中断（发 ``tool:error`` + 空结果，不产出引用卡），
与 A1「代码只做护栏」一致。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from ...core.llm_client import LLMClient, get_llm_client
from ...core.redis_client import push_recent_message
from ..legal.rag_retriever import retrieve_legal_knowledge
from .agent_nodes import Emitter, _default_emit, make_event_key, message_id_for
from .conversation_store import ConversationStore, pg_store

logger = logging.getLogger(__name__)

# skill_ref → 检索领域（数据驱动：注册表 skill_ref 决定，代码只做映射）
SKILL_DOMAINS: dict[str, str] = {
    "RegulatoryResearcher": "law",
    "CaseSearchSkill": "judge",
}

TOOL_MODEL = "deepseek-flash"

# 事件类型 / 状态
EVENT_TOOL = "tool"
EVENT_MESSAGE = "message"
TOOL_STATUS_RUNNING = "running"
TOOL_STATUS_DONE = "done"
TOOL_STATUS_ERROR = "error"

# 消息类型（引用卡）
MSG_TYPE_CARD = "card"

# 领域 → 引用卡类型 / 中文标签（前端渲染依据）
CARD_TYPES: dict[str, str] = {"law": "law_citation", "judge": "case_citation"}
DOMAIN_LABELS: dict[str, str] = {"law": "法规", "judge": "类案"}


def _query_of(state: dict[str, Any]) -> str:
    """工具检索 query：最近一条用户消息 → pending_question → 最近发言兜底。"""
    for msg in reversed(state.get("messages") or []):
        kwargs = getattr(msg, "additional_kwargs", None) or {}
        if kwargs.get("sender_type") == "user" or getattr(msg, "name", "") == "user":
            text = str(getattr(msg, "content", "") or "").strip()
            if text:
                return text
    pending = str(state.get("pending_question") or "").strip()
    if pending:
        return pending
    for msg in reversed(state.get("messages") or []):
        text = str(getattr(msg, "content", "") or "").strip()
        if text:
            return text
    return ""


def _render_citation_card(
    name: str, domain: str, query: str, results: list[dict[str, Any]]
) -> str:
    """把检索结果渲染成引用卡正文（来源 + 摘要 + 置信度）。"""
    label = DOMAIN_LABELS.get(domain, "资料")
    lines = [f"{name} · {label}检索（共 {len(results)} 条）　检索词：{query}"]
    for i, r in enumerate(results, 1):
        source = str(r.get("source") or "系统")
        content = str(r.get("content") or "").strip().replace("\n", " ")
        if len(content) > 200:
            content = content[:200] + "…"
        score = r.get("score")
        score_txt = f"（置信度 {float(score):.2f}）" if isinstance(score, (int, float)) else ""
        lines.append(f"{i}. 【{source}】{content}{score_txt}")
    return "\n".join(lines)


class ToolNodeRunner:
    """工具辐条执行器：注入 ``build_collab_graph(tool_runner=...)``。

    除返回检索 payload 供图状态（``retrieved``）使用外，还负责：
    1）下发 ``tool`` 进度事件；2）产出并幂等落库 ``msg_type=card`` 引用卡（下发 ``message``）。
    """

    def __init__(
        self,
        *,
        llm: Optional[LLMClient] = None,
        top_k: int = 5,
        store: Optional[ConversationStore] = None,
        emit: Optional[Emitter] = None,
    ) -> None:
        self._llm = llm
        self.top_k = top_k
        self._store = store
        self._emit = emit or _default_emit

    @property
    def llm(self) -> LLMClient:
        return self._llm or get_llm_client()

    @property
    def store(self) -> ConversationStore:
        return self._store or pg_store

    async def __call__(self, tool: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        tool_id = str(tool.get("agent_id") or "")
        name = str(tool.get("name") or tool_id)
        query = _query_of(state)
        payload: dict[str, Any] = {"tool_id": tool_id, "query": query, "results": []}

        domain = SKILL_DOMAINS.get(str(tool.get("skill_ref") or ""))
        if not domain or not query:
            return payload

        conversation_id = str(state.get("conversation_id") or "")
        turn_id = str(state.get("turn_id") or "")
        round_no = int(state.get("round", 0))

        await self._emit_safe(
            conversation_id,
            EVENT_TOOL,
            {
                "agent_id": tool_id,
                "agent_name": name,
                "tool": domain,
                "status": TOOL_STATUS_RUNNING,
                "query": query,
                "turn_id": turn_id,
                "round": round_no,
            },
        )

        started = time.perf_counter()
        try:
            flash = self.llm.get_chat_model(
                model=TOOL_MODEL, temperature=0.1, max_tokens=1024
            )
            results = await retrieve_legal_knowledge(
                query=query, llm=flash, top_k=self.top_k, use_hyde=True, domain=domain
            )
            payload["results"] = results or []
        except Exception as e:  # 失败降级：不让整轮中断
            logger.warning("[collab] 工具辐条 %s 检索失败，降级为空结果：%s", tool_id, e)
            await self._emit_safe(
                conversation_id,
                EVENT_TOOL,
                {
                    "agent_id": tool_id,
                    "agent_name": name,
                    "tool": domain,
                    "status": TOOL_STATUS_ERROR,
                    "query": query,
                    "result_count": 0,
                    "turn_id": turn_id,
                    "round": round_no,
                },
            )
            return payload

        elapsed = int((time.perf_counter() - started) * 1000)
        await self._emit_safe(
            conversation_id,
            EVENT_TOOL,
            {
                "agent_id": tool_id,
                "agent_name": name,
                "tool": domain,
                "status": TOOL_STATUS_DONE,
                "query": query,
                "result_count": len(payload["results"]),
                "elapsed_ms": elapsed,
                "turn_id": turn_id,
                "round": round_no,
            },
        )

        # 有结果且处于轮次内 → 产出引用卡（幂等落库 + message 事件）
        if payload["results"] and conversation_id and turn_id:
            await self._emit_card(
                conversation_id,
                tool_id=tool_id,
                name=name,
                domain=domain,
                query=query,
                turn_id=turn_id,
                round_no=round_no,
                results=payload["results"],
            )
        return payload

    async def _emit_card(
        self,
        conversation_id: str,
        *,
        tool_id: str,
        name: str,
        domain: str,
        query: str,
        turn_id: str,
        round_no: int,
        results: list[dict[str, Any]],
    ) -> None:
        """产出法规/类案引用卡：幂等落库后下发 ``message`` 事件（前端按 msg_type 渲染）。"""
        event_key = make_event_key(turn_id, round_no, tool_id, 0)
        message_id = message_id_for(event_key)

        existing = await self.store.get_message_by_event_key(conversation_id, event_key)
        if existing is not None:
            # 「先查库后发」：重跑/恢复时复用既有卡片（幂等）
            await self._emit_safe(conversation_id, EVENT_MESSAGE, existing)
            return

        metadata = {
            "message_id": message_id,
            "msg_type": MSG_TYPE_CARD,
            "card_type": CARD_TYPES.get(domain, "citation"),
            "tool_id": tool_id,
            "tool_type": domain,
            "query": query,
            "citations": [
                {
                    "source": str(r.get("source") or "系统"),
                    "content": str(r.get("content") or ""),
                    "score": r.get("score"),
                }
                for r in results
            ],
        }
        content = _render_citation_card(name, domain, query, results)

        record = await self.store.insert_message_once(
            conversation_id,
            event_key=event_key,
            sender_type="tool",
            sender_id=tool_id,
            sender_name=name,
            content=content,
            msg_type=MSG_TYPE_CARD,
            round=round_no,
            metadata=metadata,
        )
        if record is None:
            record = await self.store.get_message_by_event_key(conversation_id, event_key)
        if record is None:
            return
        try:
            await push_recent_message(conversation_id, record)
        except Exception as e:  # 热缓存仅加速，降级不影响业务
            logger.warning("[collab] 引用卡热缓存写入失败（忽略）：%s", e)
        await self._emit_safe(conversation_id, EVENT_MESSAGE, record)

    async def _emit_safe(
        self, conversation_id: str, event_type: str, data: dict[str, Any]
    ) -> None:
        """事件推送失败不阻断检索（Redis 降级时静默）。"""
        if not conversation_id:
            return
        try:
            await self._emit(conversation_id, event_type, data)
        except Exception as e:
            logger.warning("[collab] 工具事件推送失败（忽略）：%s", e)


def make_tool_runner(
    *,
    llm: Optional[LLMClient] = None,
    top_k: int = 5,
    store: Optional[ConversationStore] = None,
    emit: Optional[Emitter] = None,
) -> ToolNodeRunner:
    """构造 tool_runner（graph 可注入扩展点）。"""
    return ToolNodeRunner(llm=llm, top_k=top_k, store=store, emit=emit)
