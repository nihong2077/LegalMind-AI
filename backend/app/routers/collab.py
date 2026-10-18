"""
协同 SSE v2：短票据 + Redis Stream 回放 + Pub/Sub 桥接（T1.1）

订阅通道 ``GET /api/collab/conversations/{id}/events``：
1. 进群前先 ``POST .../events/ticket``（JWT 鉴权）换 60s 一次性短票据；
2. EventSource 以 query 携带票据（浏览器不支持给 EventSource 设头），
   重连时浏览器自动回传 ``Last-Event-ID``；
3. 服务端先按 Last-Event-ID 从 Stream 回放缺口，再订阅 Pub/Sub 实时推送；
   每条 SSE ``id`` = Redis Stream entry id，严格单调，订阅端按 id 去重——
   刷新 / 断网重连"消息不丢不重"（验收 O4）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import Depends, Header, Query, Request
from sse_starlette.sse import EventSourceResponse

from ..core.errors import UnauthorizedError
from ..core.redis_client import (
    consume_sse_ticket,
    conv_events_key,
    get_redis,
    issue_sse_ticket,
    read_conv_events_since,
    stream_id_gt,
)
from ..core.response import EnvelopeRouter, success
from ..core.security import get_current_user
from .conversations import require_owned_conversation

logger = logging.getLogger(__name__)

router = EnvelopeRouter(prefix="/api/collab/conversations", tags=["协同SSE"])

SSE_PING_SECONDS = 15
# 单次回放最多补发的条数（Stream 自身 MAXLEN 500，上限对齐）
REPLAY_BATCH = 500


@router.post("/{conversation_id}/events/ticket")
async def create_events_ticket(
    conversation: dict = Depends(require_owned_conversation),
    user: dict = Depends(get_current_user),
):
    """换一张 60s 有效的一次性 SSE 票据。"""
    token = await issue_sse_ticket(conversation["id"], user["sub"])
    return success({"events_token": token, "expires_in": 60})


async def _replay_gap(
    conversation_id: str, last_id: str
) -> tuple[list[dict[str, str]], str]:
    """读取 Stream 中严格晚于 last_id 的事件，转成 sse-starlette 事件字典。"""
    entries = await read_conv_events_since(conversation_id, last_id, count=REPLAY_BATCH)
    events: list[dict[str, str]] = []
    latest = last_id
    for entry_id, event_type, data_json in entries:
        events.append({"id": entry_id, "event": event_type, "data": data_json})
        latest = entry_id
    return events, latest


async def _conv_event_stream(
    request: Request,
    conversation_id: str,
    last_id: str,
):
    """SSE 生成器：先回放缺口，再 Pub/Sub 实时桥接；每 15s 发注释 ping 保活。"""
    r = get_redis()
    channel = conv_events_key(conversation_id)
    pubsub = r.pubsub()
    await pubsub.subscribe(channel)
    # 订阅成功后立刻再补一次缺口，覆盖"回放后、订阅前"的竞态窗口
    try:
        events, last_id = await _replay_gap(conversation_id, last_id)
        for event in events:
            yield event
        while not await request.is_disconnected():
            # 自愈：即使漏掉一条 Pub/Sub（发布瞬间订阅抖动），Stream 仍可补齐
            events, last_id = await _replay_gap(conversation_id, last_id)
            for event in events:
                yield event

            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=SSE_PING_SECONDS
            )
            if message is None:
                # 注释帧（": ping"）不触发前端 onmessage，仅保活/穿透代理
                yield {"comment": "ping"}
                continue
            try:
                payload = json.loads(message["data"])
            except (TypeError, ValueError):
                continue
            entry_id = payload.get("id", "")
            if entry_id and (not last_id or stream_id_gt(entry_id, last_id)):
                yield {
                    "id": entry_id,
                    "event": payload.get("event", "message"),
                    "data": json.dumps(payload.get("data", {}), ensure_ascii=False),
                }
                last_id = entry_id
    except asyncio.CancelledError:
        raise
    except Exception as e:  # 流式已开始，错误只能以 error 事件送达
        logger.warning("SSE 订阅异常 conv=%s：%s", conversation_id, e)
        yield {
            "event": "error",
            "data": json.dumps(
                {
                    "code": 50000,
                    "message": "实时连接异常，请重连",
                    "error": str(e),
                    "retryable": True,
                },
                ensure_ascii=False,
            ),
        }
    finally:
        try:
            await pubsub.aclose()
        except Exception:  # pragma: no cover
            pass


@router.get("/{conversation_id}/events")
async def subscribe_events(
    request: Request,
    events_token: str = Query(..., description="POST events/ticket 换取的一次性短票据"),
    last_id: Optional[str] = Query(default=None, description="上次收到的 Stream 事件 ID"),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
):
    # 票据一次性消费：过期 / 已用过 / 会话不匹配均 401（EventSource 会自动重连，
    # 前端需先重新换票；此处 401 不影响已建立连接）
    payload = await consume_sse_ticket(events_token, request.path_params["conversation_id"])
    if payload is None:
        raise UnauthorizedError("SSE 票据无效或已过期，请重新换取")

    conversation_id = payload["conversation_id"]
    resume_id = last_id or last_event_id or "0"
    return EventSourceResponse(
        _conv_event_stream(request, conversation_id, resume_id),
        ping=3_600,  # 关闭库内置 ping（自带的 15s 注释帧由生成器显式发出）
    )
