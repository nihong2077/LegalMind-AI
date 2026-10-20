"""
统一案情搜索 API（P3 T3.1）

对齐 [collab-ui-refactor_plan.md](../../../../docs/collab-ui-refactor_plan.md) §4.4/§5.5：
单个搜索框，后端**并行四路召回**并分组返回，供前端 Tab 过滤
（`全部 / 法规 / 类案 / 我的记忆 / 会话记录`）。

四路来源：
- ``law``      —— 四级 RAG（``retrieve_legal_knowledge`` domain=law）
- ``judge``    —— 四级 RAG（domain=judge，类案/裁判文书）
- ``memory``   —— 用户长期记忆（Qdrant ``user_memories`` 语义召回 + PG 补水）
- ``messages`` —— 本人会话记录（PG ``messages`` ILIKE，按 ``conversations.user_id`` 隔离）

**失败隔离（fail-open）**：任一路超时/异常只记日志、置空该路结果并写入 ``errors``，
不影响其余三路，也绝不抛出 500。用户隔离：memory/messages 严格按登录用户收敛。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from fastapi import Depends
from pydantic import BaseModel, Field

from ..core.config import settings
from ..core.embedding import embed_text
from ..core.errors import InvalidParamsError
from ..core.response import EnvelopeRouter, success
from ..core.security import get_current_user
from ..services.memory.store import MemoryStore, get_memory_store, is_memory_enabled

logger = logging.getLogger(__name__)

router = EnvelopeRouter(prefix="/api/search", tags=["统一搜索"])

SOURCE_LAW = "law"
SOURCE_JUDGE = "judge"
SOURCE_MEMORY = "memory"
SOURCE_MESSAGES = "messages"
ALL_SOURCES: tuple[str, ...] = (SOURCE_LAW, SOURCE_JUDGE, SOURCE_MEMORY, SOURCE_MESSAGES)

DEFAULT_TOP_K = 5
MAX_TOP_K = 20
DEFAULT_MESSAGE_LIMIT = 10
MAX_MESSAGE_LIMIT = 50

# 单路召回总预算（秒）：超时即按该路失败隔离，不拖垮整体响应
SOURCE_TIMEOUT = 20.0


class UnifiedSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_TOP_K)
    message_limit: int = Field(default=DEFAULT_MESSAGE_LIMIT, ge=1, le=MAX_MESSAGE_LIMIT)
    use_hyde: bool = True
    case_id: Optional[str] = None
    # 可选：仅检索部分来源（前端 Tab 单点过滤）；为空=四路全查
    sources: Optional[list[str]] = None


# ============================================================
# 结果归一化（各路统一形状，前端按 type 渲染）
# ============================================================

def _normalize_knowledge(raw: dict[str, Any], domain: str) -> dict[str, Any]:
    return {
        "type": domain,
        "content": (raw.get("content") or "")[:500],
        "source": raw.get("source") or "系统",
        "score": float(raw.get("score") or 0.0),
        "domain": raw.get("domain") or domain,
        "doc_type": raw.get("doc_type") or "",
    }


def _normalize_memory(row: dict[str, Any], score: Any) -> dict[str, Any]:
    return {
        "type": SOURCE_MEMORY,
        "id": row.get("id"),
        "memory_type": row.get("memory_type"),
        "content": row.get("content") or "",
        "summary": row.get("summary"),
        "importance": row.get("importance"),
        "case_id": row.get("case_id"),
        "score": float(score or 0.0),
        "created_at": row.get("created_at"),
    }


def _normalize_message(msg: Any, title: Optional[str]) -> dict[str, Any]:
    created = getattr(msg, "created_at", None)
    return {
        "type": SOURCE_MESSAGES,
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "conversation_title": title,
        "sender_type": msg.sender_type,
        "sender_name": msg.sender_name,
        "content": msg.content or "",
        "round": msg.round,
        "created_at": created.isoformat() if created else None,
    }


def _escape_like(value: str) -> str:
    """转义 ILIKE 通配符，避免用户输入的 % / _ 变成全匹配。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ============================================================
# 检索实现（测试可 override get_search_backend 注入 fake）
# ============================================================

