"""
协同会话 / 群 / 成员 / 消息 API（T1.1）

- 全部走统一信封（EnvelopeRouter）；
- PG 权威 + Redis 最近 20 条热缓存（10min TTL）；
- 用户发言前检查同群轮次锁，冲突抛 50901（锁由 T1.6 runner 持有/释放）；
- 消息/通知同步写入 Redis Stream + Pub/Sub，供 collab.py 的 SSE 订阅
  做断线回放与实时桥接。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import Depends, Query
from pydantic import BaseModel, Field

from ..core.config import settings
from ..core.errors import (
    ForbiddenError,
    InvalidParamsError,
    NotFoundError,
    TurnLockConflictError,
)
from ..core.events import event_bus
from ..core.redis_client import (
    append_conv_event,
    get_recent_messages,
    get_turn_lock_holder,
    push_recent_message,
    set_recent_messages,
)
from ..core.response import EnvelopeRouter, success
from ..core.security import get_current_user
from ..services.collab.conversation_store import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    ConversationStore,
    pg_store,
)
from ..services.collab.runner import TurnRunner, get_turn_runner as _get_turn_runner
from ..services.collab.minutes import MinutesRunner, get_minutes_runner as _get_minutes_runner
from ..services.collab.turn_store import (
    MODE_INPROCESS,
    MODE_KAFKA,
    TURN_INTERRUPTED,
    TURN_RUNNING,
)

logger = logging.getLogger(__name__)

router = EnvelopeRouter(prefix="/api/conversations", tags=["协同会话"])


# ============================================================
# 依赖
# ============================================================

def get_store() -> ConversationStore:
    return pg_store


def get_turn_runner() -> TurnRunner:
    """进程内轮次执行器（测试可 override 注入假/真 runner）。"""
    return _get_turn_runner()

def get_minutes_runner() -> MinutesRunner:
    """进程内纪要产出器（测试可 override 注入假 runner）。"""
    return _get_minutes_runner()


async def get_uid(user: dict = Depends(get_current_user)) -> str:
    return user["sub"]


async def require_owned_conversation(
    conversation_id: str,
    store: ConversationStore = Depends(get_store),
    uid: str = Depends(get_uid),
) -> dict[str, Any]:
    conv = await store.get_conversation(conversation_id)
    if conv is None:
        raise NotFoundError("会话不存在")
    if conv["user_id"] != uid:
        raise ForbiddenError("无权访问该会话")
    return conv


# ============================================================
# 请求模型
# ============================================================

class CreateConversationRequest(BaseModel):
    type: str = Field(pattern="^(direct|group)$")
    case_type: Optional[str] = None
    # B3 建群向导：template_id 即 case_type（给了按模板自动铺 roster 与 host）
    template_id: Optional[str] = None
    title: Optional[str] = None
    agent_ids: list[str] = Field(default_factory=list)
    # B3 用户扮演的 agent_id（选填；仅 group 有效，必须 ∈ 最终 roster）
    my_role: Optional[str] = Field(default=None, max_length=64)
    # B1 单聊目标 Agent（仅 direct 必填，∈ 10 Agent）
    target_agent_id: Optional[str] = Field(default=None, max_length=64)


class UpdateConversationRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=256)
    status: Optional[str] = Field(default=None, pattern="^(active|archived)$")


class AddMemberRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)


class SetMyRoleRequest(BaseModel):
    # B2 跨轮扮演开关：空＝不扮演（交还给 AI），非空须 ∈ 会话成员（仅群聊）
    my_role: Optional[str] = Field(default=None, max_length=64)


class SendMessageRequest(BaseModel):
    # content 允许为空仅用于「交还给 AI」控制动作（metadata.hand_back=true），
    # 其余场景在 send_message 内校验非空（统一 40001，而非 pydantic 422）
    content: str = Field(default="")
    msg_type: str = Field(default="text", pattern="^(text|card|minutes)$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ForkTurnRequest(BaseModel):
    checkpoint_id: str = Field(min_length=1)
    # fork 时叠加的事实修正（写入新轮次初值）
    update: Optional[dict[str, Any]] = None


class ForwardMessageRequest(BaseModel):
    """转发搜索结果到会话（T3.2）：仅作上下文卡片，不触发轮次。

    - ``citations`` 对齐前端引用卡渲染形状（source/title/url/content/score）；
    - ``content`` 为可读正文，落库后进入后续轮次的共享上下文窗，供 Agent 引用。
    """
    card_type: str = Field(default="reference", max_length=64)
    citations: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    content: str = Field(default="", max_length=4000)


# ============================================================
# 事件辅助
# ============================================================

async def _emit_message(conversation_id: str, message: dict[str, Any]) -> str:
    """消息以 SSE v2 message 事件形状广播（collab-ui-refactor_plan §5.4）。"""
    data = {
        "id": message["id"],
        "sender": {
            "type": message["sender_type"],
            "id": message["sender_id"],
            "name": message.get("sender_name") or message["sender_id"],
        },
        "content": message["content"],
        "msg_type": message["msg_type"],
        "round": message["round"],
        "created_at": message["created_at"],
        "metadata": message.get("metadata") or {},
    }
    return await append_conv_event(conversation_id, "message", data)


async def _append_notice(
    store: ConversationStore,
    conversation_id: str,
    content: str,
) -> dict[str, Any]:
    """成员变动等系统通知：落 PG transcript、进热缓存、广播。"""
    message = await store.insert_message(
        conversation_id,
        sender_type="system",
        sender_id="system",
        sender_name="系统",
        content=content,
        msg_type="notice",
        round=0,
        metadata=None,
    )
    await push_recent_message(conversation_id, message)
    await _emit_message(conversation_id, message)
    return message


# ============================================================
# 会话
# ============================================================

@router.get("")
async def list_conversations(
    status: Optional[str] = None,
    store: ConversationStore = Depends(get_store),
    uid: str = Depends(get_uid),
):
    if status is not None and status not in ("active", "archived"):
        raise InvalidParamsError("status 仅支持 active/archived")
    conversations = await store.list_conversations(uid, status=status)
    return success({"conversations": conversations, "total": len(conversations)})


@router.post("", status_code=201)
async def create_conversation(
    body: CreateConversationRequest,
    store: ConversationStore = Depends(get_store),
    uid: str = Depends(get_uid),
):
    # 类型专属字段规则（B1/B3，越界即 40001）
    if body.type == "direct":
        if not body.target_agent_id:
            raise InvalidParamsError("单聊必须指定 target_agent_id")
        if body.my_role:
            raise InvalidParamsError("单聊不支持 my_role（扮演仅群聊可用）")
    else:  # group
        if body.target_agent_id:
            raise InvalidParamsError("群聊不支持 target_agent_id")

    conversation = await store.create_conversation(
        user_id=uid,
        conv_type=body.type,
        case_type=body.template_id or body.case_type,
        title=body.title,
        extra_agent_ids=body.agent_ids,
        my_role=body.my_role,
        target_agent_id=body.target_agent_id,
    )
    return success(conversation, message="会话已创建")


@router.get("/{conversation_id}")
async def get_conversation(
    conversation: dict = Depends(require_owned_conversation),
):
    return success(conversation)


@router.patch("/{conversation_id}")
async def update_conversation(
    body: UpdateConversationRequest,
    store: ConversationStore = Depends(get_store),
    conversation: dict = Depends(require_owned_conversation),
):
    updated = await store.update_conversation(
        conversation["id"], title=body.title, status=body.status
    )
    return success(updated)


@router.delete("/{conversation_id}")
async def archive_conversation(
    store: ConversationStore = Depends(get_store),
    conversation: dict = Depends(require_owned_conversation),
):
    archived = await store.update_conversation(conversation["id"], status="archived")
    return success(archived, message="会话已归档")


# ============================================================
# 成员
# ============================================================

@router.post("/{conversation_id}/members", status_code=201)
async def add_member(
    body: AddMemberRequest,
    store: ConversationStore = Depends(get_store),
    conversation: dict = Depends(require_owned_conversation),
):
    member = await store.add_member(conversation["id"], body.agent_id, is_auto=False)
    await _append_notice(store, conversation["id"], f"{member.get('name', body.agent_id)} 已加入会商")
    return success(member, message="成员已添加")


@router.delete("/{conversation_id}/members")
async def remove_member(
    agent_id: str,
    store: ConversationStore = Depends(get_store),
    conversation: dict = Depends(require_owned_conversation),
):
    if not agent_id:
        raise InvalidParamsError("缺少 agent_id")
    member = next(
        (m for m in conversation["members"] if m["agent_id"] == agent_id), None
    )
    removed = await store.remove_member(conversation["id"], agent_id)
    if not removed:
        raise NotFoundError("该 Agent 不在会话中")
    name = member.get("name", agent_id) if member else agent_id
    await _append_notice(store, conversation["id"], f"{name} 已退出会商")
    return success({"agent_id": agent_id}, message="成员已移除")


@router.post("/{conversation_id}/my_role")
async def set_my_role(
    body: SetMyRoleRequest,
    store: ConversationStore = Depends(get_store),
    conversation: dict = Depends(require_owned_conversation),
):
    """设置/撤销用户扮演角色（跨轮持久化，仅群聊；空＝不扮演＝交还给 AI）。"""
    if conversation["type"] != "group":
        raise InvalidParamsError("仅群聊支持扮演角色")
    if body.my_role:
        member_ids = {m["agent_id"] for m in conversation["members"]}
        if body.my_role not in member_ids:
            raise InvalidParamsError("my_role 不在会话成员中")
    updated = await store.set_my_role(conversation["id"], body.my_role)
    return success(updated, message="已更新扮演角色")


# ============================================================
# 消息
# ============================================================

@router.get("/{conversation_id}/messages")
async def list_messages(
    before: Optional[str] = None,
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    store: ConversationStore = Depends(get_store),
    conversation: dict = Depends(require_owned_conversation),
):
    conversation_id = conversation["id"]

    # 首页（无上拉游标）走 Redis 热缓存；翻历史页直接读 PG
    if before is None:
        cached = await get_recent_messages(conversation_id)
        if cached is not None:
            page = cached[-limit:]
            next_before = page[0]["id"] if len(cached) >= limit else None
            return success({"messages": page, "next_before": next_before, "cached": True})

    messages, next_before = await store.list_messages_page(conversation_id, before, limit)
    if before is None and messages:
        # 回填热缓存（失败不影响响应，缓存仅做加速）
        try:
            await set_recent_messages(conversation_id, messages)
        except Exception as e:  # pragma: no cover - 缓存降级
            logger.warning("热缓存回填失败（忽略）：%s", e)
    return success(
        {"messages": messages, "next_before": next_before, "cached": False}
    )


async def _persist_user_message(
    store: ConversationStore,
    conversation_id: str,
    *,
    uid: str,
    content: str,
    msg_type: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """用户发言落库 + 热缓存 + SSE 广播（接管发言经 metadata.actor_agent_id 标记角色）。"""
    message = await store.insert_message(
        conversation_id,
        sender_type="user",
        sender_id=uid,
        sender_name=metadata.get("actor_agent_name") or uid,
        content=content,
        msg_type=msg_type,
        round=0,  # 轮次编号由 runner 编排时回写（T1.6）
        metadata=metadata,
    )
    await push_recent_message(conversation_id, message)
    event_id = await _emit_message(conversation_id, message)
    return {"message": message, "event_id": event_id}


@router.post("/{conversation_id}/messages", status_code=201)
async def send_message(
    body: SendMessageRequest,
    store: ConversationStore = Depends(get_store),
    conversation: dict = Depends(require_owned_conversation),
    uid: str = Depends(get_uid),
    runner: TurnRunner = Depends(get_turn_runner),
):
    conversation_id = conversation["id"]
    content = body.content or ""
    hand_back = body.metadata.get("hand_back") is True
    conclude = body.metadata.get("conclude") is True
    if not content.strip() and not hand_back and not conclude:
        raise InvalidParamsError("消息内容不能为空")

    # 1) 存在未终态轮次：本条消息即「续跑输入」（ask_user 补证 / 接管发言 / 交还给 AI / 结束会商）
    open_turn = await runner.store.get_open_turn(conversation_id)
    if open_turn is not None:
        if open_turn["status"] != TURN_INTERRUPTED:
            # running：仍在执行中（T1.6 会商进行中）→ 50901
            raise TurnLockConflictError()
        return await _resume_message(
            store=store,
            runner=runner,
            conversation_id=conversation_id,
            turn_id=open_turn["turn_id"],
            uid=uid,
            body=body,
            content=content,
            hand_back=hand_back,
            conclude=conclude,
        )

    # 1b) 「结束会商」但无挂起轮次：无进行中的会商可收尾
    if conclude:
        raise InvalidParamsError("当前没有进行中的会商，无法结束")

    # 2) 轮次锁兜底（他人持锁但未登记 open turn 的边界）
    holder = await get_turn_lock_holder(conversation_id)
    if holder is not None:
        raise TurnLockConflictError()

    # 3) 落库用户消息 + 广播 + 起新轮次（Kafka 关：进程内执行；开：入队由 worker 消费）
    persisted = await _persist_user_message(
        store, conversation_id, uid=uid, content=content,
        msg_type=body.msg_type, metadata=body.metadata,
    )

    mode = MODE_KAFKA if settings.ENABLE_KAFKA else MODE_INPROCESS
    turn = await runner.store.create_turn(
        conversation_id, uid, mode=mode, trigger_message_id=persisted["message"]["id"]
    )
    turn_id = turn["turn_id"]

    outcome = None
    if mode == MODE_KAFKA:
        published = await event_bus.publish(
            settings.KAFKA_TOPIC_TURNS,
            {"turn_id": turn_id, "conversation_id": conversation_id, "user_id": uid},
            key=conversation_id,
        )
        if not published:  # broker 降级 → 进程内兜底（不阻断业务）
            logger.warning("[turn] Kafka 入队降级，进程内执行 turn=%s", turn_id)
            outcome = await runner.execute_turn(turn_id)
    else:
        outcome = await runner.execute_turn(turn_id)

    return success(
        {
            "message": persisted["message"],
            "event_id": persisted["event_id"],
            "turn_id": turn_id,
            "status": outcome.status if outcome is not None else TURN_RUNNING,
        },
        message="已发送",
    )


async def _resume_message(
    *,
    store: ConversationStore,
    runner: TurnRunner,
    conversation_id: str,
    turn_id: str,
    uid: str,
    body: SendMessageRequest,
    content: str,
    hand_back: bool,
    conclude: bool = False,
):
    """把用户输入作为 ``Command(resume=...)`` 送进挂起轮次并续跑。"""
    if conclude:
        # 用户主权（F6）：注入 {"action": "conclude"} → 图内 ask_user/接管节点 Command(goto=conclude) 收尾
        outcome = await runner.resume_turn(turn_id, {"action": "conclude"})
        return success(
            {"message": None, "event_id": None, "turn_id": turn_id, "status": outcome.status},
            message="已结束会商",
        )
    if hand_back:
        # 撤销接管（跨轮持久化 conversations.my_role=NULL）：控制动作不落聊天气泡
        try:
            await store.set_my_role(conversation_id, None)
        except Exception as e:  # 落库失败不阻断续跑
            logger.warning("撤销接管标志失败（忽略）：%s", e)
        outcome = await runner.resume_turn(turn_id, {"action": "hand_back"})
        return success(
            {"message": None, "event_id": None, "turn_id": turn_id, "status": outcome.status},
            message="已交还给 AI",
        )

    persisted = await _persist_user_message(
        store, conversation_id, uid=uid, content=content,
        msg_type=body.msg_type, metadata=body.metadata,
    )
    outcome = await runner.resume_turn(turn_id, content)
    return success(
        {
            "message": persisted["message"],
            "event_id": persisted["event_id"],
            "turn_id": turn_id,
            "status": outcome.status,
        },
        message="已续跑",
    )


# ============================================================
# 会商纪要（T1.9-M2）
# ============================================================

@router.post("/{conversation_id}/forward", status_code=201)
async def forward_to_conversation(
    body: ForwardMessageRequest,
    store: ConversationStore = Depends(get_store),
    conversation: dict = Depends(require_owned_conversation),
    uid: str = Depends(get_uid),
):
    """把搜索结果作为「上下文卡片」转发进会话（T3.2）。

    与 ``send_message`` 的关键差异：**不起新轮次**。仅落库 + 进热缓存 + SSE 广播，
    使该卡片进入后续轮次的共享上下文窗，供 Agent 在讨论中引用。
    """
    conversation_id = conversation["id"]
    if not body.content.strip() and not body.citations:
        raise InvalidParamsError("转发内容不能为空")

    metadata = {
        "forwarded": True,
        "card_type": body.card_type,
        "citations": body.citations,
        "forward_source": "search",
    }
    message = await store.insert_message(
        conversation_id,
        sender_type="user",
        sender_id=uid,
        sender_name=uid,
        content=body.content,
        msg_type="card",
        round=0,
        metadata=metadata,
    )
    await push_recent_message(conversation_id, message)
    event_id = await _emit_message(conversation_id, message)
    return success(
        {"message": message, "event_id": event_id, "turn_id": None, "status": "forwarded"},
        message="已转发",
    )


@router.post("/{conversation_id}/minutes", status_code=201)
async def generate_minutes(
    conversation: dict = Depends(require_owned_conversation),
    runner: MinutesRunner = Depends(get_minutes_runner),
):
    """手动生成《会商纪要》：书记员汇总本会话各方观点，token 级流式产出并落库（msg_type=minutes）。"""
    result = await runner.generate(conversation["id"])
    reused = bool(result.get("reused"))
    return success(
        {
            "message": result.get("message"),
            "event_id": result.get("event_id"),
            "reused": reused,
        },
        message="已复用既有会商纪要" if reused else "已生成会商纪要",
    )

# ============================================================
# 轮次：checkpoint 时间线 / fork（T1.6 §3.3）
# ============================================================

async def _require_owned_turn(
    conversation: dict, turn_id: str, runner: TurnRunner
) -> dict[str, Any]:
    turn = await runner.store.get_turn(turn_id)
    if turn is None or turn["conversation_id"] != conversation["id"]:
        raise NotFoundError("轮次不存在")
    return turn


@router.get("/{conversation_id}/turns/{turn_id}/checkpoints")
async def list_turn_checkpoints(
    turn_id: str,
    conversation: dict = Depends(require_owned_conversation),
    runner: TurnRunner = Depends(get_turn_runner),
):
    turn = await _require_owned_turn(conversation, turn_id, runner)
    items = await runner.list_checkpoints(turn_id)
    return success({"turn_id": turn_id, "status": turn["status"], "checkpoints": items})


@router.post("/{conversation_id}/turns/{turn_id}/fork", status_code=201)
async def fork_turn(
    turn_id: str,
    body: ForkTurnRequest,
    conversation: dict = Depends(require_owned_conversation),
    runner: TurnRunner = Depends(get_turn_runner),
):
    await _require_owned_turn(conversation, turn_id, runner)
    outcome = await runner.fork_turn(turn_id, body.checkpoint_id, update=body.update)
    if outcome.skipped:
        raise InvalidParamsError("无法从该 checkpoint 分叉（不存在或无状态）")
    return success(
        {"turn_id": outcome.turn_id, "status": outcome.status},
        message="已从该轮次分叉",
    )
