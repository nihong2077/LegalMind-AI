"""T1.6 M4 worker 消费器 / 孤儿扫描测试（假消费者/假 runner + 真图真执行器，不依赖 Kafka/DB/Redis）。

覆盖计划 §3 T1.6 行的 worker 侧（F4/F11/F12）：
- 消费循环：拉到 ``collab-turns`` 消息 → 逐条驱动轮次 → 手动提交；
- 毒消息隔离：单条异常不拖垮消费循环，其余仍处理；
- broker 不可达：退化为仅心跳（standby_state=degraded），不抛异常；
- 孤儿扫描：周期认领僵死轮次续跑；扫描异常不杀进程；
- **kill-worker 故障演练**：worker A 跑到 checkpoint 后「僵死」，worker B 通过孤儿扫描认领并
  从断点续跑至 completed，且**已发言不重复**（幂等）。
"""
import asyncio
import sys
import time

import pytest

sys.path.insert(0, ".")

from app.services.collab.runner import TurnOutcome
from app.services.collab.state import initial_state
from app.services.collab.turn_store import TURN_COMPLETED, TURN_RUNNING
from app.worker.consumers.collab import (
    handle_turn_message,
    consume_turns,
    orphan_scan_loop,
)

from tests.test_collab_runner import (
    FakeConvStore,
    FakeTurnStore,
    _build_graph,
    _final_messages,
    make_emit,
    make_locks,
    make_runner,
)
from tests.test_collab_graph import make_registry

pytestmark = pytest.mark.asyncio


# ============================================================
# 假件
# ============================================================

class FakeMsg:
    def __init__(self, value):
        self.value = value


class FakeRunner:
    """记录 execute_turn 调用的假执行器（可注入单条毒消息 / 孤儿返回）。"""

    def __init__(self, *, raise_for=None, orphans=None, raise_on_scan=False):
        self.calls: list[str] = []
        self.orphan_calls = 0
        self._raise_for = set(raise_for or [])
        self._orphans = orphans or []
        self._raise_on_scan = raise_on_scan

    async def execute_turn(self, turn_id, **_):
        self.calls.append(turn_id)
        if turn_id in self._raise_for:
            raise RuntimeError(f"boom {turn_id}")
        return TurnOutcome(turn_id=turn_id, status=TURN_COMPLETED)

    async def recover_orphans(self, *, limit=50):
        self.orphan_calls += 1
        if self._raise_on_scan:
            raise RuntimeError("db down")
        return list(self._orphans)


class FakeConsumer:
    """按批次吐出消息；批次耗尽即置 stop 事件（避免空转）。"""

    def __init__(self, batches, *, start_error=None, stop_event=None):
        self._batches = batches
        self._i = 0
        self.commits = 0
        self.started = False
        self.stopped = False
        self._start_error = start_error
        self._stop_event = stop_event

    async def start(self):
        if self._start_error:
            raise self._start_error
        self.started = True

    async def stop(self):
        self.stopped = True

    async def getmany(self, timeout_ms=1000, max_records=10):
        if self._i >= len(self._batches):
            if self._stop_event is not None:
                self._stop_event.set()
            return {}
        batch = self._batches[self._i]
        self._i += 1
        return {"collab-turns-0": [FakeMsg(v) for v in batch]}

    async def commit(self):
        self.commits += 1


# ============================================================
# 消息处理
# ============================================================

async def test_handle_turn_message_drives_turn():
    runner = FakeRunner()
    out = await handle_turn_message(runner, {"turn_id": "t1", "conversation_id": "c1"})
    assert runner.calls == ["t1"]
    assert out.status == TURN_COMPLETED


async def test_handle_turn_message_missing_id_is_dropped():
    runner = FakeRunner()
    assert await handle_turn_message(runner, {}) is None
    assert await handle_turn_message(runner, None) is None
    assert runner.calls == []


# ============================================================
# 消费循环
# ============================================================