class SearchBackend:
    """四路召回的真实实现，每路一个独立协程。"""

    def __init__(self, memory_store: Optional[MemoryStore] = None) -> None:
        self._memory_store = memory_store

    @property
    def memory_store(self) -> MemoryStore:
        return self._memory_store or get_memory_store()

    async def law(self, query: str, *, top_k: int, use_hyde: bool) -> list[dict[str, Any]]:
        return await self._rag(query, domain=SOURCE_LAW, top_k=top_k, use_hyde=use_hyde)

    async def judge(self, query: str, *, top_k: int, use_hyde: bool) -> list[dict[str, Any]]:
        return await self._rag(query, domain=SOURCE_JUDGE, top_k=top_k, use_hyde=use_hyde)

    async def _rag(
        self, query: str, *, domain: str, top_k: int, use_hyde: bool
    ) -> list[dict[str, Any]]:
        from ..core.llm_client import get_llm_client
        from ..services.legal.rag_retriever import retrieve_legal_knowledge

        llm = get_llm_client().get_chat_model(
            model="deepseek-flash", temperature=0.3, max_tokens=1024
        )
        results = await retrieve_legal_knowledge(
            query=query, llm=llm, top_k=top_k, use_hyde=use_hyde, domain=domain
        )
        return [_normalize_knowledge(r, domain) for r in (results or [])]

    async def memory(
        self,
        user_id: str,
        query: str,
        *,
        top_k: int,
        case_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        # 总开关关闭 = 不读（与 T2.3 一致）；失败由上层隔离
        if not await is_memory_enabled(user_id):
            return []
        vector = await embed_text(query)
        hits = await self.memory_store.similar(
            user_id,
            vector,
            case_id=case_id,
            top_k=top_k,
            score_threshold=settings.MEMORY_RECALL_MIN_SCORE,
        )
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for hit in hits or []:
            mid = str(hit.get("id") or "").strip()
            if not mid or mid in seen:
                continue
            seen.add(mid)
            row = await self.memory_store.get(user_id, mid)
            if not row or row.get("status") != "active":
                continue
            out.append(_normalize_memory(row, hit.get("score")))
            if len(out) >= top_k:
                break
        return out

    async def messages(
        self, user_id: str, query: str, *, limit: int
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from ..core.pg_client import Conversation, Message, app_session_factory

        pattern = _escape_like(query)
        stmt = (
            select(Message, Conversation.title)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == user_id)
            .where(Message.content.ilike(f"%{pattern}%", escape="\\"))
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        async with app_session_factory() as session:
            rows = (await session.execute(stmt)).all()
        return [_normalize_message(m, title) for m, title in rows]


_search_backend = SearchBackend()


def get_search_backend() -> SearchBackend:
    """进程单例（测试可 override 注入 fake backend）。"""
    return _search_backend


def get_uid(user: dict = Depends(get_current_user)) -> str:
    return user["sub"]


# ============================================================
# 编排：四路并行 + 单路失败隔离
# ============================================================

async def _run_source(name: str, coro: Any) -> tuple[str, list[dict[str, Any]], Optional[str], int]:
    started = time.perf_counter()
    try:
        items = await asyncio.wait_for(coro, timeout=SOURCE_TIMEOUT)
        return name, list(items or []), None, int((time.perf_counter() - started) * 1000)
    except Exception as e:  # 单路失败仅隔离本路，不影响其他路
        logger.warning("[search] %s 路召回失败（已隔离）：%s", name, e)
        return name, [], str(e), int((time.perf_counter() - started) * 1000)


def _resolve_sources(sources: Optional[list[str]]) -> list[str]:
    if not sources:
        return list(ALL_SOURCES)
    bad = [s for s in sources if s not in ALL_SOURCES]
    if bad:
        raise InvalidParamsError(f"未知的搜索来源：{', '.join(bad)}")
    wanted = set(sources)
    return [s for s in ALL_SOURCES if s in wanted]


@router.post("/unified")
async def unified_search(
    body: UnifiedSearchRequest,
    backend: SearchBackend = Depends(get_search_backend),
    uid: str = Depends(get_uid),
):
    selected = _resolve_sources(body.sources)
    query = body.query.strip()
    if not query:
        raise InvalidParamsError("query 不能为空")

    tasks: list[Any] = []
    for name in selected:
        if name == SOURCE_LAW:
            tasks.append(_run_source(name, backend.law(query, top_k=body.top_k, use_hyde=body.use_hyde)))
        elif name == SOURCE_JUDGE:
            tasks.append(_run_source(name, backend.judge(query, top_k=body.top_k, use_hyde=body.use_hyde)))
        elif name == SOURCE_MEMORY:
            tasks.append(
                _run_source(
                    name,
                    backend.memory(uid, query, top_k=body.top_k, case_id=body.case_id),
                )
            )
        elif name == SOURCE_MESSAGES:
            tasks.append(
                _run_source(name, backend.messages(uid, query, limit=body.message_limit))
            )

    gathered = await asyncio.gather(*tasks)

    results: dict[str, list[dict[str, Any]]] = {s: [] for s in ALL_SOURCES}
    errors: dict[str, str] = {}
    took_ms: dict[str, int] = {}
    for name, items, err, ms in gathered:
        results[name] = items
        took_ms[name] = ms
        if err:
            errors[name] = err

    counts = {s: len(results[s]) for s in ALL_SOURCES}
    counts["total"] = sum(counts[s] for s in ALL_SOURCES)
    return success(
        {
            "query": query,
            "results": results,
            "counts": counts,
            "errors": errors,
            "took_ms": took_ms,
        }
    )
