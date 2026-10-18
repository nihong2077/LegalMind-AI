"""T1.9-M2 会商纪要生成单元测试（Fake LLM/Store/Emitter，零外部依赖）。

覆盖：
- token 级流式事件序列：``status`` → ``message_start`` → 多帧 ``message_delta`` → ``message_end``；
- 幂等落库：同一轮次纪要二次调用「先查库后发」直接复用，不重复生成/推送；
- ``msg_type=minutes`` 落库 + 确定性 ``message_id``（uuid5(event_key)）；
- 空记录 → ``InvalidParamsError``；
- 发言人标签与材料拼装（用户 / 主持人 / Agent / 工具）。
"""
import sys
import uuid

import pytest

sys.path.insert(0, ".")

from app.core.errors import InvalidParamsError
from app.services.collab.minutes import (  # noqa: E402
    CLERK_AGENT_ID,
    MINUTES_HISTORY_LIMIT,
    MSG_TYPE_MINUTES,
    MinutesRunner,
    build_minutes_material,
)


# ============================================================
# 假件
# ============================================================

class FakeLLMClient:
    """``chat_stream`` 逐帧产出 OpenAI 风格 chunk（模拟 token 级流式）。"""

    def __init__(self, chunks=None):
        self._chunks = list(chunks or ["# 会商纪要\n", "## 一、会商议题\n", "合同效力"])
        self.calls = []

    async def chat_stream(self, *, model, messages, temperature=0.7, max_tokens=2048):
        self.calls.append({"model": model, "messages": messages})
        for c in self._chunks:
            yield {"choices": [{"delta": {"content": c}}]}


class FakeStore:
    """内存 Store：模拟 event_key 唯一约束 + 会话/消息读取。"""

    def __init__(self, conversation=None, messages=None):
        self.conversation = conversation
        self.messages = list(messages or [])
        self.records = {}

    async def get_conversation(self, conversation_id):
        return self.conversation

    async def list_messages_page(self, conversation_id, before_id, limit):
        return list(self.messages)[:limit], None

    async def get_message_by_event_key(self, conversation_id, event_key):
        return self.records.get(event_key)

    async def insert_message_once(self, conversation_id, *, event_key, **kw):
        if event_key in self.records:
            return None
        record = {"id": str(len(self.records) + 1), "event_key": event_key, **kw}
        self.records[event_key] = record
        return record


def make_emit():
    events = []

    async def emit(conversation_id, event_type, data):
        events.append((event_type, data))

    return events, emit


CONV = {
    "id": "c1",
    "title": "合同纠纷会商",
    "case_type": "contract",
    "members": [
        {"agent_id": "mediator", "role": "host", "name": "调解员"},
        {"agent_id": CLERK_AGENT_ID, "role": "member", "name": "书记员"},
    ],
}
MSGS = [
    {"sender_type": "user", "sender_id": "u1", "sender_name": "u1", "content": "合同是否有效？", "round": 1},
    {"sender_type": "host", "sender_id": "mediator", "sender_name": "调解员", "content": "请双方陈述", "round": 1},
    {"sender_type": "agent", "sender_id": "legal_analyst", "sender_name": "法务分析师", "content": "合同有效", "round": 1},
    {"sender_type": "tool", "sender_id": "legal_researcher", "sender_name": "法规检索员", "content": "民法典第143条", "round": 1},
]


def _runner(**kw):
    return MinutesRunner(
        llm=kw.pop("llm", FakeLLMClient()),
        store=kw.pop("store", FakeStore(conversation=CONV, messages=MSGS)),
        emit=kw.pop("emit", None) or make_emit()[1],
        **kw,
    )


# ============================================================
# 材料拼装
# ============================================================

def test_build_minutes_material_labels():
    text = build_minutes_material(CONV, MSGS)
    assert "会商主题：合同纠纷会商" in text
    assert "案情类型：contract" in text
    assert "[用户（u1）] 合同是否有效？" in text
    assert "[主持人·调解员] 请双方陈述" in text
    assert "[法务分析师] 合同有效" in text
    assert "[工具·法规检索员] 民法典第143条" in text


