"""发言前置联网决策（P2-WebSearch Step2）

对齐 [collab-scheduling_spec.md](../../../../docs/collab-scheduling_spec.md) §3.2 与
A1「零侵入 Skill 适配」原则：在**不改动任何 Skill 流式方法**的前提下，由
[AgentNodeRunner](agent_nodes.py) 在**正式流式发言之前**插入一次「联网前置决策」：

1. **决策**：用该 Agent 自己的模型 + ``web_search`` / ``web_fetch`` 两个 function schema
   让 Agent **自主判断**本轮是否需要联网（最新法规/司法解释/新闻/公开资料等）；
   不需要则直接进入原流式发言（零额外产物）。
2. **检索**：需要时调用 [WebSearchClient](.../core/web_search.py)（透传优先 + 直连回退），
   并下发 ``tool`` 进度事件（``status=running/done/error`` + ``query/result_count/elapsed_ms``）。
3. **引用卡**：有结果时产出 ``msg_type=card`` 的**联网引用卡**（``metadata.card_type="web_citation"``，
   含 ``title/url/summary/content/site_name/date``），以
   ``event_key={turn_id}:r{round}:{agent_id}:web`` 幂等落库并下发 ``message`` 事件。
4. **并入资料块**：把结果渲染为 ``【联网检索资料】`` 追加到 ``ctx.materials``，
   供该 Agent 的原 Skill 入参（``legal_knowledge`` / ``context`` / 群上下文块）消费。

**失败降级 / 开关**：
- ``settings.WEB_SEARCH_ENABLED=False`` → 完全不触发（零额外 LLM/网络调用）；
- 决策或检索任何异常 → 记日志 + 发 ``tool:error``，**返回空串**，不阻断原流式发言。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from ...core.config import settings
from ...core.llm_client import LLMClient, get_llm_client
from ...core.redis_client import push_recent_message
from ...core.web_search import WebSearchClient, get_web_search_client
from .agent_nodes import (
    DEFAULT_AGENT_MODEL,
    Emitter,
    GroupContext,
    _default_emit,
    message_id_for,
)
from .conversation_store import ConversationStore, pg_store

logger = logging.getLogger(__name__)

EVENT_TOOL = "tool"
EVENT_MESSAGE = "message"
TOOL_STATUS_RUNNING = "running"
TOOL_STATUS_DONE = "done"
TOOL_STATUS_ERROR = "error"

MSG_TYPE_CARD = "card"
CARD_TYPE_WEB = "web_citation"

# 联网检索的「工具」标识（前端进度条 tool 字段）
TOOL_WEB_SEARCH = "web_search"
TOOL_WEB_FETCH = "web_fetch"

# 引用卡发送者（合成工具身份，非注册表 Agent）
WEB_SENDER_ID = "web_search"
WEB_SENDER_NAME = "联网检索"

# event_key 第 4 段固定 ``web``：`{turn}:r{round}:{agent_id}:web`
# （Agent 正文为 `...:{agent_id}:0`、法规/类案工具卡为 `...:{tool_id}:0`、分隔条为 `...:notice:0`）
WEB_KEY_SUFFIX = "web"

DECISION_MAX_TOKENS = 256

DECISION_SYSTEM = (
    "你是检索决策器。判断「本轮问题」是否需要联网检索**外部公开信息**"
    "（最新法规/司法解释、新闻、公开案例、行业公开资料）。\n"
    "- 需要检索信息 → 调用 web_search，给出精准检索词 query（可含 site 限定域名）；\n"
    "- 需要抓取某个具体网页正文 → 调用 web_fetch，给出 url；\n"
    "- 若内部法规/类案库足以回答，或属纯主观分析/寒暄 → **不要**调用任何工具。\n"
    "只做决策，不要输出分析过程。"
)

# OpenAI function 格式（LangChain ChatOpenAI.bind_tools 直接接受）
WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_WEB_SEARCH,
        "description": "联网搜索外部公开信息（法规/司法解读/新闻/公开资料），返回若干结果。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词，1-128 字符，尽量精准"},
                "site": {"type": "string", "description": "可选，限定域名，如 gov.cn"},
            },
            "required": ["query"],
        },
    },
}

WEB_FETCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_WEB_FETCH,
        "description": "抓取指定 URL 的正文（Markdown），用于已知具体网页时。",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "http(s) URL"}},
            "required": ["url"],
        },
    },
}


def _render_web_materials(results: list[dict[str, Any]]) -> str:
    """把联网结果渲染为资料块（供 Skill 入参的 ``materials`` 消费）。"""
    lines = ["【联网检索资料】（系统检索，供引用，勿逐条罗列）"]
    for i, r in enumerate(results[:5], 1):
        title = str(r.get("title") or "").strip()
        site = str(r.get("site_name") or "").strip()
        date = str(r.get("date") or "").strip()
        body = str(r.get("content") or r.get("snippet") or "").strip().replace("\n", " ")
        if len(body) > 300:
            body = body[:300] + "…"
        head = " · ".join(x for x in (title, site, date) if x) or "结果"
        url = str(r.get("url") or "").strip()
        line = f"  {i}. {head}：{body}"
        if url:
            line += f"（{url}）"
        lines.append(line)
    return "\n".join(lines)


def _render_web_card_content(query: str, results: list[dict[str, Any]]) -> str:
    lines = [f"{WEB_SENDER_NAME}（共 {len(results)} 条）　检索词：{query}"]
    for i, r in enumerate(results, 1):
        head = str(r.get("title") or r.get("site_name") or "结果").strip()
        body = str(r.get("content") or r.get("snippet") or "").strip().replace("\n", " ")
        if len(body) > 200:
            body = body[:200] + "…"
        lines.append(f"{i}. {head}：{body}")
    return "\n".join(lines)


class WebContextProvider:
    """联网前置决策 + 检索 + 引用卡 + 资料块（注入 ``AgentNodeRunner``）。"""

    def __init__(
        self,
        *,
        llm: Optional[LLMClient] = None,
        store: Optional[ConversationStore] = None,
        emit: Optional[Emitter] = None,
        client: Optional[WebSearchClient] = None,
        top_n: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self._llm = llm
        self._store = store
        self._emit = emit or _default_emit
        self._client = client
        self.top_n = int(top_n if top_n is not None else settings.WEB_SEARCH_TOP_N)
        self.enabled = settings.WEB_SEARCH_ENABLED if enabled is None else bool(enabled)

    @property
    def llm(self) -> LLMClient:
        return self._llm or get_llm_client()

    @property
    def store(self) -> ConversationStore:
        return self._store or pg_store

    @property
    def client(self) -> WebSearchClient:
        return self._client or get_web_search_client()

    async def maybe_search(
        self, agent: dict[str, Any], state: dict[str, Any], ctx: GroupContext, conversation_id: str
    ) -> str:
        """返回联网资料块（无检索/失败时为空串）；副作用：tool 事件 + 引用卡落库。"""
        if not self.enabled:
            return ""
        question = str(ctx.question or "").strip()
        if not question:
            return ""

        turn_id = str(state.get("turn_id") or "")
        round_no = int(state.get("round", 0))

        try:
            decision = await self._decide(agent, question, ctx)
        except Exception as e:  # 决策失败 → 不联网，照常发言
            logger.warning("[collab] 联网前置决策失败（忽略，照常发言）：%s", e)
            return ""

        action = str(decision.get("action") or "none")
        if action not in (TOOL_WEB_SEARCH, TOOL_WEB_FETCH):
            return ""

        query = str(decision.get("query") or question)
        url = str(decision.get("url") or "")
        await self._emit_tool(
            conversation_id,
            agent=agent,
            tool=action,
            status=TOOL_STATUS_RUNNING,
            query=url or query,
            turn_id=turn_id,
            round_no=round_no,
        )

        started = time.perf_counter()
        try:
            if action == TOOL_WEB_SEARCH:
                results = await self.client.search_web(
                    query,
                    ori_question=question,
                    site=decision.get("site"),
                    top_n=self.top_n,
                )
            else:
                fetched = await self.client.fetch_url(url)
                results = [
                    {
                        "title": fetched.get("title") or url,
                        "url": fetched.get("url") or url,
                        "content": fetched.get("content") or "",
                        "site_name": "",
                    }
                ]
        except Exception as e:  # 检索失败 → 空结果 + tool:error，不阻断发言
            logger.warning("[collab] 联网检索失败（忽略，照常发言）：%s", e)
            await self._emit_tool(
                conversation_id,
                agent=agent,
                tool=action,
                status=TOOL_STATUS_ERROR,
                query=url or query,
                result_count=0,
                turn_id=turn_id,
                round_no=round_no,
            )
            return ""

        elapsed = int((time.perf_counter() - started) * 1000)
        await self._emit_tool(
            conversation_id,
            agent=agent,
            tool=action,
            status=TOOL_STATUS_DONE,
            query=url or query,
            result_count=len(results),
            elapsed_ms=elapsed,
            turn_id=turn_id,
            round_no=round_no,
        )
        if not results:
            return ""

        if conversation_id and turn_id:
            await self._emit_card(
                conversation_id,
                agent=agent,
                query=url or query,
                turn_id=turn_id,
                round_no=round_no,
                results=results,
            )
        return _render_web_materials(results)

    # ---------------- 内部 ----------------

    async def _decide(
        self, agent: dict[str, Any], question: str, ctx: GroupContext
    ) -> dict[str, Any]:
        """用该 Agent 自己的模型做 function-calling 决策：search / fetch / none。"""
        prefs = agent.get("model_pref") or {}
        model = self.llm.get_chat_model(
            model=prefs.get("model") or DEFAULT_AGENT_MODEL,
            temperature=0.0,
            max_tokens=DECISION_MAX_TOKENS,
        )
        bound = model.bind_tools([WEB_SEARCH_TOOL, WEB_FETCH_TOOL])
        label = ctx.case_type_label or ctx.case_type or "通用"
        messages = [
            {"role": "system", "content": DECISION_SYSTEM},
            {"role": "user", "content": f"【案情类型】{label}\n【本轮问题】{question}"},
        ]
        resp = await bound.ainvoke(messages)
        tool_calls = getattr(resp, "tool_calls", None) or []
        for call in tool_calls:
            name = str(call.get("name") or "")
            args = call.get("args") or {}
            if name == TOOL_WEB_SEARCH:
                return {"action": TOOL_WEB_SEARCH, "query": args.get("query") or question, "site": args.get("site")}
            if name == TOOL_WEB_FETCH:
                return {"action": TOOL_WEB_FETCH, "url": args.get("url") or ""}
        return {"action": "none"}

    async def _emit_tool(
        self,
        conversation_id: str,
        *,
        agent: dict[str, Any],
        tool: str,
        status: str,
        query: str,
        turn_id: str,
        round_no: int,
        result_count: Optional[int] = None,
        elapsed_ms: Optional[int] = None,
    ) -> None:
        data: dict[str, Any] = {
            "agent_id": str(agent.get("agent_id") or ""),
            "agent_name": str(agent.get("name") or agent.get("agent_id") or ""),
            "tool": tool,
            "status": status,
            "query": query,
            "turn_id": turn_id,
            "round": round_no,
        }
        if result_count is not None:
            data["result_count"] = result_count
        if elapsed_ms is not None:
            data["elapsed_ms"] = elapsed_ms
        await self._emit_safe(conversation_id, EVENT_TOOL, data)

    async def _emit_card(
        self,
        conversation_id: str,
        *,
        agent: dict[str, Any],
        query: str,
        turn_id: str,
        round_no: int,
        results: list[dict[str, Any]],
    ) -> None:
        """联网引用卡：幂等落库后下发 ``message`` 事件（前端按 msg_type=card 渲染）。"""
        event_key = f"{turn_id}:r{round_no}:{agent.get('agent_id')}:{WEB_KEY_SUFFIX}"
        message_id = message_id_for(event_key)

        existing = await self.store.get_message_by_event_key(conversation_id, event_key)
        if existing is not None:
            await self._emit_safe(conversation_id, EVENT_MESSAGE, existing)
            return

        metadata = {
            "message_id": message_id,
            "msg_type": MSG_TYPE_CARD,
            "card_type": CARD_TYPE_WEB,
            "query": query,
            "citations": [
                {
                    "source": str(r.get("site_name") or r.get("url") or "联网"),
                    "title": str(r.get("title") or ""),
                    "url": str(r.get("url") or ""),
                    "content": str(r.get("content") or r.get("snippet") or ""),
                    "score": r.get("rerank_score"),
                }
                for r in results
            ],
        }
        content = _render_web_card_content(query, results)
        record = await self.store.insert_message_once(
            conversation_id,
            event_key=event_key,
            sender_type="tool",
            sender_id=WEB_SENDER_ID,
            sender_name=WEB_SENDER_NAME,
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
            logger.warning("[collab] 联网引用卡热缓存写入失败（忽略）：%s", e)
        await self._emit_safe(conversation_id, EVENT_MESSAGE, record)

    async def _emit_safe(self, conversation_id: str, event_type: str, data: dict[str, Any]) -> None:
        if not conversation_id:
            return
        try:
            await self._emit(conversation_id, event_type, data)
        except Exception as e:
            logger.warning("[collab] 联网事件推送失败（忽略）：%s", e)


def make_web_context(
    *,
    llm: Optional[LLMClient] = None,
    store: Optional[ConversationStore] = None,
    emit: Optional[Emitter] = None,
    client: Optional[WebSearchClient] = None,
    top_n: Optional[int] = None,
    enabled: Optional[bool] = None,
) -> WebContextProvider:
    """构造联网前置决策件（``AgentNodeRunner`` 可注入扩展点）。"""
    return WebContextProvider(
        llm=llm, store=store, emit=emit, client=client, top_n=top_n, enabled=enabled
    )
