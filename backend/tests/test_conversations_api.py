"""T1.1 协同会话 API + SSE 回放测试（内存 Store + FakeRedis，不依赖外部服务）。"""
import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, ".")

from app.core import redis_client as rc_mod
from app.core.response import register_exception_handlers
from app.core.security import get_current_user
from app.routers import collab as collab_router_mod
from app.routers import conversations as conv_mod
from app.services.collab.runner import TurnOutcome


# ============================================================
# FakeRedis：仅实现 T1.1 用到的结构（String/List/Stream/PubSub）
# ============================================================

class FakePubSub:
    def __init__(self, fake: "FakeRedis"):
        self._fake = fake
        self._channels: set[str] = set()
        self._queue: asyncio.Queue = asyncio.Queue()

    async def subscribe(self, channel: str):
        self._channels.add(channel)
        self._fake._subscribers.setdefault(channel, set()).add(self)

    async def get_message(self, ignore_subscribe_messages=True, timeout=0.0):
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def _deliver(self, payload: dict):
        self._queue.put_nowait({"type": "message", "data": json.dumps(payload, ensure_ascii=False)})

    async def aclose(self):
        for ch in list(self._channels):
            self._fake._subscribers.get(ch, set()).discard(self)
        self._channels.clear()


class _FakePipe:
    def __init__(self, fake: "FakeRedis"):
        self._fake = fake
        self._ops: list = []

    def __getattr__(self, name):
        def rec(*args, **kwargs):
            self._ops.append((name, args, kwargs))
        return rec

    async def execute(self):
        out = []
        for name, args, kwargs in self._ops:
            out.append(await getattr(self._fake, name)(*args, **kwargs))
        self._ops.clear()
        return out


class FakeRedis:
    def __init__(self):
        self.strings: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.streams: dict[str, list[tuple[str, dict]]] = {}
        self.locks: dict[str, str] = {}
        self._subscribers: dict[str, set[FakePubSub]] = {}
        self._seq = 0

    # ---- String ----
    async def set(self, key, value, nx=False, px=None, ex=None):
        if nx and key in self.strings:
            return None
        self.strings[key] = value
        return True

    async def get(self, key):
        return self.strings.get(key)

    async def getdel(self, key):
        return self.strings.pop(key, None)

    async def delete(self, *keys):
        n = 0
        for k in keys:
            self.strings.pop(k, None)
            if k in self.lists:
                del self.lists[k]; n += 1
        return n

    async def exists(self, key):
        return 1 if key in self.strings else 0

    async def eval(self, _script, _numkeys, key, holder):
        # acquire_turn_lock 走 SET NX（存 strings）；释放脚本比对同一 key
        if self.strings.get(key) == holder:
            self.strings.pop(key, None)
            return 1
        return 0

    # ---- List ----
    def pipeline(self):
        return _FakePipe(self)

    async def lpush(self, key, *values):
        lst = self.lists.setdefault(key, [])
        for v in values:
            lst.insert(0, v)
        return len(lst)

    async def lrange(self, key, start, stop):
        lst = self.lists.get(key, [])
        if stop == -1:
            return lst[start:]
        return lst[start:stop + 1]

    async def ltrim(self, key, start, stop):
        lst = self.lists.get(key)
        if lst is not None:
            self.lists[key] = lst[start:stop + 1]
        return True

    async def expire(self, key, seconds):
        return True

    # ---- Stream + PubSub ----
    async def xadd(self, key, fields, maxlen=None, approximate=True):
        self._seq += 1
        entry_id = f"{1700000000000 + self._seq}-0"
        self.streams.setdefault(key, []).append((entry_id, dict(fields)))
        if maxlen is not None:
            self.streams[key] = self.streams[key][-maxlen:]
        return entry_id

    async def xrange(self, key, min="-", max="+", count=None):
        entries = self.streams.get(key, [])
        result = []
        for eid, fields in entries:
            if min != "-" and not rc_mod.stream_id_gt(eid, min.lstrip("(")):
                continue
            result.append((eid, fields))
        return result[:count] if count else result

    async def publish(self, channel, message):
        payload = json.loads(message)
        n = 0
        for sub in list(self._subscribers.get(channel, set())):
            sub._deliver(payload)
            n += 1
        return n

    def pubsub(self):
        return FakePubSub(self)


