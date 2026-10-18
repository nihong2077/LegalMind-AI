"""决策审计落库（T1.4，D15②）

把图内 host / scheduler 的每一次排序与程序性决策写入 ``host_decisions``，
供前端时间线展示与中断恢复排障（每次排序决策可查：点了谁、是否续轮、reason）。

落库失败**绝不阻断业务**（fail-open）：审计是旁路能力，异常只告警。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from ...core.pg_client import HostDecision, app_session_factory

logger = logging.getLogger(__name__)

MAX_RAW_OUTPUT = 4000


def _as_uuid(value: Any) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


async def record_host_decision(record: dict[str, Any]) -> None:
    """图节点注入用的 ``decision_recorder``（T1.4/T1.6 装配）。"""
    turn_id = _as_uuid(record.get("turn_id"))
    conversation_id = _as_uuid(record.get("conversation_id"))
    if turn_id is None or conversation_id is None:
        # 图单测/无 turn 上下文时静默跳过（审计不阻断）
        logger.debug("[collab] 审计跳过：缺少合法 turn_id/conversation_id")
        return

    parsed = dict(record.get("parsed_directive") or {})
    parsed.setdefault("kind", record.get("kind") or "host")
    raw_output = record.get("raw_output")
    if raw_output and len(raw_output) > MAX_RAW_OUTPUT:
        raw_output = raw_output[:MAX_RAW_OUTPUT] + "…（截断）"

    row = HostDecision(
        turn_id=turn_id,
        conversation_id=conversation_id,
        round=int(record.get("round") or 0),
        host_agent_id=str(record.get("host_agent_id") or "unknown")[:64],
        raw_output=raw_output,
        parsed_directive=parsed,
        accepted=bool(record.get("accepted", True)),
        rejection_reason=(str(record["rejection_reason"])[:64]
                          if record.get("rejection_reason") else None),
        request_id=(str(record["request_id"])[:64] if record.get("request_id") else None),
        latency_ms=record.get("latency_ms"),
    )
    try:
        async with app_session_factory() as session:
            session.add(row)
            await session.commit()
    except Exception as e:  # noqa: BLE001 —— 审计失败不阻断整轮
        logger.warning("[collab] host_decisions 审计落库失败（已忽略）：%s", e)
