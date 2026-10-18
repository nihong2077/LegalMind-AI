"""T1.6 轮次执行器 / 恢复引擎测试（假台账/假会话 store/假锁 + InMemorySaver 真图，不依赖 DB/LLM/Redis）。

覆盖计划 §3 T1.6 行验收（F4/F11/F12 的引擎侧）：
- **状态机**：running → completed；失败 attempts 累计，达上限 → failed + DLQ；
- **中断恢复**：ask_user interrupt → interrupted（放锁不占 worker）→ resume 从断点续跑 → completed；
- **租约孤儿**：心跳过期的 running 被认领并续跑；
- **锁冲突**：他人持有轮次锁 → 幂等跳过；
- **checkpoint 时间线 / fork**：列链与从指定 checkpoint 分叉出新轮次。
"""
import sys
import time
import uuid as uuidlib

import pytest
from langgraph.checkpoint.memory import InMemorySaver

sys.path.insert(0, ".")

from app.services.collab import runner as runner_mod
from app.services.collab.graph import build_collab_graph
from app.services.collab.runner import (
    EVENT_DONE,
    EVENT_ERROR,
    EVENT_INTERACTION,
    TurnRunner,
)
from app.services.collab.turn_store import (
    TURN_COMPLETED,
    TURN_FAILED,
    TURN_INTERRUPTED,
    TURN_RUNNING,
)

from tests.test_collab_graph import make_registry


# ============================================================
# 假件
# ============================================================

class FakeTurnStore:
    """内存台账：语义对齐 PgTurnStore（状态机/租约/认领/attempts）。"""

    def __init__(self):
        self.turns: dict[str, dict] = {}

    async def create_turn(self, conversation_id, user_id, *, mode="inprocess",
                          trigger_message_id=None, forked_from_turn_id=None):
        turn_id = str(uuidlib.uuid4())
        self.turns[turn_id] = {
            "turn_id": turn_id, "conversation_id": conversation_id, "user_id": user_id,
            "status": TURN_RUNNING, "mode": mode, "worker_id": None,
            "worker_heartbeat": time.time(), "attempts": 0,
            "last_checkpoint_id": None, "error": None,
            "forked_from_turn_id": forked_from_turn_id, "completed_at": None,
        }
        return dict(self.turns[turn_id])

    async def get_turn(self, turn_id):
        t = self.turns.get(turn_id)
        return dict(t) if t else None

    async def get_open_turn(self, conversation_id):
        for t in reversed(list(self.turns.values())):
            if t["conversation_id"] == conversation_id and t["status"] in (TURN_RUNNING, TURN_INTERRUPTED):
                return dict(t)
        return None

    async def list_turns(self, conversation_id, limit=20):
        return [dict(t) for t in self.turns.values() if t["conversation_id"] == conversation_id]

    async def update_turn(self, turn_id, *, status=None, error=None, checkpoint_id=None,
                          worker_id=None, completed=False):
        t = self.turns.get(turn_id)
        if t is None:
            return None
        if status is not None:
            t["status"] = status
        if error is not None:
            t["error"] = error
        if checkpoint_id is not None:
            t["last_checkpoint_id"] = checkpoint_id
        if worker_id is not None:
            t["worker_id"] = worker_id
            t["worker_heartbeat"] = time.time()
        if completed:
            t["completed_at"] = time.time()
        return dict(t)

    async def heartbeat(self, turn_id, worker_id):
        t = self.turns.get(turn_id)
        if t is None:
            return False
        t["worker_id"] = worker_id
        t["worker_heartbeat"] = time.time()
        return True

    async def increment_attempts(self, turn_id):
        t = self.turns.get(turn_id)
        if t is None:
            return None
        t["attempts"] = int(t.get("attempts", 0)) + 1
        return t["attempts"]

    async def claim_orphan_turns(self, worker_id, *, lease_seconds, limit=50):
        now = time.time()
        claimed = []
        for t in self.turns.values():
            if t["status"] != TURN_RUNNING:
                continue
            hb = t.get("worker_heartbeat") or 0
            if now - hb > lease_seconds:
                t["worker_id"] = worker_id
                t["worker_heartbeat"] = now
                claimed.append(dict(t))
            if len(claimed) >= limit:
                break
        return claimed