# ============================================================
# 内存版 ConversationStore（业务语义对齐 PgConversationStore）
# ============================================================

class InMemoryStore:
    def __init__(self):
        self.convs: dict[str, dict] = {}
        self.members: dict[str, list[dict]] = {}
        self.messages: dict[str, list[dict]] = {}
        self._base = datetime(2026, 10, 16, tzinfo=timezone.utc)
        self._clock = 0
        self.agents = {
            "general_assistant": {"agent_id": "general_assistant", "name": "法律助手", "enabled": True, "sort_order": 10},
            "legal_analyst": {"agent_id": "legal_analyst", "name": "法务分析师", "enabled": True, "sort_order": 20},
            "legal_researcher": {"agent_id": "legal_researcher", "name": "法规检索员", "enabled": True, "sort_order": 40},
            "disabled_one": {"agent_id": "disabled_one", "name": "停用Agent", "enabled": False, "sort_order": 99},
        }
        self.templates = {
            "custom": {
                "case_type": "custom", "name": "自定义", "enabled": True,
                "host_agent_id": "legal_analyst",
                "roster": [{"agent_id": "legal_analyst", "stage": "debate", "order": 1},
                           {"agent_id": "legal_researcher", "stage": "debate", "order": 2}],
            }
        }

    def _now(self):
        # 严格单调递增（分页游标依赖 created_at 全序，不能用 %60 回绕）
        self._clock += 1
        return (self._base + timedelta(seconds=self._clock)).isoformat()

    async def list_conversations(self, user_id, status=None):
        out = [dict(c, members=list(self.members.get(c["id"], [])))
               for c in self.convs.values() if c["user_id"] == user_id and (status is None or c["status"] == status)]
        return sorted(out, key=lambda c: c["updated_at"], reverse=True)

    async def create_conversation(self, user_id, conv_type, case_type, title, extra_agent_ids,
                                  my_role=None, target_agent_id=None):
        host_id, roster_ids = None, []
        if case_type:
            tpl = self.templates.get(case_type)
            if not tpl or not tpl["enabled"]:
                from app.core.errors import InvalidParamsError
                raise InvalidParamsError("未知或已停用的案情模板")
            host_id, roster_ids = tpl["host_agent_id"], [i["agent_id"] for i in tpl["roster"]]
            title = title or tpl["name"]
        elif conv_type == "direct":
            roster_ids = [target_agent_id or "general_assistant"]
        seen, ordered = set(), []
        for aid in [*roster_ids, *(extra_agent_ids or [])]:
            if aid not in seen:
                seen.add(aid); ordered.append(aid)
        if host_id and host_id not in seen:
            ordered.insert(0, host_id); seen.add(host_id)
        if not ordered:
            from app.core.errors import InvalidParamsError
            raise InvalidParamsError("至少一个 Agent")
        if my_role and my_role not in seen:
            from app.core.errors import InvalidParamsError
            raise InvalidParamsError(f"my_role 不在会话成员中：{my_role}")
        for aid in ordered:
            ag = self.agents.get(aid)
            if not ag or not ag["enabled"]:
                from app.core.errors import InvalidParamsError
                raise InvalidParamsError(f"Agent 不存在或已停用：{aid}")
        cid = str(uuid.uuid4())
        auto = set(roster_ids) | ({host_id} if host_id else set())
        conv = {"id": cid, "user_id": user_id, "type": conv_type, "case_type": case_type,
                "title": title, "status": "active",
                "my_role": my_role, "target_agent_id": target_agent_id,
                "created_at": self._now(), "updated_at": self._now()}
        self.convs[cid] = conv
        self.members[cid] = [
            {"agent_id": aid, "role": "host" if aid == host_id else "member",
             "is_auto": aid in auto, "joined_at": self._now(),
             "name": self.agents[aid]["name"], "sort_order": self.agents[aid]["sort_order"]}
            for aid in ordered
        ]
        return await self.get_conversation(cid)

    async def get_conversation(self, conversation_id):
        c = self.convs.get(str(conversation_id))
        if not c:
            return None
        return dict(c, members=list(self.members.get(c["id"], [])))

    async def update_conversation(self, conversation_id, title=None, status=None):
        c = self.convas_get(conversation_id)
        if title is not None: c["title"] = title
        if status is not None: c["status"] = status
        return await self.get_conversation(conversation_id)

    async def set_my_role(self, conversation_id, my_role):
        c = self.convas_get(conversation_id)
        c["my_role"] = my_role
        return await self.get_conversation(conversation_id)

    def convas_get(self, conversation_id):
        c = self.convs.get(str(conversation_id))
        if c is None:
            from app.core.errors import NotFoundError
            raise NotFoundError("会话不存在")
        return c

    async def add_member(self, conversation_id, agent_id, is_auto):
        c = self.convas_get(conversation_id)
        ag = self.agents.get(agent_id)
        if not ag or not ag["enabled"]:
            from app.core.errors import InvalidParamsError
            raise InvalidParamsError(f"Agent 不存在或已停用：{agent_id}")
        if any(m["agent_id"] == agent_id for m in self.members[c["id"]]):
            from app.core.errors import ConflictError
            raise ConflictError("Agent 已在会话中")
        member = {"agent_id": agent_id, "role": "member", "is_auto": is_auto,
                  "joined_at": self._now(), "name": ag["name"], "sort_order": ag["sort_order"]}
        self.members[c["id"]].append(member)
        return member

    async def remove_member(self, conversation_id, agent_id):
        c = self.convas_get(conversation_id)
        before = len(self.members[c["id"]])
        self.members[c["id"]] = [m for m in self.members[c["id"]] if m["agent_id"] != agent_id]
        return len(self.members[c["id"]]) < before

    async def list_messages_page(self, conversation_id, before_id, limit):
        msgs = sorted(self.messages.get(str(conversation_id), []),
                      key=lambda m: (m["created_at"], m["id"]), reverse=True)
        if before_id:
            anchor = next((m for m in msgs if m["id"] == str(before_id)), None)
            if anchor:
                msgs = [m for m in msgs if (m["created_at"], m["id"]) < (anchor["created_at"], anchor["id"])]
        page = msgs[:limit + 1]
        has_more = len(page) > limit
        page = page[:limit]
        next_before = page[-1]["id"] if has_more else None
        return list(reversed(page)), next_before

    async def insert_message(self, conversation_id, *, sender_type, sender_id, sender_name,
                             content, msg_type, round, metadata, created_at=None):
        c = self.convas_get(conversation_id)
        msg = {"id": str(uuid.uuid4()), "conversation_id": c["id"],
               "sender_type": sender_type, "sender_id": sender_id, "sender_name": sender_name,
               "content": content, "msg_type": msg_type, "round": round,
               "fork_parent_message_id": None, "metadata": metadata or {},
               "created_at": created_at.isoformat() if created_at is not None else self._now()}
        self.messages.setdefault(c["id"], []).append(msg)
        c["updated_at"] = self._now()
        return msg

    async def get_agent(self, agent_id):
        return self.agents.get(agent_id)

    async def get_template(self, case_type):
        return self.templates.get(case_type)


