"""T1.6 M3 API 接入测试：send_message 驱动真 TurnRunner（假台账 + InMemorySaver 真图）。

覆盖：新轮次创建并执行 / ask_user 中断→resume 续跑 / B2 接管发言落库 + 交还撤销接管 /
checkpoints 时间线 + fork 端点 / SSE 事件（status·interaction_required·done）可消费。

不依赖 DB/Redis/LLM：Redis 用 FakeRedis，图用 InMemorySaver + 假回调，台账用内存实现。
"""
import sys
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver

sys.path.insert(0, ".")

from app.core import redis_client as rc_mod
from app.core.response import register_exception_handlers
from app.core.security import get_current_user
from app.routers import conversations as conv_mod
from app.services.collab.graph import build_collab_graph
from app.services.collab.runner import TurnRunner

from tests.test_collab_graph import make_registry
from tests.test_collab_runner import FakeTurnStore, _ask_user_advisor, fixed_agent_runner
from tests.test_conversations_api import FakeRedis, InMemoryStore, _create_group


# ============================================================
# Fixtures（复用 T1.1 的 FakeRedis / InMemoryStore）
# ============================================================

@pytest.fixture(autouse=True)
def fake_redis():
    fake = FakeRedis()
    rc_mod.redis_client = fake
    yield fake
    rc_mod.redis_client = None


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture
def app(store):
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(conv_mod.router)
    application.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    application.dependency_overrides[conv_mod.get_store] = lambda: store
    return application


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _make_runner(store, *, host_advisor=None, agent_runner=None) -> TurnRunner:
    """真 TurnRunner：真图（InMemorySaver）+ 内存台账 + 注入 conv_store/registry。"""
    reg = make_registry()
    graph = await build_collab_graph(
        registry=reg,
        host_advisor=host_advisor,
        agent_runner=agent_runner or fixed_agent_runner(),
        checkpointer=InMemorySaver(),
    )
    return TurnRunner(
        graph=graph, store=FakeTurnStore(), conv_store=store, registry=reg,
        worker_id="w-api", heartbeat_interval=0,  # 关闭心跳后台任务，避免时序噪声
    )


def _inject(app, runner):
    app.dependency_overrides[conv_mod.get_turn_runner] = lambda: runner


async def _seed_court_conv(store, *, my_role="plaintiff_lawyer") -> str:
    """直接种一个 court 会话（host=judge），用于验证接管式扮演暂停。"""
    cid = str(uuid.uuid4())
    store.convs[cid] = {
        "id": cid, "user_id": "u1", "type": "group", "case_type": "court",
        "title": "模拟庭审", "status": "active", "my_role": my_role,
        "target_agent_id": None, "created_at": store._now(), "updated_at": store._now(),
    }
    store.members[cid] = [
        {"agent_id": "judge", "role": "host", "is_auto": True, "joined_at": store._now(),
         "name": "法官", "sort_order": 90},
        {"agent_id": "plaintiff_lawyer", "role": "member", "is_auto": True,
         "joined_at": store._now(), "name": "原告律师", "sort_order": 70},
        {"agent_id": "defense_lawyer", "role": "member", "is_auto": True,
         "joined_at": store._now(), "name": "被告律师", "sort_order": 80},
        {"agent_id": "clerk", "role": "member", "is_auto": True,
         "joined_at": store._now(), "name": "书记员", "sort_order": 100},
    ]
    return cid


def _event_types(entries):
    return [fields["event"] for _, fields in entries]


# ============================================================
# 新轮次：创建 + 进程内执行 + SSE 事件可消费
# ============================================================

@pytest.mark.asyncio
async def test_send_message_runs_turn_and_streams_events(client, store, app, fake_redis):
    conv = await _create_group(client)
    cid = conv["id"]
    _inject(app, await _make_runner(store))

    resp = await client.post(f"/api/conversations/{cid}/messages", json={"content": "请开始会商"})
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["turn_id"] and data["status"] == "completed"
    assert data["message"]["content"] == "请开始会商"

    # SSE 事件可消费：Stream 中同时含用户 message 与 runner 的 status/done
    types = _event_types(await fake_redis.xrange(rc_mod.conv_events_key(cid)))
    assert "message" in types and "status" in types and "done" in types


@pytest.mark.asyncio
async def test_empty_content_rejected(client, store, app):
    conv = await _create_group(client)
    _inject(app, await _make_runner(store))
    resp = await client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "  "})
    assert resp.status_code == 400 and resp.json()["code"] == 40001