class FakeConvStore:
    """内存会话 store：提供 get_conversation / list_messages_page。"""

    def __init__(self, *, case_type="court", members=None, my_role=None,
                 conv_type="group", target_agent_id=None, messages=None):
        self.conv = {
            "id": "conv-1", "user_id": "u1", "type": conv_type, "case_type": case_type,
            "title": "模拟庭审", "status": "active", "my_role": my_role,
            "target_agent_id": target_agent_id,
            "members": members if members is not None else [
                {"agent_id": "judge", "role": "host"},
                {"agent_id": "plaintiff_lawyer", "role": "member"},
                {"agent_id": "defense_lawyer", "role": "member"},
                {"agent_id": "clerk", "role": "member"},
            ],
        }
        self.msgs = messages if messages is not None else [
            {"id": "m1", "sender_type": "user", "sender_id": "u1", "sender_name": "u1",
             "content": "请开始庭审", "msg_type": "text", "round": 0, "metadata": {}},
        ]

    async def get_conversation(self, conversation_id):
        return dict(self.conv) if conversation_id == self.conv["id"] else None

    async def list_messages_page(self, conversation_id, before_id, limit):
        return [dict(m) for m in self.msgs], None


def make_locks() -> dict:
    state = {"holder": None, "acquire_calls": 0, "release_calls": 0}

    async def acquire(conversation_id, holder):
        state["acquire_calls"] += 1
        if state["holder"] is None:
            state["holder"] = holder
            return True
        return False

    async def release(conversation_id, holder):
        state["release_calls"] += 1
        if state["holder"] == holder:
            state["holder"] = None
        return True

    async def holder_fn(conversation_id):
        return state["holder"]

    async def refresh(conversation_id, holder):
        return state["holder"] == holder

    # 注意：``holder`` 键存的是**当前持锁值**，锁函数另存其它键，避免同名覆盖
    state["holder_fn"] = holder_fn
    state["refresh"] = refresh
    state["acquire"] = acquire
    state["release"] = release
    return state


def make_emit() -> tuple[list[tuple[str, dict]], runner_mod.Emitter]:
    events: list[tuple[str, dict]] = []

    async def emit(conversation_id, event_type, data):
        events.append((event_type, data))

    return events, emit


def fixed_agent_runner(text="（模拟发言）"):
    async def _run(agent, state):
        return f"{text}:{agent['agent_id']}"
    return _run


def boom_agent_runner():
    async def _run(agent, state):
        raise RuntimeError("LLM 端点 500")
    return _run


async def _build_graph(reg, *, host_advisor=None, scheduler=None, agent_runner=None):
    return await build_collab_graph(
        registry=reg, host_advisor=host_advisor, scheduler=scheduler,
        agent_runner=agent_runner or fixed_agent_runner(),
        checkpointer=InMemorySaver(),
    )


def make_runner(*, graph, store, locks, emit, conv_store=None, **kwargs):
    return TurnRunner(
        graph=graph, store=store, conv_store=conv_store or FakeConvStore(),
        registry=make_registry(), emit=emit, worker_id="w1",
        heartbeat_interval=0,  # 单测关闭心跳后台任务，避免时序噪声
        lock_acquire=locks["acquire"], lock_release=locks["release"],
        lock_holder=locks["holder_fn"], lock_refresh=locks["refresh"],
        **kwargs,
    )


async def _new_turn(store, mode="inprocess"):
    return await store.create_turn("conv-1", "u1", mode=mode)


def _statuses(events, event_type):
    return [d for e, d in events if e == event_type]


# ============================================================
# 状态机：正常完成 / 终态跳过 / 锁冲突
# ============================================================

