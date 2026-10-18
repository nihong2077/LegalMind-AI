"""T1.2 Agent 注册表 / 案情模板服务 + 只读 API 测试（注入假 loader，不依赖 DB）。"""
import sys

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, ".")

from app.core.response import register_exception_handlers
from app.core.security import get_current_user
from app.routers import agents as agents_router_mod
from app.services.collab.registry import (
    RegistryError,
    RegistryService,
    get_registry,
)


# ============================================================
# 假数据：10 个 Agent（含 2 个工具型/1 个停用）+ 3 个模板（含 court）
# ============================================================

def _agent(agent_id, name, role_label, sort_order, is_tool=False, enabled=True):
    return {
        "agent_id": agent_id, "name": name, "avatar": None, "role_label": role_label,
        "description": f"{name}的职责说明", "skill_ref": None, "persona": "p",
        "model_pref": {"temperature": 0.5}, "is_tool": is_tool,
        "sort_order": sort_order, "enabled": enabled,
    }


AGENTS = [
    _agent("general_assistant", "法律助手", "通用问答", 10),
    _agent("legal_analyst", "法务分析师", "案情分析", 20),
    _agent("contract_reviewer", "合同顾问", "合同审查", 30),
    _agent("legal_researcher", "法规检索员", "法规检索", 40, is_tool=True),
    _agent("case_searcher", "类案检索员", "类案检索", 50, is_tool=True),
    _agent("mediator", "调解员", "调解主持", 60),
    _agent("plaintiff_lawyer", "原告律师", "原告代理", 70),
    _agent("defense_lawyer", "被告律师", "被告代理", 80),
    _agent("judge", "法官", "庭审主持", 90),
    _agent("clerk", "书记员", "纪要文书", 100),
    _agent("retired_bot", "退役助手", "已停用", 200, enabled=False),
]

TEMPLATES = [
    {
        "case_type": "contract", "name": "合同纠纷", "icon": "file", "description": "d",
        "host_agent_id": "mediator",
        "roster": [
            {"agent_id": "legal_analyst", "stage": "debate", "order": 1},
            {"agent_id": "legal_researcher", "stage": "debate", "order": 2},
            {"agent_id": "mediator", "stage": "debate", "order": 3},
        ],
        "max_rounds": 2, "opening_enabled": True, "minutes_enabled": True,
        "adapter": "generic", "enabled": True,
    },
    {
        "case_type": "court", "name": "模拟庭审", "icon": "gavel", "description": "d",
        "host_agent_id": "judge",
        "roster": [
            {"agent_id": "plaintiff_lawyer", "stage": "opening", "order": 1},
            {"agent_id": "defense_lawyer", "stage": "debate", "order": 2},
            {"agent_id": "judge", "stage": "debate", "order": 3},
            {"agent_id": "clerk", "stage": "debate", "order": 4},
        ],
        "max_rounds": 3, "opening_enabled": True, "minutes_enabled": True,
        "adapter": "court", "enabled": True,
    },
    {
        "case_type": "archived_tpl", "name": "已停用模板", "icon": None, "description": "d",
        "host_agent_id": "legal_analyst",
        "roster": [{"agent_id": "legal_analyst", "stage": "debate", "order": 1}],
        "max_rounds": 2, "opening_enabled": True, "minutes_enabled": True,
        "adapter": "generic", "enabled": False,
    },
]


def make_service(agents=None, templates=None) -> RegistryService:
    async def agent_loader():
        return list(AGENTS if agents is None else agents)

    async def template_loader():
        return list(TEMPLATES if templates is None else templates)

    return RegistryService(agent_loader=agent_loader, template_loader=template_loader)


@pytest.fixture
def reg():
    return make_service()


@pytest.fixture
def app(reg):
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(agents_router_mod.router)
    application.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    application.dependency_overrides[get_registry] = lambda: reg
    return application


@pytest.fixture
def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ============================================================
# 注册表加载 / 查询
# ============================================================

@pytest.mark.asyncio
async def test_agents_loaded_and_sorted(reg):
    agents = await reg.all_agents()
    assert len(agents) == 10  # 停用的默认被过滤
    assert [a["agent_id"] for a in agents][:2] == ["general_assistant", "legal_analyst"]
    assert (await reg.get_agent("judge"))["name"] == "法官"
    assert await reg.get_agent("ghost") is None


@pytest.mark.asyncio
async def test_agents_filters(reg):
    assert {a["agent_id"] for a in await reg.tool_agents()} == {"legal_researcher", "case_searcher"}
    assert {a["agent_id"] for a in await reg.all_agents(is_tool=False)} >= {"judge", "mediator"}
    only_disabled = await reg.all_agents(include_disabled=True)
    assert "retired_bot" in {a["agent_id"] for a in only_disabled}
    by_q = await reg.all_agents(q="检索")
    assert {a["agent_id"] for a in by_q} == {"legal_researcher", "case_searcher"}
    by_ids = await reg.agents_by_ids(["judge", "ghost"])
    assert [a["agent_id"] for a in by_ids] == ["judge"]