async def test_consume_turns_dispatches_and_commits():
    stop = asyncio.Event()
    consumer = FakeConsumer([[{"turn_id": "t1"}, {"turn_id": "t2"}]], stop_event=stop)
    runner = FakeRunner()
    standby: dict = {}

    await asyncio.wait_for(
        consume_turns(
            stop, worker_id="w-collab", runner=runner,
            consumer_factory=lambda *a, **k: consumer, standby_state=standby,
        ),
        timeout=2,
    )

    assert runner.calls == ["t1", "t2"]
    assert consumer.commits == 1
    assert consumer.stopped and standby["kafka"] == "consuming"


async def test_consume_turns_isolates_poison_message():
    """一条消息执行抛异常，其余消息仍被处理并提交（不阻塞消费循环）。"""
    stop = asyncio.Event()
    consumer = FakeConsumer(
        [[{"turn_id": "bad"}, {"turn_id": "good"}]], stop_event=stop
    )
    runner = FakeRunner(raise_for=["bad"])

    await asyncio.wait_for(
        consume_turns(stop, worker_id="w", runner=runner,
                      consumer_factory=lambda *a, **k: consumer),
        timeout=2,
    )

    assert runner.calls == ["bad", "good"]
    assert consumer.commits == 1


async def test_consume_turns_degrades_when_start_fails():
    """broker 不可达：退化为仅心跳，不抛异常、不提交。"""
    stop = asyncio.Event()
    consumer = FakeConsumer([], start_error=ConnectionError("broker down"))
    standby: dict = {}

    await asyncio.wait_for(
        consume_turns(stop, worker_id="w", runner=FakeRunner(),
                      consumer_factory=lambda *a, **k: consumer,
                      standby_state=standby),
        timeout=2,
    )

    assert standby["kafka"] == "degraded"
    assert consumer.commits == 0


# ============================================================
# 孤儿扫描
# ============================================================

async def test_orphan_scan_loop_recovers_and_stops():
    stop = asyncio.Event()
    runner = FakeRunner(orphans=[TurnOutcome(turn_id="t1", status=TURN_COMPLETED)])
    task = asyncio.create_task(orphan_scan_loop(runner, stop, interval=0.01))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert runner.orphan_calls >= 1


async def test_orphan_scan_loop_survives_scan_error():
    """扫描抛异常不杀进程（下一周期重试）。"""
    stop = asyncio.Event()
    runner = FakeRunner(raise_on_scan=True)
    task = asyncio.create_task(orphan_scan_loop(runner, stop, interval=0.01))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2)  # 未上抛即通过
    assert runner.orphan_calls >= 1


# ============================================================
# kill-worker 故障演练：worker A 僵死 → worker B 孤儿扫描接力续跑
# ============================================================

async def test_kill_worker_drill_orphan_scan_finishes_turn():
    store, locks = FakeTurnStore(), make_locks()
    events, emit = make_emit()
    reg = make_registry()
    graph = await _build_graph(reg)

    turn = await store.create_turn("conv-1", "u1", mode="kafka")
    turn_id = turn["turn_id"]

    # worker A：跑到图 END 产生 checkpoint（发言落 transcript），随后「崩溃」未回写 completed
    st = initial_state(
        conversation_id="conv-1", turn_id=turn_id, case_type="court",
        host_agent_id="judge", roster=["plaintiff_lawyer", "defense_lawyer"],
        max_rounds=2, user_message="请开始庭审",
    )
    await graph.ainvoke(
        st, config={"configurable": {"thread_id": turn_id}, "recursion_limit": 50}
    )
    msgs_before = len(await _final_messages(graph, turn_id))
    store.turns[turn_id]["status"] = TURN_RUNNING
    store.turns[turn_id]["worker_heartbeat"] = time.time() - 999  # 租约过期（A 僵死）

    # worker B：孤儿扫描认领并从断点续跑
    runner = make_runner(
        graph=graph, store=store, locks=locks, emit=emit,
        conv_store=FakeConvStore(), lease_seconds=90,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(orphan_scan_loop(runner, stop, interval=0.01))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2)

    assert store.turns[turn_id]["status"] == TURN_COMPLETED
    assert store.turns[turn_id]["worker_id"] == "w1"  # 被 B 认领
    assert store.turns[turn_id]["completed_at"] is not None
    # 幂等：从 checkpoint 续跑不重复发言
    assert len(await _final_messages(graph, turn_id)) == msgs_before