@pytest.mark.asyncio
async def test_execute_turn_completes():
    store, locks = FakeTurnStore(), make_locks()
    events, emit = make_emit()
    turn = await _new_turn(store)
    graph = await _build_graph(make_registry())
    r = make_runner(graph=graph, store=store, locks=locks, emit=emit)

    out = await r.execute_turn(turn["turn_id"])

    assert out.status == TURN_COMPLETED
    assert not out.skipped
    assert store.turns[turn["turn_id"]]["status"] == TURN_COMPLETED
    assert store.turns[turn["turn_id"]]["completed_at"] is not None
    assert _statuses(events, EVENT_DONE)[0]["status"] == TURN_COMPLETED
    assert _statuses(events, "status")[0]["phase"] == "turn_running"
    assert locks["holder"] is None  # 完成后放锁


@pytest.mark.asyncio
async def test_terminal_turn_is_skipped():
    store, locks = FakeTurnStore(), make_locks()
    events, emit = make_emit()
    turn = await _new_turn(store)
    await store.update_turn(turn["turn_id"], status=TURN_COMPLETED)
    graph = await _build_graph(make_registry())
    r = make_runner(graph=graph, store=store, locks=locks, emit=emit)

    out = await r.execute_turn(turn["turn_id"])

    assert out.skipped and out.status == TURN_COMPLETED
    assert locks["acquire_calls"] == 0  # 未尝试抢锁
    assert events == []  # 不推任何事件


@pytest.mark.asyncio
async def test_lock_conflict_skips():
    store, locks = FakeTurnStore(), make_locks()
    events, emit = make_emit()
    turn = await _new_turn(store)
    locks["holder"] = "another-turn"  # 他人持锁
    graph = await _build_graph(make_registry())
    r = make_runner(graph=graph, store=store, locks=locks, emit=emit)

    out = await r.execute_turn(turn["turn_id"])

    assert out.skipped
    assert store.turns[turn["turn_id"]]["status"] == TURN_RUNNING  # 未被推进
    assert events == []


# ============================================================
# 中断恢复：ask_user
# ============================================================

def _ask_user_advisor():
    async def advisor(state):
        resumed = any(
            getattr(m, "additional_kwargs", {}).get("resume_after_interrupt")
            for m in state.get("messages", [])
        )
        if resumed:
            return {"directive": "conclude", "reason": "已补证"}
        return {"directive": "ask_user", "ask_user": "请补充证据材料"}
    return advisor


@pytest.mark.asyncio
async def test_interrupt_then_resume_completes():
    store, locks = FakeTurnStore(), make_locks()
    events, emit = make_emit()
    turn = await _new_turn(store)
    graph = await _build_graph(make_registry(), host_advisor=_ask_user_advisor())
    r = make_runner(graph=graph, store=store, locks=locks, emit=emit)

    out = await r.execute_turn(turn["turn_id"])
    assert out.status == TURN_INTERRUPTED
    assert store.turns[turn["turn_id"]]["status"] == TURN_INTERRUPTED
    assert locks["holder"] is None  # 中断不占 worker：放锁
    card = _statuses(events, EVENT_INTERACTION)[0]
    assert card["type"] == "interaction_required"
    assert card["question"] == "请补充证据材料"
    assert card["turn_id"] == turn["turn_id"]

    resumed = await r.resume_turn(turn["turn_id"], "补充：合同复印件一份")
    assert resumed.status == TURN_COMPLETED
    assert store.turns[turn["turn_id"]]["status"] == TURN_COMPLETED


# ============================================================
# 失败：attempts 累计 → DLQ
# ============================================================