# ============================================================
# 模板 → roster / host 映射
# ============================================================

@pytest.mark.asyncio
async def test_templates_only_enabled(reg):
    tpls = await reg.all_templates()
    assert {t["case_type"] for t in tpls} == {"contract", "court"}  # 停用模板不返回


@pytest.mark.asyncio
async def test_default_roster_opening_first(reg):
    # court 的 opening（原告）先于 debate（被告/法官/书记员）
    roster = await reg.default_roster("court")
    assert roster[0] == "plaintiff_lawyer"
    assert set(roster) == {"plaintiff_lawyer", "defense_lawyer", "judge", "clerk"}
    assert await reg.resolve_host("court") == "judge"
    assert await reg.resolve_host("contract") == "mediator"


@pytest.mark.asyncio
async def test_default_roster_unknown_raises(reg):
    from app.core.errors import InvalidParamsError
    with pytest.raises(InvalidParamsError):
        await reg.default_roster("nope")
    with pytest.raises(InvalidParamsError):
        await reg.default_roster("archived_tpl")  # 已停用


def test_whitelist_mapping():
    members = [{"agent_id": "judge"}, "clerk", {"agent_id": "mediator"}, {"role": "x"}]
    assert RegistryService.whitelist(members) == {"judge", "clerk", "mediator"}


# ============================================================
# 加载即校验（三类）
# ============================================================

@pytest.mark.asyncio
async def test_validate_roster_agent_missing():
    bad = [dict(TEMPLATES[0], roster=[{"agent_id": "ghost", "stage": "debate", "order": 1}])]
    with pytest.raises(RegistryError, match="未注册 Agent"):
        await make_service(templates=bad).all_templates()


@pytest.mark.asyncio
async def test_validate_host_must_be_registered():
    bad = [dict(TEMPLATES[0], host_agent_id="ghost")]  # 主持人未注册
    with pytest.raises(RegistryError, match="主持人"):
        await make_service(templates=bad).all_templates()


@pytest.mark.asyncio
async def test_host_allowed_outside_roster():
    # court 种子即为 host=judge 而 roster 只列原被告/书记员——合法（主持人自动并入成员）
    tpl = dict(
        TEMPLATES[1],
        roster=[
            {"agent_id": "plaintiff_lawyer", "stage": "opening", "order": 1},
            {"agent_id": "defense_lawyer", "stage": "debate", "order": 2},
        ],
    )
    tpls = await make_service(templates=[tpl]).all_templates()
    assert tpls[0]["host_agent_id"] == "judge"
    assert "judge" not in [i["agent_id"] for i in tpls[0]["roster"]]


@pytest.mark.asyncio
async def test_validate_court_host_must_be_judge():
    bad = [dict(TEMPLATES[1], host_agent_id="mediator",
                roster=[{"agent_id": "mediator", "stage": "debate", "order": 1}])]
    with pytest.raises(RegistryError, match="court"):
        await make_service(templates=bad).all_templates()


@pytest.mark.asyncio
async def test_refresh_reloads(reg):
    calls = {"n": 0}
    agents = list(AGENTS)

    async def loader():
        calls["n"] += 1
        return list(agents)

    async def tloader():
        return list(TEMPLATES)

    svc = RegistryService(agent_loader=loader, template_loader=tloader)
    await svc.all_agents()
    await svc.all_agents()
    assert calls["n"] == 1  # 命中缓存
    svc.refresh()
    await svc.all_agents()
    assert calls["n"] == 2


# ============================================================
# 只读 API（/templates 不被 /{agent_id} 吞掉）
# ============================================================

@pytest.mark.asyncio
async def test_list_agents_api(client):
    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["data"]["total"] == 10
    filtered = await client.get("/api/agents?is_tool=true")
    assert filtered.json()["data"]["total"] == 2


@pytest.mark.asyncio
async def test_templates_api_not_shadowed(client):
    resp = await client.get("/api/agents/templates")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 2
    court = next(t for t in data["templates"] if t["case_type"] == "court")
    assert court["host_agent_id"] == "judge"
    assert court["roster_summary"][0]["agent_id"] == "plaintiff_lawyer"
    assert court["roster_summary"][0]["name"] == "原告律师"


@pytest.mark.asyncio
async def test_agent_detail_api(client):
    ok = await client.get("/api/agents/judge")
    assert ok.status_code == 200 and ok.json()["data"]["agent_id"] == "judge"
    missing = await client.get("/api/agents/ghost")
    assert missing.status_code == 404 and missing.json()["code"] == 40004
