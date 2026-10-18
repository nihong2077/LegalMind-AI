"""
Agent 注册表 / 案情模板 查询 API（T1.2）

只读、无副作用，全部走统一信封（EnvelopeRouter），JWT 鉴权。
建群向导与「Agent 通讯录」页统一从此处取数，杜绝前端硬编码名单。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Query

from ..core.errors import NotFoundError
from ..core.response import EnvelopeRouter, success
from ..core.security import get_current_user
from ..services.collab.registry import RegistryService, get_registry

router = EnvelopeRouter(prefix="/api/agents", tags=["Agent 注册表"])


async def _auth(_user: dict = Depends(get_current_user)) -> None:
    """只读接口：仅要求登录，无额外权限。"""
    return None


# 注意：静态段 /templates 必须先于 /{agent_id} 注册，否则被路径参数吞掉
@router.get("/templates")
async def list_templates(
    reg: RegistryService = Depends(get_registry),
    _: None = Depends(_auth),
):
    templates = await reg.all_templates()
    cards = []
    for tpl in templates:
        roster_summary = []
        for item in tpl.get("roster") or []:
            agent = await reg.get_agent(str(item.get("agent_id")))
            if agent is not None:
                roster_summary.append(
                    {
                        "agent_id": agent["agent_id"],
                        "name": agent.get("name"),
                        "role_label": agent.get("role_label"),
                        "is_tool": agent.get("is_tool"),
                        "stage": item.get("stage"),
                        "order": item.get("order"),
                    }
                )
        cards.append({**tpl, "roster_summary": roster_summary})
    return success({"templates": cards, "total": len(cards)})


@router.get("")
async def list_agents(
    is_tool: Optional[bool] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=64),
    reg: RegistryService = Depends(get_registry),
    _: None = Depends(_auth),
):
    agents = await reg.all_agents(is_tool=is_tool, q=q)
    return success({"agents": agents, "total": len(agents)})


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    reg: RegistryService = Depends(get_registry),
    _: None = Depends(_auth),
):
    agent = await reg.get_agent(agent_id)
    if agent is None:
        raise NotFoundError(f"Agent 不存在：{agent_id}")
    return success(agent)