@pytest.mark.asyncio
async def test_failure_retries_then_dlq():
    store, locks = FakeTurnStore(), make_locks()
    events, emit = make_emit()
    turn = await _new_turn(store)
    graph = await _build_graph(make_registry(), agent_runner=boom_agent_runner())
    dlq: list[dict] = []

    async def dlq_publish(payload, error):
        dlq.append(payload)

    r = make_runner(graph=graph, store=store, locks=locks, emit=emit,
                    max_attempts=2, dlq_publish=dlq_publish)

    first = await r.execute_turn(turn["turn_id"])
    assert first.status == TURN_RUNNING  # 未达上限：保留可重试
    assert first.attempts == 1
    assert store.turns[turn["turn_id"]]["attempts"] == 1
    err = _statuses(events, EVENT_ERROR)[0]
    assert err["retryable"] is True and err["code"] == 50201
    assert dlq == []

    second = await r.retry_turn(turn["turn_id"])
    assert second.status == TURN_FAILED
    assert second.attempts == 2 and second.dlq
    assert store.turns[turn["turn_id"]]["status"] == TURN_FAILED
    assert len(dlq) == 1 and dlq[0]["turn_id"] == turn["turn_id"]
    assert locks["holder"] is None


# ============================================================
# 租约孤儿：认领 + 续跑
# ============================================================

@pytest.mark.asyncio
async def test_recover_orphan_turns():
    store, locks = FakeTurnStore(), make_locks()
    events, emit = make_emit()
    turn = await _new_turn(store)
    store.turns[turn["turn_id"]]["worker_heartbeat"] = time.time() - 999  # 心跳过期（僵死）
    graph = await _build_graph(make_registry())
    r = make_runner(graph=graph, store=store, locks=locks, emit=emit, lease_seconds=90)

    outcomes = await r.recover_orphans()

    assert len(outcomes) == 1
    assert outcomes[0].turn_id == turn["turn_id"]
    assert store.turns[turn["turn_id"]]["status"] == TURN_COMPLETED
    assert store.turns[turn["turn_id"]]["worker_id"] == "w1"  # 被本副本认领


# ============================================================
# checkpoint 时间线 / fork
# ============================================================

@pytest.mark.asyncio
async def test_list_checkpoints_timeline():
    store, locks = FakeTurnStore(), make_locks()
    events, emit = make_emit()
    turn = await _new_turn(store)
    graph = await _build_graph(make_registry())
    r = make_runner(graph=graph, store=store, locks=locks, emit=emit)
    await r.execute_turn(turn["turn_id"])

    items = await r.list_checkpoints(turn["turn_id"])
    assert items, "应至少有一个 checkpoint"
    assert sum(1 for it in items if it["is_latest"]) == 1
    assert all("checkpoint_id" in it and "round" in it for it in items)


@pytest.mark.asyncio
async def test_fork_turn_from_checkpoint():
    store, locks = FakeTurnStore(), make_locks()
    events, emit = make_emit()
    turn = await _new_turn(store)
    graph = await _build_graph(make_registry())
    r = make_runner(graph=graph, store=store, locks=locks, emit=emit)
    await r.execute_turn(turn["turn_id"])

    items = await r.list_checkpoints(turn["turn_id"])
    # 取一个较早的 checkpoint（round=0，未发言）作 fork 源
    source = next((it for it in items if it["round"] == 0), items[-1])

    out = await r.fork_turn(turn["turn_id"], source["checkpoint_id"])

    assert out.status == TURN_COMPLETED
    new_turn = await store.get_turn(out.turn_id)
    assert new_turn is not None
    assert new_turn["turn_id"] != turn["turn_id"]
    assert new_turn["forked_from_turn_id"] == turn["turn_id"]
    assert new_turn["status"] == TURN_COMPLETED


# ============================================================
# M2 · B2 接管式扮演（轮到 my_role 暂停 → resume 以该角色身份落库 / 交还给 AI）
# ============================================================

async def _final_messages(graph, turn_id):
    snap = await graph.aget_state({"configurable": {"thread_id": turn_id}})
    return (snap.values or {}).get("messages", [])


def _by_actor(messages, agent_id):
    return [
        m for m in messages
        if (getattr(m, "additional_kwargs", {}) or {}).get("actor_agent_id") == agent_id
    ]


def _by_agent(messages, agent_id):
    return [
        m for m in messages
        if (getattr(m, "additional_kwargs", {}) or {}).get("agent_id") == agent_id
    ]


