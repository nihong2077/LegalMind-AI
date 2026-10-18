"""轮次发言分隔条单元测试（Fake Store / Emitter，零外部依赖）。

覆盖：
- 产出：``sender_type="system"`` + ``msg_type="notice"``，正文「下面是 X 发言」；
- 幂等键：``event_key = {turn}:r{round}:notice:0``，``message_id = uuid5(event_key)``，
  ``metadata.kind="speaker_notice"``（前端据此应用「无背景、小字居中」样式）；
- 幂等：「先查库后发」——同 ``event_key`` 二次调用不重复落库，仍复用既有记录重发事件；
- 中立性：正文不含「主持人/调度」等身份词；
- fail-open：Store/emit 抛异常时调用方不抛出，不阻断整轮。
"""
import sys

import pytest

sys.path.insert(0, ".")

from app.services.collab.graph import build_collab_graph  # noqa: E402
from app.services.collab.registry import RegistryService  # noqa: E402
from app.services.collab.speaker_notice import (  # noqa: E402
    KIND_SPEAKER_NOTICE,
    MSG_TYPE_NOTICE,
    make_speaker_notice,
)
from app.services.collab.state import initial_state  # noqa: E402


# ============================================================
# 假件
# ============================================================

class FakeStore:
    """内存 Store：模拟 event_key 唯一约束（ON CONFLICT DO NOTHING）。"""

    def __init__(self):
        self.records: dict[str, dict] = {}

    async def get_message_by_event_key(self, conversation_id, event_key):
        return self.records.get(event_key)

    async def insert_message_once(self, conversation_id, *, event_key, **kw):
        if event_key in self.records:
            return None
        record = {"id": f"m{len(self.records) + 1}", "event_key": event_key, **kw}
        self.records[event_key] = record
        return record


class BoomStore(FakeStore):
    async def get_message_by_event_key(self, conversation_id, event_key):
        raise RuntimeError("db down")


def make_emit():
    events = []

    async def emit(conversation_id, event_type, data):
        events.append((event_type, data))

    return events, emit


STATE = {"conversation_id": "c1", "turn_id": "t1", "round": 0}


# ============================================================
# 产出与幂等
# ============================================================

@pytest.mark.asyncio
async def test_notice_persist_and_emit():
    store = FakeStore()
    events, emit = make_emit()
    notice = make_speaker_notice(store=store, emit=emit)

    await notice(STATE, "judge", "法官")

    # round 为「即将开始的轮次」= 当前 round + 1
    record = store.records["t1:r1:notice:0"]
    assert record["content"] == "下面是 法官 发言"
    assert record["sender_type"] == "system"
    assert record["msg_type"] == MSG_TYPE_NOTICE
    assert record["round"] == 1
    assert record["metadata"]["kind"] == KIND_SPEAKER_NOTICE
    assert record["metadata"]["speaker_id"] == "judge"
    assert record["metadata"]["message_id"]

    assert len(events) == 1
    assert events[0][0] == "message"
    assert events[0][1]["event_key"] == "t1:r1:notice:0"


@pytest.mark.asyncio
async def test_notice_is_neutral_no_host_wording():
    store = FakeStore()
    _, emit = make_emit()
    notice = make_speaker_notice(store=store, emit=emit)

    await notice(STATE, "judge", "法官")
    content = store.records["t1:r1:notice:0"]["content"]
    for word in ("主持人", "调度", "排序"):
        assert word not in content


@pytest.mark.asyncio
async def test_notice_idempotent_rerun():
    store = FakeStore()
    events, emit = make_emit()
    notice = make_speaker_notice(store=store, emit=emit)

    await notice(STATE, "judge", "法官")
    await notice(STATE, "judge", "法官")  # 重跑/恢复

    assert len(store.records) == 1  # 不重复落库
    assert len(events) == 2  # 仍复用既有记录重发事件（前端可幂等合并）


@pytest.mark.asyncio
async def test_notice_uses_uuid5_message_id():
    import uuid

    store = FakeStore()
    _, emit = make_emit()
    notice = make_speaker_notice(store=store, emit=emit)
    await notice(STATE, "judge", "法官")

    from app.services.collab.agent_nodes import message_id_for

    assert (
        store.records["t1:r1:notice:0"]["metadata"]["message_id"]
        == str(uuid.uuid5(uuid.UUID("6f1a4b7e-0c1d-4a5e-9b3c-c0ffee5eed01"), "t1:r1:notice:0"))
        == message_id_for("t1:r1:notice:0")
    )


# ============================================================
# 降级 / 边界
# ============================================================

@pytest.mark.asyncio
async def test_notice_fail_open_on_store_error():
    events, emit = make_emit()
    notice = make_speaker_notice(store=BoomStore(), emit=emit)
    # 不抛出（fail-open）
    await notice(STATE, "judge", "法官")
    assert events == []


@pytest.mark.asyncio
async def test_notice_skips_without_turn_or_speaker():
    store = FakeStore()
    events, emit = make_emit()
    notice = make_speaker_notice(store=store, emit=emit)

    await notice({"conversation_id": "c1", "turn_id": "", "round": 0}, "judge", "法官")
    await notice(STATE, "", "法官")
    assert store.records == {}
    assert events == []


# ============================================================
# 图级：scheduler 定出下一个发言人 → 触发分隔条
# ============================================================

def _agent(agent_id, name, sort_order, is_tool=False):
    return {
        "agent_id": agent_id, "name": name, "avatar": None, "role_label": name,
        "description": f"{name}的职责", "skill_ref": None, "persona": "p",
        "model_pref": {}, "is_tool": is_tool, "sort_order": sort_order, "enabled": True,
    }


AGENTS = [
    _agent("host", "调解员", 10),
    _agent("plaintiff_lawyer", "原告律师", 20),
    _agent("defense_lawyer", "被告律师", 30),
]


def _registry():
    async def agent_loader():
        return [dict(a) for a in AGENTS]

    async def template_loader():
        return []

    return RegistryService(agent_loader=agent_loader, template_loader=template_loader)


@pytest.mark.asyncio
async def test_graph_invokes_speaker_notice():
    from langgraph.checkpoint.memory import InMemorySaver

    notices = []

    async def fake_notice(state, speaker_id, name):
        notices.append((speaker_id, name))

    graph = await build_collab_graph(
        registry=_registry(), speaker_notice=fake_notice, checkpointer=InMemorySaver()
    )
    state = initial_state(
        conversation_id="c1", turn_id="t1", case_type="consult",
        host_agent_id="host", roster=["plaintiff_lawyer", "defense_lawyer"],
    )
    cfg = {"configurable": {"thread_id": "t1"}, "recursion_limit": 50}
    await graph.ainvoke(state, config=cfg)

    # 默认 scheduler（模板顺序）依次点原告律师 → 被告律师，各触发一次分隔条
    assert notices == [("plaintiff_lawyer", "原告律师"), ("defense_lawyer", "被告律师")]


@pytest.mark.asyncio
async def test_graph_without_speaker_notice_still_runs():
    from langgraph.checkpoint.memory import InMemorySaver

    graph = await build_collab_graph(registry=_registry(), checkpointer=InMemorySaver())
    state = initial_state(
        conversation_id="c1", turn_id="t1", case_type="consult",
        host_agent_id="host", roster=["plaintiff_lawyer"],
    )
    cfg = {"configurable": {"thread_id": "t1"}, "recursion_limit": 50}
    out = await graph.ainvoke(state, config=cfg)  # 不注入 → 不产出分隔条，图照常跑完
    assert out is not None
