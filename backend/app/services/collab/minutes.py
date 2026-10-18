"""会商纪要生成（T1.9-M2）

对齐 [docs/collab-ui-refactor_plan.md](../../../../docs/collab-ui-refactor_plan.md) §5.3⑤ / §5.5：

- **手动触发**：用户在群内点「生成会商纪要」→ ``POST /api/conversations/{id}/minutes``；
  由书记员（``clerk``）汇总本会话各方观点，产出《会商纪要》并以 ``msg_type=minutes`` 落库。
- **S1 流式**：token 级 —— ``message_start``（分配 message_id + event_key）→ 多帧 ``message_delta``
  → ``message_end``（定稿落库），与 Agent 辐条（``agent_nodes``）同一事件协议。
- **幂等**：``event_key = {conversation_id}:minutes:r{round}``、``message_id = uuid5(event_key)``；
  「先查库后发」——同一轮次的纪要已存在则直接复用，不重复生成/推送。

本模块为**可注入服务**（llm/store/emit/registry 均可替换），不建图、无固定边；
旧 ``/debate/stream`` 等链路不受影响（A3 红线）。
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Optional

from ...core.errors import InvalidParamsError, NotFoundError
from ...core.llm_client import LLMClient, get_llm_client
from ...core.redis_client import push_recent_message
from .agent_nodes import (
    EVENT_DELTA,
    EVENT_END,
    EVENT_START,
    Emitter,
    message_id_for,
    _default_emit,
)
from .conversation_store import ConversationStore, pg_store
from .registry import RegistryService, get_registry

logger = logging.getLogger(__name__)

DEFAULT_MINUTES_MODEL = "deepseek-v4-pro"
MSG_TYPE_MINUTES = "minutes"
EVENT_STATUS = "status"

# 纪要产出者身份：优先取群内书记员（clerk），退化为通用「书记员」
CLERK_AGENT_ID = "clerk"
CLERK_FALLBACK_NAME = "书记员"

# 供纪要取用的历史消息条数（覆盖整场会商）
MINUTES_HISTORY_LIMIT = 200

MINUTES_SYSTEM_PROMPT = """你是一名专业的会商纪要整理人（书记员）。请根据给定的会商记录，
客观、凝练地整理一份《会商纪要》，供与会各方留档与后续执行参考。

要求：
1. 只归纳记录中真实出现的内容，不臆造事实或法律结论；
2. 用中性、专业的书面语，不必复述全部细节，重在提炼观点与共识；
3. 严格按以下 Markdown 结构输出，不要添加其它一级标题：