@pytest.mark.asyncio
async def test_takeover_interrupt_then_resume_as_role():
    """轮到 my_role（原告律师）时暂停；用户 resume 的发言以 sender_type=user + actor_agent_id 落 transcript。"""
    store, locks = FakeTurnStore(), make_locks()
    events, emit = make_emit()
    turn = await _new_turn(store)
    conv = FakeConvStore(my_role="plaintiff_lawyer")
    graph = await _build_graph(make_registry())
    r = make_runner(graph=graph, store=store, locks=locks, emit=emit, conv_store=conv)

    out = await r.execute_turn(turn["turn_id"])
    assert out.status == TURN_INTERRUPTED
    card = _statuses(events, EVENT_INTERACTION)[0]
    assert card["type"] == "takeover" and card["agent_id"] == "plaintiff_lawyer"
    assert card["turn_id"] == turn["turn_id"]

    resumed = await r.resume_turn(turn["turn_id"], "我主张该公司应承担违约责任")
    assert resumed.status == TURN_COMPLETED

    msgs = await _final_messages(graph, turn["turn_id"])
    takeover = _by_actor(msgs, "plaintiff_lawyer")
    assert takeover, "接管发言应落 transcript"
    assert takeover[0].additional_kwargs["sender_type"] == "user"
    assert takeover[0].content == "我主张该公司应承担违约责任"


@pytest.mark.asyncio
async def test_takeover_hand_back_generates_ai_message():
    """「交还给 AI」：撤销接管标志后自动续跑，由 AI 代该角色生成（sender_type=agent）。"""
    store, locks = FakeTurnStore(), make_locks()
    events, emit = make_emit()
    turn = await _new_turn(store)
    conv = FakeConvStore(my_role="plaintiff_lawyer")
    graph = await _build_graph(make_registry())
    r = make_runner(graph=graph, store=store, locks=locks, emit=emit, conv_store=conv)

    out = await r.execute_turn(turn["turn_id"])
    assert out.status == TURN_INTERRUPTED

    resumed = await r.resume_turn(turn["turn_id"], {"action": "hand_back"})
    assert resumed.status == TURN_COMPLETED

    msgs = await _final_messages(graph, turn["turn_id"])
    assert not _by_actor(msgs, "plaintiff_lawyer"), "交还 AI 后不应有用户接管气泡"
    ai = _by_agent(msgs, "plaintiff_lawyer")
    assert ai and ai[0].additional_kwargs["sender_type"] == "agent"
    snap = await graph.aget_state({"configurable": {"thread_id": turn["turn_id"]}})
    assert not snap.values.get("my_role"), "交还后本 turn 内 my_role 应被置空"


# ============================================================
# T2.2：轮次成功收尾派发记忆事件
# ============================================================

@pytest.mark.asyncio
async def test_memory_dispatch_called_on_turn_success():
    store, locks = FakeTurnStore(), make_locks()
    events, emit = make_emit()
    dispatched: list[dict] = []

    async def memory_dispatch(turn):
        dispatched.append(dict(turn))

    r = make_runner(
        graph=None, store=store, locks=locks, emit=emit,
        memory_dispatch=memory_dispatch,
    )
    turn = await _new_turn(store)
    out = await r._on_success(await store.get_turn(turn["turn_id"]), "ckpt-1")

    assert out.status == TURN_COMPLETED
    assert [d["turn_id"] for d in dispatched] == [turn["turn_id"]]


@pytest.mark.asyncio
async def test_memory_dispatch_failure_is_fail_open():
    """派发器抛异常不得改变轮次终态（fail-open）。"""
    store, locks = FakeTurnStore(), make_locks()
    events, emit = make_emit()

    async def boom(turn):
        raise RuntimeError("memory backend down")

    r = make_runner(graph=None, store=store, locks=locks, emit=emit, memory_dispatch=boom)
    turn = await _new_turn(store)
    out = await r._on_success(await store.get_turn(turn["turn_id"]), None)

    assert out.status == TURN_COMPLETED
    assert store.turns[turn["turn_id"]]["status"] == TURN_COMPLETED
    assert store.turns[turn["turn_id"]]["completed_at"] is not None
