"""对话链路长期记忆召回（P2 T2.3）

对齐 [collab-implementation_plan.md](../../../../docs/collab-implementation_plan.md) §P2 T2.3
与 A1「零侵入」原则：在 ``prepare`` 节点正式编排之前，按**语义**召回该用户 top5 长期记忆，
填入 ``state["memories"]`` —— 由 [agent_nodes.build_group_context](agent_nodes.py) 渲染为
群上下文中的**独立块**「【已召回的用户背景记忆】」（**不覆盖任何 Skill 人设 prompt**），
并下发 ``memory_recall`` **工具进度事件**（``status=running/done/error`` + ``result_count/elapsed_ms``）。

**开关与降级**：
- 总开关关闭（``legalmind:memory:enabled:{user_id}`` = 0）→ **既不读也不写**，直接返回空；
- 嵌入/向量库/PG 任一异常 → 记日志 + ``tool:error``，返回空记忆，**绝不阻断本轮编排**（fail-open）。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from ...core.config import settings
from ...core.embedding import embed_text
from .agent_nodes import Emitter, _default_emit, _latest_question
from ..memory.store import MemoryStore, get_memory_store, is_memory_enabled

logger = logging.getLogger(__name__)

EVENT_TOOL = "tool"
TOOL_STATUS_RUNNING = "running"
TOOL_STATUS_DONE = "done"
TOOL_STATUS_ERROR = "error"

# 记忆召回的「工具」标识（前端进度条 tool 字段）
TOOL_MEMORY_RECALL = "memory_recall"

# 进度条发送者（合成工具身份，非注册表 Agent）——前端要求 agent_id 非空
MEMORY_SENDER_ID = "memory_recall"
MEMORY_SENDER_NAME = "记忆召回"


class MemoryRecallProvider:
    """语义召回 + 事件下发（注入 ``prepare`` 节点的可调用件）。"""

    def __init__(
        self,
        *,
        memory_store: Optional[MemoryStore] = None,
        emit: Optional[Emitter] = None,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self._memory_store = memory_store
        self._emit = emit or _default_emit
        self.top_k = int(top_k if top_k is not None else settings.MEMORY_RECALL_TOP_K)
        self.min_score = float(
            min_score if min_score is not None else settings.MEMORY_RECALL_MIN_SCORE
        )
        self.enabled = True if enabled is None else bool(enabled)

    @property
    def memory_store(self) -> MemoryStore:
        return self._memory_store or get_memory_store()

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.recall(state)

    async def recall(self, state: dict[str, Any]) -> dict[str, Any]:
        """返回 ``{"memories": [...]}``（命中时）或 ``{}``；副作用：``memory_recall`` tool 事件。"""
        if not self.enabled:
            return {}
        user_id = str(state.get("user_id") or "").strip()
        if not user_id:
            return {}
        question = _latest_question(state)
        if not question:
            return {}

        conversation_id = str(state.get("conversation_id") or "")
        turn_id = str(state.get("turn_id") or "")
        round_no = int(state.get("round", 0))

        try:
            if not await is_memory_enabled(user_id):
                logger.info("[collab] 用户已关闭记忆，跳过召回 user=%s", user_id)
                return {}
        except Exception as e:  # Redis 降级按默认开启
            logger.warning("[collab] 读取记忆开关失败，按默认开启处理：%s", e)

        await self._emit_tool(
            conversation_id,
            status=TOOL_STATUS_RUNNING,
            query=question,
            turn_id=turn_id,
            round_no=round_no,
        )

        started = time.perf_counter()
        try:
            vector = await embed_text(question)
            hits = await self.memory_store.similar(
                user_id, vector, top_k=self.top_k, score_threshold=self.min_score
            )
            memories = await self._hydrate(user_id, hits)
        except Exception as e:  # 召回失败 → 空记忆 + tool:error，不阻断本轮
            logger.warning("[collab] 记忆召回失败（忽略，不阻断本轮）：%s", e)
            await self._emit_tool(
                conversation_id,
                status=TOOL_STATUS_ERROR,
                query=question,
                turn_id=turn_id,
                round_no=round_no,
                result_count=0,
            )
            return {}

        elapsed = int((time.perf_counter() - started) * 1000)
        await self._emit_tool(
            conversation_id,
            status=TOOL_STATUS_DONE,
            query=question,
            turn_id=turn_id,
            round_no=round_no,
            result_count=len(memories),
            elapsed_ms=elapsed,
        )
        if not memories:
            return {}
        return {"memories": memories}

    # ---------------- 内部 ----------------

    async def _hydrate(self, user_id: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """向量 payload 不含 ``content``，回 PG 逐条补水并按 ``status=active`` 过滤。"""
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for hit in hits or []:
            mid = str(hit.get("id") or "").strip()
            if not mid or mid in seen:
                continue
            seen.add(mid)
            try:
                row = await self.memory_store.get(user_id, mid)
            except Exception as e:  # 单条补水失败只跳过该条
                logger.warning("[collab] 记忆补水失败（跳过）id=%s：%s", mid, e)
                continue
            if not row or row.get("status") != "active":
                continue
            if not str(row.get("content") or "").strip():
                continue
            out.append({**row, "score": hit.get("score")})
            if len(out) >= self.top_k:
                break
        return out

    async def _emit_tool(
        self,
        conversation_id: str,
        *,
        status: str,
        query: str,
        turn_id: str,
        round_no: int,
        result_count: Optional[int] = None,
        elapsed_ms: Optional[int] = None,
    ) -> None:
        if not conversation_id:
            return
        data: dict[str, Any] = {
            "agent_id": MEMORY_SENDER_ID,
            "agent_name": MEMORY_SENDER_NAME,
            "tool": TOOL_MEMORY_RECALL,
            "status": status,
            "query": query,
            "turn_id": turn_id,
            "round": round_no,
        }
        if result_count is not None:
            data["result_count"] = result_count
        if elapsed_ms is not None:
            data["elapsed_ms"] = elapsed_ms
        try:
            await self._emit(conversation_id, EVENT_TOOL, data)
        except Exception as e:  # 事件推送失败不影响召回结果
            logger.warning("[collab] 记忆召回事件推送失败（忽略）：%s", e)


def make_memory_recall(
    *,
    memory_store: Optional[MemoryStore] = None,
    emit: Optional[Emitter] = None,
    top_k: Optional[int] = None,
    min_score: Optional[float] = None,
    enabled: Optional[bool] = None,
) -> MemoryRecallProvider:
    """构造记忆召回件（``build_collab_graph`` 可注入扩展点）。"""
    return MemoryRecallProvider(
        memory_store=memory_store, emit=emit, top_k=top_k, min_score=min_score, enabled=enabled
    )
