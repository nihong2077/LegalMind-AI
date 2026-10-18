"""
Agent 注册表与案情模板服务（T1.2）

把 ``agent_registry``（10 个 Agent）与 ``case_roster_templates``（8 个模板）
从 SQL 种子变成**可查询、可校验、可复用**的服务：建群向导、编排器白名单
统一从这里取数，杜绝任何硬编码名单（对齐 A1「代码只做护栏」）。

- 进程内缓存 + 显式 ``refresh()`` 失效；
- **加载即校验**，失败快速暴露（不留到运行期）；
- 供编排器复用的小工具：``default_roster`` / ``resolve_host`` / ``whitelist``
  （D14 后白名单由隐藏的演讲排序智能体 scheduler 消费）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select

from ...core.errors import InvalidParamsError, NotFoundError
from ...core.pg_client import AgentRegistry as AgentRegistryModel
from ...core.pg_client import CaseRosterTemplate, app_session_factory

logger = logging.getLogger(__name__)

# 模板/主持人校验常量（与 05-seed 种子一致）
COURT_TEMPLATE = "court"
COURT_HOST = "judge"

AgentLoader = Callable[[], Awaitable[list[dict[str, Any]]]]
TemplateLoader = Callable[[], Awaitable[list[dict[str, Any]]]]


class RegistryError(RuntimeError):
    """注册表/模板加载校验失败（种子数据不一致，启动/首查即暴露）。"""


def serialize_agent(agent: AgentRegistryModel) -> dict[str, Any]:
    return {
        "agent_id": agent.agent_id,
        "name": agent.name,
        "avatar": agent.avatar,
        "role_label": agent.role_label,
        "description": agent.description,
        "skill_ref": agent.skill_ref,
        "persona": agent.persona,
        "model_pref": agent.model_pref or {},
        "is_tool": agent.is_tool,
        "sort_order": agent.sort_order,
        "enabled": agent.enabled,
    }


def serialize_template(tpl: CaseRosterTemplate) -> dict[str, Any]:
    return {
        "case_type": tpl.case_type,
        "name": tpl.name,
        "icon": tpl.icon,
        "description": tpl.description,
        "host_agent_id": tpl.host_agent_id,
        "roster": list(tpl.roster or []),
        "max_rounds": tpl.max_rounds,
        "opening_enabled": tpl.opening_enabled,
        "minutes_enabled": tpl.minutes_enabled,
        "adapter": tpl.adapter,
        "enabled": tpl.enabled,
    }


async def _load_agents_pg() -> list[dict[str, Any]]:
    async with app_session_factory() as session:
        rows = (await session.execute(select(AgentRegistryModel))).scalars().all()
        return [serialize_agent(a) for a in rows]


async def _load_templates_pg() -> list[dict[str, Any]]:
    async with app_session_factory() as session:
        rows = (await session.execute(select(CaseRosterTemplate))).scalars().all()
        return [serialize_template(t) for t in rows]


def _roster_ids(tpl: dict[str, Any]) -> list[str]:
    return [str(i.get("agent_id")) for i in (tpl.get("roster") or []) if i.get("agent_id")]


class RegistryService:
    """Agent 注册表 + 案情模板的只读服务（进程级单例，可注入假数据做单测）。"""

    def __init__(
        self,
        agent_loader: Optional[AgentLoader] = None,
        template_loader: Optional[TemplateLoader] = None,
    ):
        self._agent_loader = agent_loader or _load_agents_pg
        self._template_loader = template_loader or _load_templates_pg
        self._agents: Optional[dict[str, dict[str, Any]]] = None
        self._templates: Optional[dict[str, dict[str, Any]]] = None
        self._lock = asyncio.Lock()

    # ---------------- 加载与校验 ----------------

    async def _ensure_loaded(self) -> None:
        if self._agents is not None and self._templates is not None:
            return
        async with self._lock:
            if self._agents is not None and self._templates is not None:
                return
            agents = {a["agent_id"]: a for a in await self._agent_loader()}
            templates = {t["case_type"]: t for t in await self._template_loader()}
            self._validate(agents, templates)
            self._agents, self._templates = agents, templates

    @staticmethod
    def _validate(
        agents: dict[str, dict[str, Any]], templates: dict[str, dict[str, Any]]
    ) -> None:
        """加载即校验：① roster 成员必须已注册；② 主持人必须已注册；③ court host=judge。

        注意 ②：不强制「host ∈ roster」——主持人由 `create_conversation` 自动并入
        成员（role=host），因而允许 host 不在 roster 中（与 court 种子一致：
        法官主持庭审，roster 仅列原被告与书记员）。
        """
        for case_type, tpl in templates.items():
            roster = _roster_ids(tpl)
            for agent_id in roster:
                if agent_id not in agents:
                    raise RegistryError(
                        f"模板 {case_type} 的 roster 引用了未注册 Agent：{agent_id}"
                    )
            host = tpl.get("host_agent_id")
            if host not in agents:
                raise RegistryError(f"模板 {case_type} 的主持人 {host} 未注册")
            if case_type == COURT_TEMPLATE and host != COURT_HOST:
                raise RegistryError(f"{COURT_TEMPLATE} 模板的主持人必须为 {COURT_HOST}")

    def refresh(self) -> None:
        """显式失效缓存（种子变更/测试注入后调用）。"""
        self._agents = None
        self._templates = None

    # ---------------- Agent ----------------

    async def get_agent(self, agent_id: str) -> Optional[dict[str, Any]]:
        await self._ensure_loaded()
        return self._agents.get(agent_id) if self._agents else None

    async def all_agents(
        self,
        include_disabled: bool = False,
        is_tool: Optional[bool] = None,
        q: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        await self._ensure_loaded()
        items = list((self._agents or {}).values())
        if not include_disabled:
            items = [a for a in items if a.get("enabled")]
        if is_tool is not None:
            items = [a for a in items if bool(a.get("is_tool")) == is_tool]
        if q:
            needle = q.strip().lower()
            items = [
                a
                for a in items
                if needle in str(a.get("name", "")).lower()
                or needle in str(a.get("role_label", "")).lower()
                or needle in str(a.get("description", "") or "").lower()
            ]
        return sorted(items, key=lambda a: a.get("sort_order", 10_000))

    async def agents_by_ids(self, agent_ids: list[str]) -> list[dict[str, Any]]:
        await self._ensure_loaded()
        return [
            self._agents[aid] for aid in agent_ids if aid in (self._agents or {})
        ]

    async def tool_agents(self) -> list[dict[str, Any]]:
        return await self.all_agents(is_tool=True)

    # ---------------- 模板 ----------------

    async def get_template(self, case_type: str) -> Optional[dict[str, Any]]:
        await self._ensure_loaded()
        return (self._templates or {}).get(case_type)

    async def all_templates(self) -> list[dict[str, Any]]:
        await self._ensure_loaded()
        items = [t for t in (self._templates or {}).values() if t.get("enabled")]
        return sorted(items, key=lambda t: t.get("case_type", ""))

    # ---------------- 编排器复用工具 ----------------

    async def default_roster(self, case_type: str) -> list[str]:
        """模板默认发言名单（opening 先于 debate，其余按 order）。"""
        tpl = await self.get_template(case_type)
        if tpl is None or not tpl.get("enabled"):
            raise InvalidParamsError(f"未知或已停用的案情模板：{case_type}")
        roster = sorted(
            tpl.get("roster") or [],
            key=lambda x: (x.get("stage") != "opening", x.get("order", 99)),
        )
        return [str(i["agent_id"]) for i in roster if i.get("agent_id")]

    async def resolve_host(self, case_type: str) -> Optional[str]:
        tpl = await self.get_template(case_type)
        return tpl.get("host_agent_id") if tpl else None

    @staticmethod
    def whitelist(members: list[Any]) -> set[str]:
        """把群成员映射成 scheduler 可 goto 的白名单集合（D14）。

        ``members`` 可为 ``[{"agent_id": ...}]`` 或 ``["agent_id", ...]`` 的混合。
        """
        out: set[str] = set()
        for m in members:
            if isinstance(m, str):
                out.add(m)
            elif isinstance(m, dict) and m.get("agent_id"):
                out.add(str(m["agent_id"]))
        return out


def require_agent(agent: Optional[dict[str, Any]], agent_id: str) -> dict[str, Any]:
    """未知/停用 Agent 统一抛 40004（加人、建群校验共用）。"""
    if agent is None or not agent.get("enabled"):
        raise InvalidParamsError(f"Agent 不存在或已停用：{agent_id}")
    return agent


# 进程级单例（路由依赖注入；测试可 dependency_overrides 或自建实例）
registry = RegistryService()


async def get_registry() -> RegistryService:
    return registry