# ============================================================
# 假轮次执行器（T1.6 M3）：API 层只做路由断言，不跑图
# ============================================================

class FakeTurnRunner:
    """极简执行器：``store`` 即自身；``execute/resume`` 直接判 completed，不驱动图。"""

    def __init__(self):
        self.created: list[dict] = []
        self.resumed: list[tuple[str, object]] = []

    @property
    def store(self) -> "FakeTurnRunner":
        return self

    async def get_open_turn(self, conversation_id):
        return None

    async def create_turn(self, conversation_id, user_id, *, mode="inprocess",
                          trigger_message_id=None, forked_from_turn_id=None):
        turn = {"turn_id": f"turn-{len(self.created) + 1}", "conversation_id": conversation_id,
                "user_id": user_id, "status": "running", "mode": mode,
                "trigger_message_id": trigger_message_id, "forked_from_turn_id": forked_from_turn_id}
        self.created.append(turn)
        return dict(turn)

    async def get_turn(self, turn_id):
        return next((t for t in self.created if t["turn_id"] == turn_id), None)

    async def execute_turn(self, turn_id, **kwargs):
        return TurnOutcome(turn_id=turn_id, status="completed")

    async def resume_turn(self, turn_id, resume_value, **kwargs):
        self.resumed.append((turn_id, resume_value))
        return TurnOutcome(turn_id=turn_id, status="completed")


