"""轮次发言分隔条生产者（隐藏主持人身份）

用户可见的「分隔条」：每轮开始前，把「下一个发言人」以**中性**系统提示的形式
显性化一条「下面是 X 发言」，无背景、小字居中；**绝不暴露主持人/调度身份**。

对齐 [collab-ui-refactor_plan §4.2](../../../../docs/collab-ui-refactor_plan.md)
（系统状态条）与 §5.4（SSE v2 ``message`` 事件）：

- 幂等落库：``sender_type="system"``、``msg_type="notice"``，
  ``event_key={turn_id}:r{round}:notice:0``（第 3 段用 ``notice``，**避开** Agent 流式
  用的 ``{agent_id}``），``message_id = uuid5(event_key)``；
- 「先查库后发」：``event_key`` 已落库则复用既有记录并重发事件（重跑/恢复不重复生成）；
- 热缓存 + ``message`` 事件：刷新后仍可见；
- **fail-open**：任何异常只记日志，绝不阻断整轮（对齐 A1「代码只做护栏」）。

``metadata.kind="speaker_notice"`` 供前端区分该分隔条与其它 ``system`` 通知
（成员变动等），从而只对该条应用「无背景、小字居中」样式。
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from ...core.redis_client import push_recent_message
from .agent_nodes import Emitter, _default_emit, make_event_key, message_id_for
from .conversation_store import ConversationStore, pg_store

logger = logging.getLogger(__name__)

EVENT_MESSAGE = "message"

# 落库字段（与 DB CHECK 约束一致：sender_type=system 合法，msg_type=notice 合法）
SENDER_TYPE = "system"
SENDER_ID = "system"
SENDER_NAME = "系统"
MSG_TYPE_NOTICE = "notice"
KIND_SPEAKER_NOTICE = "speaker_notice"

# event_key 第 3 段固定为 "notice"，与 Agent 流式键（第 3 段为 agent_id）天然不冲突
NOTICE_KEY_SEGMENT = "notice"

# 分隔条文案模板：用户要求「下面是 X 发言」
NOTICE_TEMPLATE = "下面是 {name} 发言"

# 注入点签名：(state, speaker_id, speaker_name) -> None
SpeakerNotice = Callable[[dict[str, Any], str, str], Awaitable[None]]


def _render_notice(speaker_name: str, speaker_id: str) -> str:
    return NOTICE_TEMPLATE.format(name=speaker_name or speaker_id)


def make_speaker_notice(
    *,
    store: Optional[ConversationStore] = None,
    emit: Optional[Emitter] = None,
) -> SpeakerNotice:
    """构造 ``speaker_notice``（``build_collab_graph`` 可注入扩展点）。"""
    _store = store
    _emit = emit or _default_emit

    async def _notice(state: dict[str, Any], speaker_id: str, speaker_name: str) -> None:
        conversation_id = str(state.get("conversation_id") or "")
        turn_id = str(state.get("turn_id") or "")
        # 分隔条对应「即将开始」的轮次：scheduler 调用后 state["round"] 才 +1
        round_no = int(state.get("round", 0)) + 1
        if not conversation_id or not turn_id or not speaker_id:
            return

        event_key = make_event_key(turn_id, round_no, NOTICE_KEY_SEGMENT, 0)
        message_id = message_id_for(event_key)
        content = _render_notice(speaker_name, speaker_id)
        st: ConversationStore = _store or pg_store

        try:
            existing = await st.get_message_by_event_key(conversation_id, event_key)
            if existing is not None:
                # 「先查库后发」：重跑/恢复复用既有分隔条（幂等）
                await _emit(conversation_id, EVENT_MESSAGE, existing)
                return

            metadata = {
                "message_id": message_id,
                "msg_type": MSG_TYPE_NOTICE,
                "kind": KIND_SPEAKER_NOTICE,
                "round": round_no,
                "speaker_id": speaker_id,
                "speaker_name": speaker_name,
            }
            record = await st.insert_message_once(
                conversation_id,
                event_key=event_key,
                sender_type=SENDER_TYPE,
                sender_id=SENDER_ID,
                sender_name=SENDER_NAME,
                content=content,
                msg_type=MSG_TYPE_NOTICE,
                round=round_no,
                metadata=metadata,
            )
            if record is None:
                record = await st.get_message_by_event_key(conversation_id, event_key)
            if record is None:
                return
            try:
                await push_recent_message(conversation_id, record)
            except Exception as e:  # 热缓存仅加速，降级不影响业务
                logger.warning("[collab] 分隔条热缓存写入失败（忽略）：%s", e)
            await _emit(conversation_id, EVENT_MESSAGE, record)
        except Exception as e:  # fail-open：分隔条失败绝不阻断整轮
            logger.warning("[collab] 轮次分隔条产出失败（忽略）：%s", e)

    return _notice