# ============================================================
# 生成：流式 + 落库 + 幂等
# ============================================================

@pytest.mark.asyncio
async def test_generate_streams_and_persists_minutes():
    events, emit = make_emit()
    store = FakeStore(conversation=CONV, messages=MSGS)
    llm = FakeLLMClient(["# 会商纪要\n", "## 一、会商议题\n", "合同效力"])
    runner = MinutesRunner(llm=llm, store=store, emit=emit)

    result = await runner.generate("c1")

    # 事件序列：status → start → delta*3 → end
    kinds = [e[0] for e in events]
    assert kinds[0] == "status" and events[0][1]["phase"] == "minutes"
    assert kinds[1] == "message_start" and events[1][1]["type"] == MSG_TYPE_MINUTES
    assert kinds[2:-1] == ["message_delta"] * 3
    assert kinds[-1] == "message_end"

    # 落库：msg_type=minutes，确定性 message_id，event_key 归一到 round
    msg = result["message"]
    assert result["reused"] is False
    assert msg["msg_type"] == MSG_TYPE_MINUTES
    assert msg["sender_id"] == CLERK_AGENT_ID
    event_key = "c1:minutes:r1"
    assert msg["event_key"] == event_key
    assert msg["metadata"]["message_id"] == str(uuid.uuid5(  # 与 message_id_for 一致
        uuid.UUID("6f1a4b7e-0c1d-4a5e-9b3c-c0ffee5eed01"), event_key
    ))
    # message_start / message_end 的 message_id 与落库一致
    assert events[1][1]["message_id"] == msg["metadata"]["message_id"]
    assert events[-1][1]["content"] == "# 会商纪要\n## 一、会商议题\n合同效力"
    # LLM 收到系统提示 + 材料
    assert llm.calls[0]["messages"][0]["role"] == "system"
    assert "会商记录如下" in llm.calls[0]["messages"][1]["content"]


@pytest.mark.asyncio
async def test_generate_idempotent_reuse():
    events, emit = make_emit()
    store = FakeStore(conversation=CONV, messages=MSGS)
    runner = MinutesRunner(llm=FakeLLMClient(), store=store, emit=emit)

    first = await runner.generate("c1")
    n_events = len(events)
    second = await runner.generate("c1")

    assert first["reused"] is False and second["reused"] is True
    assert second["message"]["id"] == first["message"]["id"]
    assert len(events) == n_events  # 复用不新增任何事件（不重复推送）


@pytest.mark.asyncio
async def test_generate_round_no_defaults_to_max_and_idempotent_key():
    events, emit = make_emit()
    store = FakeStore(
        conversation=CONV,
        messages=[{**MSGS[0], "round": 3}],
    )
    runner = MinutesRunner(llm=FakeLLMClient(), store=store, emit=emit)
    result = await runner.generate("c1")
    assert result["message"]["event_key"] == "c1:minutes:r3"
    assert result["message"]["round"] == 3


@pytest.mark.asyncio
async def test_generate_empty_transcript_raises():
    store = FakeStore(conversation=CONV, messages=[])
    runner = MinutesRunner(llm=FakeLLMClient(), store=store, emit=make_emit()[1])
    with pytest.raises(InvalidParamsError):
        await runner.generate("c1")


@pytest.mark.asyncio
async def test_generate_emit_failure_is_fail_open():
    """事件推送失败不影响纪要落库（Redis 降级静默）。"""
    store = FakeStore(conversation=CONV, messages=MSGS)

    async def boom(conversation_id, event_type, data):
        raise RuntimeError("redis down")

    runner = MinutesRunner(llm=FakeLLMClient(), store=store, emit=boom)
    result = await runner.generate("c1")
    assert result["message"]["msg_type"] == MSG_TYPE_MINUTES


def test_history_limit_constant():
    assert MINUTES_HISTORY_LIMIT >= 50