# ============================================================
# Fixtures
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
    application.include_router(collab_router_mod.router)
    application.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    application.dependency_overrides[conv_mod.get_store] = lambda: store
    application.dependency_overrides[conv_mod.get_turn_runner] = lambda: FakeTurnRunner()
    return application


@pytest.fixture
def client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def _create_group(client, case_type="custom", agent_ids=None, my_role=None):
    resp = await client.post("/api/conversations",
                             json={"type": "group", "case_type": case_type,
                                   "agent_ids": agent_ids or [], "my_role": my_role})
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


# ============================================================
# 会话 / 成员
# ============================================================

@pytest.mark.asyncio
async def test_create_group_fills_template_roster(client):
    conv = await _create_group(client)
    roles = {m["agent_id"]: m["role"] for m in conv["members"]}
    assert roles["legal_analyst"] == "host"
    assert "legal_researcher" in roles
    assert conv["case_type"] == "custom"


@pytest.mark.asyncio
async def test_create_with_unknown_agent_rejected(client):
    resp = await client.post("/api/conversations",
                             json={"type": "group", "agent_ids": ["ghost"]})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001


@pytest.mark.asyncio
async def test_add_and_remove_member(client):
    conv = await _create_group(client)
    cid = conv["id"]
    # 重复添加 → 409/40009
    await client.post(f"/api/conversations/{cid}/members", json={"agent_id": "general_assistant"})
    dup = await client.post(f"/api/conversations/{cid}/members", json={"agent_id": "general_assistant"})
    assert dup.status_code == 409 and dup.json()["code"] == 40009
    # 停用 Agent → 400
    bad = await client.post(f"/api/conversations/{cid}/members", json={"agent_id": "disabled_one"})
    assert bad.status_code == 400
    removed = await client.delete(f"/api/conversations/{cid}/members?agent_id=general_assistant")
    assert removed.status_code == 200
    detail = await client.get(f"/api/conversations/{cid}")
    assert all(m["agent_id"] != "general_assistant" for m in detail.json()["data"]["members"])


@pytest.mark.asyncio
async def test_ownership_forbidden(client, store, app):
    conv = await _create_group(client)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "intruder"}
    resp = await client.get(f"/api/conversations/{conv['id']}")
    assert resp.status_code == 403 and resp.json()["code"] == 40301
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}


@pytest.mark.asyncio
async def test_unknown_conversation_404(client):
    resp = await client.get(f"/api/conversations/{uuid.uuid4()}")
    assert resp.status_code == 404 and resp.json()["code"] == 40004


# ============================================================
# B1 / B3：单聊目标 Agent / 建群扮演角色（T1.2）
# ============================================================

@pytest.mark.asyncio
async def test_direct_requires_target_agent_id(client):
    # 缺 target_agent_id → 400
    missing = await client.post("/api/conversations", json={"type": "direct"})
    assert missing.status_code == 400 and missing.json()["code"] == 40001
    # 指定目标 Agent → 201，且成员只有该 Agent
    ok = await client.post("/api/conversations",
                           json={"type": "direct", "target_agent_id": "legal_analyst"})
    assert ok.status_code == 201, ok.text
    conv = ok.json()["data"]
    assert conv["target_agent_id"] == "legal_analyst"
    assert [m["agent_id"] for m in conv["members"]] == ["legal_analyst"]


@pytest.mark.asyncio
async def test_direct_rejects_my_role_and_group_rejects_target(client):
    d = await client.post("/api/conversations",
                          json={"type": "direct", "target_agent_id": "legal_analyst",
                                "my_role": "legal_analyst"})
    assert d.status_code == 400 and d.json()["code"] == 40001
    g = await client.post("/api/conversations",
                          json={"type": "group", "case_type": "custom",
                                "target_agent_id": "legal_analyst"})
    assert g.status_code == 400 and g.json()["code"] == 40001