# 会商纪要
## 一、会商议题
## 二、各方观点
（按发言主体分条，注明其主要主张与依据）
## 三、争议焦点
## 四、结论与建议
## 五、待办事项
（若无明确待办，写「暂无」）"""


def _speaker_label(msg: dict[str, Any]) -> str:
    """消息发言人标签（用户 / 主持人 / Agent / 系统）。"""
    stype = str(msg.get("sender_type") or "agent")
    name = str(msg.get("sender_name") or msg.get("sender_id") or "")
    if stype == "user":
        return f"用户（{name}）" if name else "用户"
    if stype == "host":
        return f"主持人·{name}"
    if stype == "tool":
        return f"工具·{name}"
    if stype == "system":
        return "系统"
    return name or "成员"


def build_minutes_material(conversation: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    """把会话记录拼成供纪要撰写的材料（议题 + 逐条发言人/正文）。"""
    title = str(conversation.get("title") or "").strip() or "未命名会商"
    case_type = str(conversation.get("case_type") or "").strip()
    lines: list[str] = [f"会商主题：{title}"]
    if case_type:
        lines.append(f"案情类型：{case_type}")
    lines.append("会商记录如下：")
    for m in messages:
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"- [{_speaker_label(m)}] {content}")
    return "\n".join(lines)


class MinutesRunner:
    """会商纪要产出器（注入 router / 测试可整体替换）。"""

    def __init__(
        self,
        *,
        llm: Optional[LLMClient] = None,
        store: Optional[ConversationStore] = None,
        registry: Optional[RegistryService] = None,
        emit: Optional[Emitter] = None,
        model: str = DEFAULT_MINUTES_MODEL,
    ) -> None:
        self._llm = llm
        self._store = store
        self._registry = registry
        self._emit = emit or _default_emit
        self._model = model

    @property
    def llm(self) -> LLMClient:
        return self._llm or get_llm_client()

    @property
    def store(self) -> ConversationStore:
        return self._store or pg_store

    @staticmethod
    def event_key(conversation_id: str, round_no: int) -> str:
        return f"{conversation_id}:minutes:r{int(round_no)}"

    async def generate(
        self, conversation_id: str, *, round_no: Optional[int] = None
    ) -> dict[str, Any]:
        """生成（或复用）指定会话的会商纪要；token 级流式 + 幂等落库。

        Returns:
            ``{"message": 落库消息 dict, "event_id": Redis Stream id 或 None, "reused": bool}``
        """
        conv = await self.store.get_conversation(conversation_id)
        if conv is None:
            raise NotFoundError("会话不存在")

        rows, _ = await self.store.list_messages_page(
            conversation_id, None, MINUTES_HISTORY_LIMIT
        )
        if not rows:
            raise InvalidParamsError("暂无可整理的会商记录")

        if round_no is None:
            round_no = max((int(m.get("round") or 0) for m in rows), default=0)
        event_key = self.event_key(conversation_id, round_no)

        # 「先查库后发」：同一轮次纪要已存在 → 直接复用（不重复生成/推送）
        existing = await self.store.get_message_by_event_key(conversation_id, event_key)
        if existing is not None:
            logger.info("[collab] 纪要已存在，复用（幂等）：%s", event_key)
            return {"message": existing, "event_id": None, "reused": True}

        sender_id, sender_name = await self._resolve_sender(conv)
        message_id = message_id_for(event_key)
        sender = {"type": "agent", "id": sender_id, "name": sender_name}
        base = {"message_id": message_id, "event_key": event_key, "round": round_no, "sender": sender}

        await self._emit_safe(
            conversation_id,
            EVENT_STATUS,
            {"phase": "minutes", "message": "正在生成会商纪要…", "round": round_no},
        )
        await self._emit_safe(conversation_id, EVENT_START, {**base, "type": MSG_TYPE_MINUTES})

        material = build_minutes_material(conv, rows)
        chunks: list[str] = []
        async for chunk in self._stream(material):
            chunks.append(chunk)
            await self._emit_safe(
                conversation_id, EVENT_DELTA, {"message_id": message_id, "delta": chunk}
            )
        content = "".join(chunks)

        await self._emit_safe(
            conversation_id,
            EVENT_END,
            {**base, "content": content, "metadata": {"msg_type": MSG_TYPE_MINUTES}},
        )

        record = await self.store.insert_message_once(
            conversation_id,
            event_key=event_key,
            sender_type="agent",
            sender_id=sender_id,
            sender_name=sender_name,
            content=content,
            msg_type=MSG_TYPE_MINUTES,
            round=round_no,
            metadata={"message_id": message_id, "msg_type": MSG_TYPE_MINUTES},
        )
        if record is not None:
            try:
                await push_recent_message(conversation_id, record)
            except Exception as e:  # 热缓存仅加速，降级不影响业务
                logger.warning("[collab] 纪要热缓存写入失败（忽略）：%s", e)
        else:
            # 并发/重跑：落库被幂等挡住 → 取既有记录返回
            record = await self.store.get_message_by_event_key(conversation_id, event_key)
        return {"message": record, "event_id": None, "reused": False}

    async def _resolve_sender(self, conv: dict[str, Any]) -> tuple[str, str]:
        """发言人：群内书记员优先，否则通用「书记员」。"""
        members = conv.get("members") or []
        for m in members:
            if str(m.get("agent_id") or "") == CLERK_AGENT_ID:
                return CLERK_AGENT_ID, str(m.get("name") or CLERK_FALLBACK_NAME)
        return CLERK_AGENT_ID, CLERK_FALLBACK_NAME

    async def _stream(self, material: str) -> AsyncIterator[str]:
        messages = [
            {"role": "system", "content": MINUTES_SYSTEM_PROMPT},
            {"role": "user", "content": material},
        ]
        async for chunk in self.llm.chat_stream(
            model=self._model, messages=messages, temperature=0.3, max_tokens=4096
        ):
            choices = chunk.get("choices") or [{}]
            delta = (choices[0].get("delta") or {}).get("content") or ""
            if delta:
                yield delta

    async def _emit_safe(self, conversation_id: str, event_type: str, data: dict[str, Any]) -> None:
        """事件推送失败不阻断纪要生成（Redis 降级时静默）。"""
        try:
            await self._emit(conversation_id, event_type, data)
        except Exception as e:
            logger.warning("[collab] 纪要事件推送失败（忽略）：%s", e)


# ============================================================
# API 进程内单例（测试可 override 注入假 runner）
# ============================================================

_minutes_singleton: Optional[MinutesRunner] = None


def get_minutes_runner() -> MinutesRunner:
    """API 路由依赖：进程内单例纪要产出器。"""
    global _minutes_singleton
    if _minutes_singleton is None:
        _minutes_singleton = MinutesRunner()
    return _minutes_singleton


def reset_minutes_runner() -> None:
    """显式失效缓存（测试注入后调用）。"""
    global _minutes_singleton
    _minutes_singleton = None