# ============================================================
# ask_user 中断 → 下一条消息路由为 resume
# ============================================================

@pytest.mark.asyncio
async def test_send_message_resumes_after_ask_user(client, store, app, fake_redis):
    conv = await _create_group(client)
    cid = conv["id"]
    _inject(app, await _make_runner(store, host_advisor=_ask_user_advisor()))

    first = await client.post(f"/api/conversations/{cid}/messages", json={"content": "开审"})
    assert first.json()["data"]["status"] == "interrupted"
    turn_id = first.json()["data"]["turn_id"]
    # 中断卡片（interaction_required）已进 SSE 流
    types = _event_types(await fake_redis.xrange(rc_mod.conv_events_key(cid)))
    assert "interaction_required" in types

    second = await client.post(f"/api/conversations/{cid}/messages", json={"content": "补充：合同原件"})
    body = second.json()["data"]
    assert body["status"] == "completed"
    assert body["turn_id"] == turn_id  # 同一轮次续跑，不新开轮次


# ============================================================
# B2 接管式扮演：轮到 my_role 暂停 → resume 以该角色身份落库
# ============================================================

@pytest.mark.asyncio
async def test_takeover_resume_persists_actor_message(client, store, app):
    cid = await _seed_court_conv(store)
    _inject(app, await _make_runner(store))

    first = await client.post(f"/api/conversations/{cid}/messages", json={"content": "开庭"})
    assert first.json()["data"]["status"] == "interrupted"

    resp = await client.post(
        f"/api/conversations/{cid}/messages",
        json={
            "content": "我主张被告构成违约",
            "metadata": {"actor_agent_id": "plaintiff_lawyer", "actor_agent_name": "原告律师"},
        },
    )
    body = resp.json()["data"]
    assert body["status"] == "completed"
    assert body["turn_id"] == first.json()["data"]["turn_id"]

    takeover = [
        m for m in store.messages[cid]
        if (m["metadata"] or {}).get("actor_agent_id") == "plaintiff_lawyer"
    ]
    assert takeover, "接管发言应以 metadata.actor_agent_id 落库"
    assert takeover[0]["content"] == "我主张被告构成违约"
    assert takeover[0]["sender_type"] == "user"


@pytest.mark.asyncio
async def test_hand_back_clears_my_role(client, store, app):
    cid = await _seed_court_conv(store)
    _inject(app, await _make_runner(store))

    first = await client.post(f"/api/conversations/{cid}/messages", json={"content": "开庭"})
    assert first.json()["data"]["status"] == "interrupted"

    resp = await client.post(
        f"/api/conversations/{cid}/messages",
        json={"content": "", "metadata": {"hand_back": True}},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["status"] == "completed"
    # 交还给 AI：跨轮撤销接管标志（控制动作不落聊天气泡）
    assert store.convs[cid]["my_role"] is None
    assert not any(
        (m["metadata"] or {}).get("hand_back") for m in store.messages.get(cid, [])
    )


# ============================================================
# checkpoints 时间线 / fork 端点
# ============================================================

@pytest.mark.asyncio
async def test_checkpoints_and_fork_endpoints(client, store, app):
    conv = await _create_group(client)
    cid = conv["id"]
    _inject(app, await _make_runner(store))

    post = await client.post(f"/api/conversations/{cid}/messages", json={"content": "开始"})
    turn_id = post.json()["data"]["turn_id"]

    ck = await client.get(f"/api/conversations/{cid}/turns/{turn_id}/checkpoints")
    assert ck.status_code == 200, ck.text
    items = ck.json()["data"]["checkpoints"]
    assert items and any(it["is_latest"] for it in items)
    source = next((it for it in items if it["round"] == 0), items[-1])

    forked = await client.post(
        f"/api/conversations/{cid}/turns/{turn_id}/fork",
        json={"checkpoint_id": source["checkpoint_id"]},
    )
    assert forked.status_code == 201, forked.text
    new_turn_id = forked.json()["data"]["turn_id"]
    assert new_turn_id != turn_id
    assert forked.json()["data"]["status"] == "completed"

    missing = await client.get(f"/api/conversations/{cid}/turns/ghost/checkpoints")
    assert missing.status_code == 404 and missing.json()["code"] == 40004


@pytest.mark.asyncio
async def test_unknown_turn_fork_rejected(client, store, app):
    conv = await _create_group(client)
    _inject(app, await _make_runner(store))
    resp = await client.post(
        f"/api/conversations/{conv['id']}/turns/ghost/fork",
        json={"checkpoint_id": "ckpt-1"},
    )
    assert resp.status_code == 404
