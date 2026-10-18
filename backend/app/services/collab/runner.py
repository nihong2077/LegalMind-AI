"""
协同轮次执行器 / 恢复引擎（T1.6）

对齐
[docs/collab-supervisor-checkpoint_spec.md](../../../../docs/collab-supervisor-checkpoint_spec.md) §3 与
计划 §3 T1.6 行：以 ``collab_turns`` 台账为权威，把「用户一次发言」驱动成一个可中断、可续跑、
可重试、可回退（fork）的轮次。Kafka 消费与进程内执行**共用本执行器**（双模式）。

核心职责：
1. **状态机**：running → interrupted（ask_user/接管暂停）→ running（resume）→ completed；异常
   累计 attempts，达上限 → failed + DLQ（§4.3）。
2. **租约心跳**：执行期间每 ``TURN_HEARTBEAT_INTERVAL`` 续写 ``worker_heartbeat`` 并续期 Redis 轮次锁，
   超 ``TURN_LEASE_SECONDS`` 无心跳的 running 轮次被视为僵死孤儿，可被其它副本认领续跑（§3.2）。
3. **checkpoint 续跑**：``astream`` 每个 super-step 原子提交；失败重试 / worker 重启从最近
   checkpoint 继续，**已完成的节点不重跑、已发言不重复**（幂等键见 agent_nodes，D15①）。
4. **中断与恢复**：``astream`` 返回 ``__interrupt__`` → status=interrupted 并推
   ``interaction_required`` 卡片；``Command(resume=...)`` 从断点精确续跑。
5. **审计与回退**：``aget_state_history`` 列 checkpoint 时间线；从指定 checkpoint fork 出新轮次（§3.3）。

设计取舍（已记录）：checkpoint ``thread_id`` 取 **turn_id**（非 conversation_id）——每轮状态
（``spoken``/``round``/``events`` 递增归并）天然按轮隔离，避免复用会话级 thread 时跨轮状态串味；
跨轮上下文由执行器**从 messages 表播种最近 N 条**进 ``state.messages``（DB 为权威，§3.1）。
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from ...core.config import settings
from ...core.events import event_bus
from ...core.metrics import COLLAB_TURN
from ...core.redis_client import (
    acquire_turn_lock,
    append_conv_event,
    get_turn_lock_holder,
    refresh_turn_lock,
    release_turn_lock,
)
from .agent_nodes import AgentNodeRunner
from .conversation_store import ConversationStore, pg_store
from .graph import get_collab_graph
from .registry import RegistryService, get_registry
from .state import DEFAULT_MAX_ROUNDS, initial_state
from .turn_store import (
    MODE_INPROCESS,
    TERMINAL_STATUSES,
    TURN_COMPLETED,
    TURN_FAILED,
    TURN_INTERRUPTED,
    TURN_RUNNING,
    TurnStore,
    pg_turn_store,
)

logger = logging.getLogger(__name__)

# SSE 控制事件（collab-ui-refactor_plan §5.4）
EVENT_STATUS = "status"
EVENT_INTERACTION = "interaction_required"
EVENT_DONE = "done"
EVENT_ERROR = "error"

Emitter = Callable[[str, str, dict[str, Any]], Awaitable[None]]


async def _default_emit(conversation_id: str, event_type: str, data: dict[str, Any]) -> None:
    await append_conv_event(conversation_id, event_type, data)


@dataclass
class TurnOutcome:
    """一次执行的结果快照（供 API/worker 决策与单测断言）。"""

    turn_id: str
    status: str
    skipped: bool = False
    interrupt: Optional[dict[str, Any]] = None
    error: Optional[dict[str, Any]] = None
    attempts: int = 0
    checkpoint_id: Optional[str] = None
    dlq: bool = False

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


def _interrupt_value(raw: Any) -> Any:
    """``Interrupt`` 对象 → 其 payload（兼容不同版本）。"""
    return getattr(raw, "value", raw)


class TurnRunner:
    """轮次执行器（注入图 / 台账 / 会话 store；Redis/事件/Kafka 均可注入以便单测）。"""

    def __init__(
        self,
        *,
        graph: Any = None,
        store: Optional[TurnStore] = None,
        conv_store: Optional[ConversationStore] = None,
        registry: Optional[RegistryService] = None,
        agent_runner: Optional[AgentNodeRunner] = None,
        emit: Optional[Emitter] = None,
        worker_id: str = "inline",
        max_attempts: Optional[int] = None,
        lease_seconds: Optional[int] = None,
        heartbeat_interval: Optional[float] = None,
        lock_acquire: Callable[[str, str], Awaitable[bool]] = acquire_turn_lock,
        lock_release: Callable[[str, str], Awaitable[bool]] = release_turn_lock,
        lock_holder: Callable[[str], Awaitable[Optional[str]]] = get_turn_lock_holder,
        lock_refresh: Callable[[str, str], Awaitable[bool]] = refresh_turn_lock,
        dlq_publish: Optional[Callable[[dict[str, Any], dict[str, Any]], Awaitable[None]]] = None,
        memory_dispatch: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
    ) -> None:
        self._graph = graph
        self._store = store
        self._conv_store = conv_store
        self._registry = registry
        self._agent_runner = agent_runner
        self._emit = emit or _default_emit
        self.worker_id = worker_id
        self.max_attempts = max_attempts or settings.TURN_MAX_ATTEMPTS
        self.lease_seconds = lease_seconds or settings.TURN_LEASE_SECONDS
        self.heartbeat_interval = (
            settings.TURN_HEARTBEAT_INTERVAL if heartbeat_interval is None else heartbeat_interval
        )
        self._lock_acquire = lock_acquire
        self._lock_release = lock_release
        self._lock_holder = lock_holder
        self._lock_refresh = lock_refresh
        self._dlq_publish = dlq_publish
        self._memory_dispatch = memory_dispatch

    # ---- 依赖 ---- 

    @property
    def store(self) -> TurnStore:
        return self._store or pg_turn_store

    @property
    def conv_store(self) -> ConversationStore:
        return self._conv_store or pg_store

    async def _get_graph(self) -> Any:
        if self._graph is not None:
            return self._graph
        self._graph = await get_collab_graph()
        return self._graph

    # ============================================================
    # 主入口
    # ============================================================

    async def execute_turn(
        self,
        turn_id: str,
        *,
        resume: Any = None,
        request_id: Optional[str] = None,
        recovered: bool = False,
    ) -> TurnOutcome:
        """执行/续跑一个轮次。``resume`` 非空走 ``Command(resume=...)``；否则按 checkpoint 状态续跑。"""
        turn = await self.store.get_turn(turn_id)
        if turn is None:
            logger.warning("[turn] 台账不存在 turn=%s", turn_id)
            return TurnOutcome(turn_id=turn_id, status=TURN_FAILED, skipped=True)

        # 终态幂等：Kafka 重投 / 重复触发直接 ack 跳过（§3.2）
        if turn["status"] in TERMINAL_STATUSES:
            logger.info("[turn] 终态幂等跳过 turn=%s status=%s", turn_id, turn["status"])
            return TurnOutcome(turn_id=turn_id, status=turn["status"], skipped=True)

        conversation_id = turn["conversation_id"]

        # 单一执行者双重保险：Redis 轮次锁（holder=turn_id）+ PG 状态
        if not await self._ensure_lock(conversation_id, turn_id):
            logger.info("[turn] 轮次锁被他人持有，放弃执行 turn=%s conv=%s", turn_id, conversation_id)
            return TurnOutcome(turn_id=turn_id, status=turn["status"], skipped=True)

        graph = await self._get_graph()
        config = self._config(turn_id)

        try:
            graph_input = await self._resolve_input(graph, turn, config, resume)
        except Exception as e:  # 前置加载失败也计入 attempts
            return await self._on_failure(turn, e, request_id=request_id)

        await self._start(turn, recovered=recovered)
        heartbeat = self._start_heartbeat(turn_id, conversation_id)
        try:
            interrupt_value = await self._drive(graph, graph_input, config)
            snapshot = await self._snapshot(graph, config)
            checkpoint_id = self._checkpoint_id(snapshot)
        except Exception as e:
            return await self._on_failure(turn, e, request_id=request_id)
        finally:
            await self._stop_heartbeat(heartbeat)

        if interrupt_value is not None:
            return await self._on_interrupt(turn, checkpoint_id, interrupt_value)

        return await self._on_success(turn, checkpoint_id)

    async def resume_turn(self, turn_id: str, resume_value: Any, *, request_id: Optional[str] = None) -> TurnOutcome:
        """用户输入后从 ``interrupt`` 断点精确续跑（ask_user 补证 / 接管发言 / 交还）。"""
        return await self.execute_turn(turn_id, resume=resume_value, request_id=request_id)

    async def retry_turn(self, turn_id: str, *, request_id: Optional[str] = None) -> TurnOutcome:
        """失败重试：从最近 checkpoint 续跑（input=None），失败的那个 super-step 重新执行。"""
        return await self.execute_turn(turn_id, request_id=request_id, recovered=True)

    async def recover_orphans(self, *, limit: int = 50) -> list[TurnOutcome]:
        """启动/巡检：认领租约过期的 running 孤儿并续跑（worker 崩溃接力）。"""
        claimed = await self.store.claim_orphan_turns(
            self.worker_id, lease_seconds=self.lease_seconds, limit=limit
        )
        outcomes: list[TurnOutcome] = []
        for turn in claimed:
            logger.info("[turn] 认领孤儿轮次 turn=%s", turn["turn_id"])
            outcomes.append(await self.execute_turn(turn["turn_id"], recovered=True))
        return outcomes

    # ============================================================
    # 输入解析 / 状态播种
    # ============================================================

    def _config(self, turn_id: str, checkpoint_id: Optional[str] = None) -> dict[str, Any]:
        cfg: dict[str, Any] = {"configurable": {"thread_id": turn_id}}
        if checkpoint_id:
            cfg["configurable"]["checkpoint_id"] = checkpoint_id
        return cfg

    async def _resolve_input(
        self, graph: Any, turn: dict[str, Any], config: dict, resume: Any
    ) -> Any:
        from langgraph.types import Command

        if resume is not None:
            return Command(resume=resume)
        if await self._has_checkpoint(graph, config):
            return None  # 从最近 checkpoint 续跑（失败节点重来）
        # 首次执行：从 messages 表播种历史 + 本轮状态
        return await self._initial_state(turn)

    async def _has_checkpoint(self, graph: Any, config: dict) -> bool:
        snapshot = await graph.aget_state(config)
        return bool(getattr(snapshot, "values", None)) or bool(getattr(snapshot, "next", None))

    async def _initial_state(self, turn: dict[str, Any]) -> dict[str, Any]:
        conversation_id = turn["conversation_id"]
        conv = await self.conv_store.get_conversation(conversation_id)
        if conv is None:
            raise RuntimeError(f"会话不存在：{conversation_id}")

        members = conv.get("members") or []
        roster = [m["agent_id"] for m in members]
        host = next((m["agent_id"] for m in members if m.get("role") == "host"), None)
        case_type = conv.get("case_type") or ""
        reg = self._registry or await get_registry()
        tpl = await reg.get_template(case_type) if case_type else None
        if not host and tpl:
            host = tpl.get("host_agent_id")
        max_rounds = int((tpl or {}).get("max_rounds") or DEFAULT_MAX_ROUNDS)

        state = initial_state(
            conversation_id=conversation_id,
            turn_id=turn["turn_id"],
            case_type=case_type,
            host_agent_id=host or "",
            roster=roster,
            my_role=conv.get("my_role"),
            conv_type=conv.get("type") or "group",
            target_agent_id=conv.get("target_agent_id"),
            max_rounds=max_rounds,
            user_message=None,
        )
        # 跨轮上下文：DB 权威，播种最近 N 条（含本轮触发消息，其即最后一条 user）
        rows, _ = await self.conv_store.list_messages_page(
            conversation_id, None, settings.TURN_HISTORY_LIMIT
        )
        state["messages"] = _to_messages(rows)
        return state

    # ============================================================
    # 驱动
    # ============================================================

    async def _drive(self, graph: Any, graph_input: Any, config: dict) -> Any:
        """跑图至 END 或 interrupt；返回 interrupt payload（None＝正常收敛）。"""
        interrupt_value: Any = None
        async for chunk in graph.astream(graph_input, config, stream_mode="updates"):
            if not isinstance(chunk, dict):
                continue
            raw = chunk.get("__interrupt__")
            if raw:
                first = raw[0] if isinstance(raw, (list, tuple)) else raw
                interrupt_value = _interrupt_value(first)
        return interrupt_value

    async def _snapshot(self, graph: Any, config: dict) -> Any:
        return await graph.aget_state(config)

    @staticmethod
    def _checkpoint_id(snapshot: Any) -> Optional[str]:
        cfg = getattr(snapshot, "config", None) or {}
        return (cfg.get("configurable") or {}).get("checkpoint_id")

    # ============================================================
    # 状态机落账 + 事件
    # ============================================================

    async def _start(self, turn: dict[str, Any], *, recovered: bool) -> None:
        turn_id = turn["turn_id"]
        conversation_id = turn["conversation_id"]
        if turn["status"] != TURN_RUNNING or recovered:
            await self.store.update_turn(turn_id, status=TURN_RUNNING, worker_id=self.worker_id)
        else:
            await self.store.heartbeat(turn_id, self.worker_id)
        await self._emit_safe(
            conversation_id,
            EVENT_STATUS,
            {
                "phase": "turn_running",
                "message": "会商进行中…",
                "turn_id": turn_id,
                "recovered": recovered,
            },
        )

    async def _on_success(self, turn: dict[str, Any], checkpoint_id: Optional[str]) -> TurnOutcome:
        turn_id = turn["turn_id"]
        conversation_id = turn["conversation_id"]
        await self.store.update_turn(
            turn_id, status=TURN_COMPLETED, checkpoint_id=checkpoint_id, completed=True
        )
        await self._release_lock(conversation_id, turn_id)
        await self._emit_safe(
            conversation_id, EVENT_DONE, {"turn_id": turn_id, "status": TURN_COMPLETED}
        )
        COLLAB_TURN.labels(state=TURN_COMPLETED).inc()
        logger.info("[turn] 完成 turn=%s", turn_id)
        await self._dispatch_memory(turn)
        return TurnOutcome(turn_id=turn_id, status=TURN_COMPLETED, checkpoint_id=checkpoint_id)

    async def _on_interrupt(
        self, turn: dict[str, Any], checkpoint_id: Optional[str], payload: Any
    ) -> TurnOutcome:
        turn_id = turn["turn_id"]
        conversation_id = turn["conversation_id"]
        data = payload if isinstance(payload, dict) else {"value": payload}
        data = {"turn_id": turn_id, **data}
        await self.store.update_turn(
            turn_id, status=TURN_INTERRUPTED, checkpoint_id=checkpoint_id
        )
        # 中断不占 worker：放锁，用户下一条消息据此路由为 resume（§3.1）
        await self._release_lock(conversation_id, turn_id)
        await self._emit_safe(conversation_id, EVENT_INTERACTION, data)
        COLLAB_TURN.labels(state=TURN_INTERRUPTED).inc()
        logger.info("[turn] 中断待恢复 turn=%s kind=%s", turn_id, data.get("type"))
        return TurnOutcome(
            turn_id=turn_id,
            status=TURN_INTERRUPTED,
            interrupt=data,
            checkpoint_id=checkpoint_id,
        )

    async def _on_failure(
        self, turn: dict[str, Any], exc: Exception, *, request_id: Optional[str]
    ) -> TurnOutcome:
        turn_id = turn["turn_id"]
        conversation_id = turn["conversation_id"]
        attempts = await self.store.increment_attempts(turn_id) or 1
        error = {
            "code": 50201,
            "message": str(exc),
            "type": type(exc).__name__,
            "request_id": request_id,
        }
        if attempts >= self.max_attempts:
            await self.store.update_turn(
                turn_id, status=TURN_FAILED, error=error, completed=True
            )
            await self._release_lock(conversation_id, turn_id)
            await self._publish_dlq(turn, error)
            await self._emit_safe(
                conversation_id,
                EVENT_ERROR,
                {
                    "code": 50201,
                    "message": "会商执行失败，已转死信，可点击重试",
                    "retryable": True,
                    "request_id": request_id,
                    "turn_id": turn_id,
                },
            )
            COLLAB_TURN.labels(state=TURN_FAILED).inc()
            logger.error("[turn] 失败进 DLQ turn=%s attempts=%d err=%s", turn_id, attempts, exc)
            return TurnOutcome(
                turn_id=turn_id, status=TURN_FAILED, error=error, attempts=attempts, dlq=True
            )

        # 未达上限：保留 running（可通过重投/孤儿扫描/用户重试续跑）
        await self.store.update_turn(turn_id, status=TURN_RUNNING, error=error)
        await self._release_lock(conversation_id, turn_id)
        await self._emit_safe(
            conversation_id,
            EVENT_ERROR,
            {
                "code": 50201,
                "message": "本轮会商遇到异常，可重试",
                "retryable": True,
                "request_id": request_id,
                "turn_id": turn_id,
            },
        )
        logger.warning("[turn] 执行异常待重试 turn=%s attempts=%d err=%s", turn_id, attempts, exc)
        return TurnOutcome(
            turn_id=turn_id, status=TURN_RUNNING, error=error, attempts=attempts
        )

    async def _dispatch_memory(self, turn: dict[str, Any]) -> None:
        """轮次成功收尾后派发记忆事件（T2.2）。fail-open：异常仅告警，绝不改轮次终态。"""
        if self._memory_dispatch is None:
            return
        try:
            await self._memory_dispatch(turn)
        except Exception as e:
            logger.warning("[turn] 记忆派发失败（忽略）：%s", e)

    async def _publish_dlq(self, turn: dict[str, Any], error: dict[str, Any]) -> None:
        payload = {
            "turn_id": turn["turn_id"],
            "conversation_id": turn["conversation_id"],
            "user_id": turn.get("user_id"),
            "attempts": self.max_attempts,
            "error": error,
        }
        try:
            if self._dlq_publish is not None:
                await self._dlq_publish(payload, error)
            else:
                await event_bus.publish(
                    settings.KAFKA_TOPIC_TURNS_DLQ,
                    payload,
                    key=turn["conversation_id"],
                )
        except Exception as e:  # DLQ 失败不阻断主流程（fail-open）
            logger.warning("[turn] DLQ 发布失败（忽略）：%s", e)

    # ============================================================
    # 锁 / 心跳
    # ============================================================

    async def _ensure_lock(self, conversation_id: str, turn_id: str) -> bool:
        try:
            holder = await self._lock_holder(conversation_id)
            if holder == turn_id:
                return True
            if holder is not None:
                return False
            return bool(await self._lock_acquire(conversation_id, turn_id))
        except Exception as e:  # Redis 降级：不阻塞（单进程本地开发）
            logger.warning("[turn] 轮次锁不可用，降级放行：%s", e)
            return True

    async def _release_lock(self, conversation_id: str, turn_id: str) -> None:
        try:
            await self._lock_release(conversation_id, turn_id)
        except Exception as e:
            logger.warning("[turn] 放锁失败（忽略，靠 TTL 兜底）：%s", e)

    def _start_heartbeat(self, turn_id: str, conversation_id: str) -> Optional[asyncio.Task]:
        interval = self.heartbeat_interval
        if not interval or interval <= 0:
            return None

        async def _beat() -> None:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self.store.heartbeat(turn_id, self.worker_id)
                    await self._lock_refresh(conversation_id, turn_id)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("[turn] 心跳失败（下跳重试）turn=%s：%s", turn_id, e)

        return asyncio.ensure_future(_beat())

    @staticmethod
    async def _stop_heartbeat(task: Optional[asyncio.Task]) -> None:
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    async def _emit_safe(self, conversation_id: str, event_type: str, data: dict[str, Any]) -> None:
        try:
            await self._emit(conversation_id, event_type, data)
        except Exception as e:  # 事件推送失败不影响权威落账
            logger.warning("[turn] 事件推送失败（忽略）：%s", e)

    # ============================================================
    # checkpoint 时间线 / fork（§3.3）
    # ============================================================

    async def list_checkpoints(self, turn_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """列出该轮次的 checkpoint 链（时间线：轮次/主持人指令/时间/是否最新）。"""
        graph = await self._get_graph()
        config = self._config(turn_id)
        items: list[dict[str, Any]] = []
        latest_id: Optional[str] = None
        try:
            snapshot = await graph.aget_state(config)
            latest_id = self._checkpoint_id(snapshot)
            idx = 0
            async for snap in graph.aget_state_history(config):
                if len(items) >= limit:
                    break
                values = getattr(snap, "values", None) or {}
                directive = values.get("host_directive") or {}
                cid = self._checkpoint_id(snap)
                items.append(
                    {
                        "checkpoint_id": cid,
                        "step": idx,
                        "round": int(values.get("round", 0)),
                        "directive": directive.get("directive"),
                        "reason": directive.get("reason"),
                        "force_stop_reason": values.get("force_stop_reason"),
                        "spoken": list(values.get("spoken") or []),
                        "next": list(getattr(snap, "next", ()) or ()),
                        "created_at": _iso(getattr(snap, "created_at", None)),
                        "is_latest": cid == latest_id,
                    }
                )
                idx += 1
        except Exception as e:
            logger.warning("[turn] 列 checkpoint 失败 turn=%s：%s", turn_id, e)
        return items

    async def fork_turn(
        self,
        turn_id: str,
        checkpoint_id: str,
        *,
        update: Optional[dict[str, Any]] = None,
        forked_turn_id: Optional[str] = None,
    ) -> TurnOutcome:
        """从指定 checkpoint fork 出新轮次（旧分支保留）。

        以该 checkpoint 的 state 作为新轮次初值（可叠加 ``update`` 修正事实），在新 thread
        重跑：新轮次消息用新 ``turn_id`` 幂等键，不与旧分支冲突。
        """
        src = await self.store.get_turn(turn_id)
        if src is None:
            return TurnOutcome(turn_id=turn_id, status=TURN_FAILED, skipped=True)

        graph = await self._get_graph()
        src_config = self._config(turn_id, checkpoint_id)
        snapshot = await graph.aget_state(src_config)
        values = dict(getattr(snapshot, "values", None) or {})
        if not values:
            logger.warning("[turn] fork 源 checkpoint 无状态 turn=%s ckpt=%s", turn_id, checkpoint_id)
            return TurnOutcome(turn_id=turn_id, status=TURN_FAILED, skipped=True)

        new_turn = await self.store.create_turn(
            src["conversation_id"],
            src.get("user_id") or "",
            mode=src.get("mode") or MODE_INPROCESS,
            forked_from_turn_id=turn_id,
        )
        new_turn_id = forked_turn_id or new_turn["turn_id"]

        # 修正事实 + 隔离审计（fork 后事件重新累积，不继承父链审计）
        values.setdefault("budget", {})
        values["conversation_id"] = src["conversation_id"]
        values["turn_id"] = new_turn_id
        values["events"] = []
        values["force_stop_reason"] = None
        values["forked_from"] = {"turn_id": turn_id, "checkpoint_id": checkpoint_id}
        if update:
            values.update(update)

        if not await self._ensure_lock(src["conversation_id"], new_turn_id):
            return TurnOutcome(turn_id=new_turn_id, status=src.get("status") or TURN_RUNNING, skipped=True)

        config = self._config(new_turn_id)
        await self._start(new_turn, recovered=False)
        heartbeat = self._start_heartbeat(new_turn_id, src["conversation_id"])
        try:
            interrupt_value = await self._drive(graph, values, config)
            snapshot = await self._snapshot(graph, config)
            checkpoint_id_new = self._checkpoint_id(snapshot)
        except Exception as e:
            return await self._on_failure(new_turn, e, request_id=None)
        finally:
            await self._stop_heartbeat(heartbeat)

        if interrupt_value is not None:
            return await self._on_interrupt(new_turn, checkpoint_id_new, interrupt_value)
        return await self._on_success(new_turn, checkpoint_id_new)


# ============================================================
# transcript 序列化辅助
# ============================================================

def _iso(value: Any) -> Optional[str]:
    try:
        return value.isoformat() if value is not None else None
    except AttributeError:
        return None


def _to_messages(rows: list[dict[str, Any]]) -> list[Any]:
    """PG 消息行 → LangGraph transcript（AnyMessage + additional_kwargs 角色标记）。"""
    from langchain_core.messages import AIMessage, HumanMessage

    out: list[Any] = []
    for m in rows:
        content = str(m.get("content") or "")
        sender_type = m.get("sender_type") or "agent"
        sender_id = m.get("sender_id") or sender_type
        name = m.get("sender_name") or sender_id
        kwargs: dict[str, Any] = {
            "sender_type": sender_type,
            "sender_id": sender_id,
            "sender_name": name,
        }
        if sender_type == "agent":
            kwargs["agent_id"] = sender_id
        elif sender_type == "tool":
            kwargs["tool_id"] = sender_id
        if sender_type == "user":
            out.append(HumanMessage(content=content, name="user", additional_kwargs=kwargs))
        else:
            out.append(AIMessage(content=content, name=name, additional_kwargs=kwargs))
    return out


def _inline_worker_id() -> str:
    """API 进程内执行器的 worker_id（唯一，避免多副本各自「孤儿认领」互相抢）。"""
    return f"inline-{socket.gethostname()}-{os.getpid()}"


def make_turn_runner(
    *,
    graph: Any = None,
    store: Optional[TurnStore] = None,
    conv_store: Optional[ConversationStore] = None,
    registry: Optional[RegistryService] = None,
    agent_runner: Optional[AgentNodeRunner] = None,
    emit: Optional[Emitter] = None,
    worker_id: str = "inline",
    heartbeat_interval: Optional[float] = None,
    dlq_publish: Optional[Callable[[dict[str, Any], dict[str, Any]], Awaitable[None]]] = None,
    memory_dispatch: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
) -> TurnRunner:
    return TurnRunner(
        graph=graph,
        store=store,
        conv_store=conv_store,
        registry=registry,
        agent_runner=agent_runner,
        emit=emit,
        worker_id=worker_id,
        heartbeat_interval=heartbeat_interval,
        dlq_publish=dlq_publish,
        memory_dispatch=memory_dispatch,
    )


# ============================================================
# API 进程内单例（T1.6 M3）
# ============================================================

_runner_singleton: Optional[TurnRunner] = None


def get_turn_runner() -> TurnRunner:
    """API 路由依赖：进程内单例执行器（Kafka 关时的进程内模式；worker 另建实例）。"""
    global _runner_singleton
    if _runner_singleton is None:
        _runner_singleton = TurnRunner(
            worker_id=_inline_worker_id(),
            memory_dispatch=_default_memory_dispatch(),
        )
    return _runner_singleton


def _default_memory_dispatch() -> Callable[[dict[str, Any]], Awaitable[None]]:
    """惰性取 T2.2 记忆派发器（避免 core→services 的顶层循环导入）。"""
    from ..memory.pipeline import dispatch_memory_event

    return dispatch_memory_event


def reset_turn_runner() -> None:
    """显式失效缓存（测试注入 / 配置变更后调用）。"""
    global _runner_singleton
    _runner_singleton = None