@pytest.mark.asyncio
async def test_my_role_must_be_in_roster(client):
    # 不在 roster → 400
    bad = await client.post("/api/conversations",
                            json={"type": "group", "case_type": "custom", "my_role": "ghost"})
    assert bad.status_code == 400 and bad.json()["code"] == 40001
    # 在 roster → 201 且落库
    ok = await client.post("/api/conversations",
                           json={"type": "group", "case_type": "custom", "my_role": "legal_analyst"})
    assert ok.status_code == 201, ok.text
    assert ok.json()["data"]["my_role"] == "legal_analyst"


@pytest.mark.asyncio
async def test_set_my_role_endpoint(client):
    conv = await _create_group(client, my_role="legal_analyst")
    cid = conv["id"]
    assert conv["my_role"] == "legal_analyst"

    # 切换到另一成员
    resp = await client.post(f"/api/conversations/{cid}/my_role",
                             json={"my_role": "legal_researcher"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["my_role"] == "legal_researcher"

    # 交还给 AI（空）
    cleared = await client.post(f"/api/conversations/{cid}/my_role", json={"my_role": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["my_role"] is None

    # 非成员 → 400
    bad = await client.post(f"/api/conversations/{cid}/my_role", json={"my_role": "ghost"})
    assert bad.status_code == 400 and bad.json()["code"] == 40001


@pytest.mark.asyncio
async def test_set_my_role_rejected_for_direct(client):
    conv = await client.post("/api/conversations",
                             json={"type": "direct", "target_agent_id": "legal_analyst"})
    cid = conv.json()["data"]["id"]
    resp = await client.post(f"/api/conversations/{cid}/my_role", json={"my_role": None})
    assert resp.status_code == 400 and resp.json()["code"] == 40001


@pytest.mark.asyncio
async def test_template_id_alias_fills_roster(client):
    resp = await client.post("/api/conversations",
                             json={"type": "group", "template_id": "custom"})
    assert resp.status_code == 201, resp.text
    conv = resp.json()["data"]
    assert conv["case_type"] == "custom"
    assert {m["agent_id"] for m in conv["members"]} >= {"legal_analyst", "legal_researcher"}


# ============================================================
# 消息：缓存 / 分页 / 50901
# ============================================================

@pytest.mark.asyncio
async def test_send_and_list_messages_uses_cache(client, fake_redis):
    conv = await _create_group(client)
    cid = conv["id"]
    for text in ("第一条", "第二条"):
        resp = await client.post(f"/api/conversations/{cid}/messages", json={"content": text})
        assert resp.status_code == 201
        assert resp.json()["data"]["turn_id"] is not None  # T1.6 runner 已接入：起轮次
    listed = await client.get(f"/api/conversations/{cid}/messages")
    body = listed.json()["data"]
    assert [m["content"] for m in body["messages"]] == ["第一条", "第二条"]
    assert body["cached"] is True  # POST 已写热缓存
    # Stream 事件也已落
    events = await fake_redis.xrange(rc_mod.conv_events_key(cid))
    assert len(events) == 2


@pytest.mark.asyncio
async def test_message_pagination_keyset(client, store):
    conv = await _create_group(client)
    cid = conv["id"]
    for i in range(25):
        await client.post(f"/api/conversations/{cid}/messages", json={"content": f"m{i:02d}"})
    # 强制绕过缓存测 PG 分页（游标页本就不查缓存）
    first = await client.get(f"/api/conversations/{cid}/messages?limit=20")
    page1 = first.json()["data"]["messages"]
    cursor = first.json()["data"]["next_before"]
    assert len(page1) == 20 and cursor is not None
    page2 = await client.get(f"/api/conversations/{cid}/messages?before={cursor}&limit=20")
    page2_msgs = page2.json()["data"]["messages"]
    assert len(page2_msgs) == 5 and page2.json()["data"]["next_before"] is None
    # 不重不丢：25 条 id 唯一，且时间顺序衔接
    ids = [m["id"] for m in page1] + [m["id"] for m in page2_msgs]
    assert len(set(ids)) == 25
    assert page1[-1]["created_at"] >= page2_msgs[0]["created_at"]


@pytest.mark.asyncio
async def test_turn_lock_conflict_50901(client, fake_redis):
    conv = await _create_group(client)
    cid = conv["id"]
    # 模拟 T1.6 runner 持锁
    ok = await rc_mod.acquire_turn_lock(cid, "runner-A")
    assert ok is True
    resp = await client.post(f"/api/conversations/{cid}/messages", json={"content": "再发一条"})
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == 50901 and body["retryable"] is True
    # 锁释放后恢复
    assert await rc_mod.release_turn_lock(cid, "runner-A") is True
    again = await client.post(f"/api/conversations/{cid}/messages", json={"content": "再发一条"})
    assert again.status_code == 201


@pytest.mark.asyncio
async def test_lock_holder_token_protected(fake_redis):
    # 别人的令牌不能释放这把锁
    await rc_mod.acquire_turn_lock("c1", "runner-A")
    assert await rc_mod.release_turn_lock("c1", "runner-B") is False
    assert await rc_mod.get_turn_lock_holder("c1") == "runner-A"


# ============================================================
# SSE：短票据 + Stream 回放 + 不丢不重
# ============================================================

class _Disconnected:
    """假 Request：永不判定断开，供生成器级死循环测试使用。"""

    async def is_disconnected(self):
        return False


async def _drain(gen, n, timeout=2.0):
    """从 SSE 生成器拉取 n 条事件（超时保护）。"""
    out = []
    for _ in range(n):
        out.append(await asyncio.wait_for(gen.__anext__(), timeout=timeout))
    return out


# 说明：httpx ASGITransport 不增量 flush SSE 中间分片（只在响应完成时交付），
# 因此流式端点只能用生成器级测试；票据/校验等在响应完成前即返回，仍走 HTTP。
@pytest.mark.asyncio
async def test_ticket_endpoint_and_one_shot_consume(client, fake_redis):
    conv = await _create_group(client)
    cid = conv["id"]
    await client.post(f"/api/conversations/{cid}/messages", json={"content": "已有消息"})

    ticket_resp = await client.post(f"/api/collab/conversations/{cid}/events/ticket")
    assert ticket_resp.status_code == 200
    token = ticket_resp.json()["data"]["events_token"]
    assert token and ticket_resp.json()["data"]["expires_in"] == 60

    # 票据一次性（GETDEL）：首次消费成功且绑定会话，二次返回 None
    assert await rc_mod.consume_sse_ticket(token, cid) == {
        "user_id": "u1", "conversation_id": cid,
    }
    assert await rc_mod.consume_sse_ticket(token, cid) is None
    # 会话不匹配 → 判无效且票据已被消耗
    other = (await client.post(
        f"/api/collab/conversations/{cid}/events/ticket"
    )).json()["data"]["events_token"]
    assert await rc_mod.consume_sse_ticket(other, "other-conv") is None

    # 无票据 / 无效票据：在生成响应前即返回（信封 400 / 401）
    assert (await client.get(f"/api/collab/conversations/{cid}/events")).status_code == 400
    bad = await client.get(f"/api/collab/conversations/{cid}/events?events_token=nope")
    assert bad.status_code == 401

    # 生成器级回放：last_id="0" 时补发全部历史（id = Stream entry id）
    gen = collab_router_mod._conv_event_stream(_Disconnected(), cid, "0")
    ev = await asyncio.wait_for(gen.__anext__(), timeout=2)
    assert ev["id"] == "1700000000001-0"
    assert ev["event"] == "message"
    assert json.loads(ev["data"])["content"] == "已有消息"
    await gen.aclose()


@pytest.mark.asyncio
async def test_sse_reconnect_no_loss_no_dup(client, fake_redis):
    conv = await _create_group(client)
    cid = conv["id"]

    def _eid(resp):
        return resp.json()["data"]["event_id"]

    e1 = _eid(await client.post(f"/api/conversations/{cid}/messages", json={"content": "m1"}))
    e2 = _eid(await client.post(f"/api/conversations/{cid}/messages", json={"content": "m2"}))

    # 第一次订阅：从 0 回放，收到 m1、m2
    gen1 = collab_router_mod._conv_event_stream(_Disconnected(), cid, "0")
    got1 = await _drain(gen1, 2)
    await gen1.aclose()
    assert [e["id"] for e in got1] == [e1, e2]

    # 断线期间来一条新消息
    e3 = _eid(await client.post(f"/api/conversations/{cid}/messages", json={"content": "m3"}))

    # 重连：以 Last-Event-ID=e2 续，只补 m3（不重不丢）
    gen2 = collab_router_mod._conv_event_stream(_Disconnected(), cid, e2)
    got2 = await _drain(gen2, 1)
    await gen2.aclose()
    assert [e["id"] for e in got2] == [e3]
    assert {e["id"] for e in got1}.isdisjoint({e["id"] for e in got2})


@pytest.mark.asyncio
async def test_sse_live_pubsub_and_dedupe(fake_redis, monkeypatch):
    """生成器级：订阅后的实时事件走 PubSub；重复 ID 不二次下发。"""
    # 测试内把 ping 超时缩短（生产为 15s；0.5s 足够覆盖 0.05s 的发布竞态）
    monkeypatch.setattr(collab_router_mod, "SSE_PING_SECONDS", 0.5)
    cid = "conv-live"
    e1 = await rc_mod.append_conv_event(cid, "message", {"content": "e1"})
    e2 = await rc_mod.append_conv_event(cid, "message", {"content": "e2"})

    gen = collab_router_mod._conv_event_stream(_Disconnected(), cid, "0")
    got = []
    got.append(await asyncio.wait_for(gen.__anext__(), timeout=2))  # replay e1
    got.append(await asyncio.wait_for(gen.__anext__(), timeout=2))  # replay e2

    live_ids = []

    async def push_live():
        await asyncio.sleep(0.05)
        live_ids.append(await rc_mod.append_conv_event(cid, "message", {"content": "e3"}))

    task = asyncio.create_task(push_live())
    ev3 = await asyncio.wait_for(gen.__anext__(), timeout=2)  # live e3 via PubSub
    await task
    assert [e["id"] for e in got] == [e1, e2]
    assert ev3["id"] == live_ids[0] != e2

    # 模拟 PubSub 重复投递同 ID（重发）→ 必须被忽略，下一个是 ping 注释
    sub = list(fake_redis._subscribers[rc_mod.conv_events_key(cid)])[0]
    sub._deliver({"id": ev3["id"], "event": "message", "data": {"content": "dup"}})
    nxt = await asyncio.wait_for(gen.__anext__(), timeout=2)
    assert nxt.get("comment") == "ping"  # dup 被吞，15s 超时由 fake 瞬时返回 → ping
    await gen.aclose()

# ============================================================
# 会商纪要（T1.9-M2）：POST /{id}/minutes
# ============================================================

@pytest.mark.asyncio
async def test_generate_minutes_endpoint(client, app):
    conv = await _create_group(client)
    calls: list[str] = []

    class FakeMinutesRunner:
        async def generate(self, conversation_id):
            calls.append(conversation_id)
            return {
                "message": {"id": "m-min-1", "msg_type": "minutes",
                            "conversation_id": conversation_id, "content": "# 会商纪要"},
                "event_id": None,
                "reused": False,
            }

    app.dependency_overrides[conv_mod.get_minutes_runner] = lambda: FakeMinutesRunner()
    resp = await client.post(f"/api/conversations/{conv['id']}/minutes")
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["message"]["msg_type"] == "minutes"
    assert data["reused"] is False
    assert calls == [conv["id"]]


@pytest.mark.asyncio
async def test_generate_minutes_unknown_conversation_404(client):
    resp = await client.post(f"/api/conversations/{uuid.uuid4()}/minutes")
    assert resp.status_code == 404 and resp.json()["code"] == 40004


# ============================================================
# 转发到会话（T3.2）：POST /{id}/forward —— 上下文卡片，不触发轮次
# ============================================================

@pytest.mark.asyncio
async def test_forward_card_no_turn(client, fake_redis):
    conv = await _create_group(client)
    cid = conv["id"]
    citation = {"source": "民法典", "title": "第五百七十七条", "content": "违约责任"}
    resp = await client.post(
        f"/api/conversations/{cid}/forward",
        json={"card_type": "law_citation", "citations": [citation], "content": "违约责任条文"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    # 关键：不起轮次
    assert data["turn_id"] is None
    assert data["status"] == "forwarded"
    msg = data["message"]
    assert msg["msg_type"] == "card"
    assert msg["metadata"]["forwarded"] is True
    assert msg["metadata"]["citations"] == [citation]
    assert msg["round"] == 0

    # 落库可见（进历史，可供后续轮次 Agent 引用）
    listed = await client.get(f"/api/conversations/{cid}/messages")
    msgs = listed.json()["data"]["messages"]
    assert [m["id"] for m in msgs] == [msg["id"]]
    # SSE 广播一条（与 send_message 一样走 message 事件）
    events = await fake_redis.xrange(rc_mod.conv_events_key(cid))
    assert len(events) == 1


@pytest.mark.asyncio
async def test_forward_empty_rejected(client):
    conv = await _create_group(client)
    cid = conv["id"]
    resp = await client.post(
        f"/api/conversations/{cid}/forward", json={"content": "   ", "citations": []}
    )
    assert resp.status_code == 400 and resp.json()["code"] == 40001


@pytest.mark.asyncio
async def test_forward_ownership_forbidden(client, app):
    conv = await _create_group(client)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "intruder"}
    resp = await client.post(
        f"/api/conversations/{conv['id']}/forward", json={"content": "越权转发"}
    )
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    assert resp.status_code == 403 and resp.json()["code"] == 40301


# ============================================================
# 旧本地会话导入（T4.2）：POST /import —— direct 历史，不触发轮次
# ============================================================

@pytest.mark.asyncio
async def test_import_conversation_creates_direct_history(client, fake_redis):
    resp = await client.post(
        "/api/conversations/import",
        json={
            "title": "旧会话·违约责任",
            "messages": [
                {"role": "user", "content": "违约金过高怎么办？", "ts": "2026-09-01T10:00:00.000Z"},
                {"role": "assistant", "content": "可请求法院适当减少。", "ts": "2026-09-01T10:00:05.000Z"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    # 关键：不起轮次
    assert "turn_id" not in data
    assert data["imported"] == 2
    conv = data["conversation"]
    assert conv["type"] == "direct"
    assert conv["target_agent_id"] == "general_assistant"
    assert conv["title"] == "旧会话·违约责任"
    cid = conv["id"]

    # 落库可见：发送者映射正确，原始时间戳保留
    listed = await client.get(f"/api/conversations/{cid}/messages")
    msgs = listed.json()["data"]["messages"]
    assert [m["sender_type"] for m in msgs] == ["user", "agent"]
    assert msgs[0]["sender_id"] == "u1"
    assert msgs[1]["sender_id"] == "general_assistant"
    assert msgs[1]["sender_name"] == "法律助手"
    assert all(m["metadata"].get("imported") is True for m in msgs)
    assert msgs[0]["created_at"].startswith("2026-09-01T10:00:00")

    # 每条均广播 SSE（进入历史后可供后续轮次 Agent 引用）
    events = await fake_redis.xrange(rc_mod.conv_events_key(cid))
    assert len(events) == 2


@pytest.mark.asyncio
async def test_import_unknown_agent_rejected(client):
    resp = await client.post(
        "/api/conversations/import",
        json={"target_agent_id": "ghost", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 400 and resp.json()["code"] == 40001


@pytest.mark.asyncio
async def test_import_empty_messages_rejected(client):
    resp = await client.post("/api/conversations/import", json={"messages": []})
    assert resp.status_code == 400 and resp.json()["code"] == 40001


@pytest.mark.asyncio
async def test_import_too_many_messages_rejected(client):
    messages = [{"role": "user", "content": f"m{i}"} for i in range(201)]
    resp = await client.post("/api/conversations/import", json={"messages": messages})
    assert resp.status_code == 400 and resp.json()["code"] == 40001


@pytest.mark.asyncio
async def test_import_bad_role_and_blank_content_rejected(client):
    bad_role = await client.post(
        "/api/conversations/import",
        json={"messages": [{"role": "system", "content": "x"}]},
    )
    assert bad_role.status_code == 400 and bad_role.json()["code"] == 40001
    blank = await client.post(
        "/api/conversations/import",
        json={"messages": [{"role": "user", "content": "   "}]},
    )
    assert blank.status_code == 400 and blank.json()["code"] == 40001

