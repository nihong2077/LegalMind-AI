"""生产图全局接线（T1.8 前提 / 集成收口）

把 T1.3–T1.7 一直用「默认桩」编译的 ``get_collab_graph()`` 换成**真实件**：

- **host_advisor**：按模板 ``adapter`` 分派 —— ``court`` → T1.7 法官适配件
  （[templates/court.build_court_host_advisor](templates/court.py)）；其余 → 通用
  [HostSkill.speak_and_decide](host_skill.py)；
- **scheduler**：``court`` → [court_scheduler](templates/court.py)（打散串行、庭审用语中性）；
  其余 → 通用 [SchedulerSkill.decide](scheduler_skill.py)（隐藏排序智能体，D14）；
- **agent_runner**：[make_agent_runner](agent_nodes.py)（T1.5 真实 Skill 映射 + S1 流式；
  注入 [make_web_context](web_decision.py) 的联网前置决策，fail-open）；
- **tool_runner**：[make_tool_runner](tool_nodes.py)（法规/类案检索辐条，fail-open）；
- **decision_recorder**：[audit.record_host_decision](audit.py)（host_decisions 落库，fail-open）；
- **interaction_card**：``court`` → 庭审补证卡片（同步件，分派器包成 async）；
  其余 → 空（保持通用 interrupt payload）；
- **conclude_producer**：``court`` → verdict 判决书气泡；其余 → 无追加；
- **speaker_notice**：[make_speaker_notice](speaker_notice.py)（轮次发言分隔条，
  中性「下面是 X 发言」，隐藏主持人身份，fail-open）。

设计取舍（对齐 A1「代码只做护栏」，不新增任何图固定边）：
- 业务分派**只依据 adapter 判据**（[prompts.is_court_template](prompts.py)），无硬编码业务顺序；
- 分派器在**调用时**按 ``state.case_type`` 查模板（注册表进程级缓存），因此**同一张编译图
  可同时服务所有模板**，无需按模板重建图；
- 所有真实件均可注入（``llm``/``registry``/``store``/``emit``/``verdict_runner``），
  单测可整体替换为假件，不依赖 DB/Redis/LLM；
- 失败降级沿用既有约定：scheduler/conclude/tool 异常由**图节点**捕获兜底（D15③），
  生产装配本身不吞错、不阻断主流程。
"""
from __future__ import annotations

from typing import Any, Optional

from ...core.llm_client import LLMClient
from .agent_nodes import Emitter, make_agent_runner
from .audit import record_host_decision
from .conversation_store import ConversationStore
from .host_skill import HostSkill
from .prompts import is_court_template
from .registry import RegistryService, get_registry
from .scheduler_skill import SchedulerSkill
from .speaker_notice import make_speaker_notice
from .templates.court import (
    VerdictRunner,
    build_court_host_advisor,
    build_court_interaction_card,
    court_scheduler,
    make_court_conclude_producer,
)
from .tool_nodes import make_tool_runner
from .web_decision import make_web_context


async def build_production_injectables(
    *,
    llm: Optional[LLMClient] = None,
    registry: Optional[RegistryService] = None,
    store: Optional[ConversationStore] = None,
    emit: Optional[Emitter] = None,
    verdict_runner: Optional[VerdictRunner] = None,
) -> dict[str, Any]:
    """装配 ``build_collab_graph(...)`` 的真实可注入件（按模板 adapter 分派）。

    Returns:
        可直接展开进 ``build_collab_graph(**injectables, registry=reg)`` 的 dict：
        ``host_advisor / scheduler / agent_runner / tool_runner / decision_recorder /
        interaction_card / conclude_producer``。
    """
    reg = registry or await get_registry()

    host_generic = HostSkill(llm=llm, registry=reg)
    scheduler_generic = SchedulerSkill(llm=llm, registry=reg)
    court_host = build_court_host_advisor(llm=llm, registry=reg)
    court_conclude = make_court_conclude_producer(verdict_runner=verdict_runner)

    async def _is_court(state: dict[str, Any]) -> bool:
        template = await reg.get_template(str(state.get("case_type") or ""))
        return is_court_template(template)

    async def host_advisor(state: dict[str, Any]) -> dict[str, Any]:
        if await _is_court(state):
            return await court_host(state)
        return await host_generic.speak_and_decide(state)

    async def scheduler(state: dict[str, Any], candidates: list[str]) -> dict[str, Any]:
        if await _is_court(state):
            return await court_scheduler(state, candidates)
        return await scheduler_generic.decide(state, candidates)

    async def interaction_card(state: dict[str, Any]) -> dict[str, Any]:
        # 分派器为 async（需查模板）；graph 侧已支持 awaitable interaction_card
        if await _is_court(state):
            return build_court_interaction_card(state) or {}
        return {}

    async def conclude_producer(state: dict[str, Any]) -> list[Any]:
        if await _is_court(state):
            return await court_conclude(state) or []
        return []

    return {
        "host_advisor": host_advisor,
        "scheduler": scheduler,
        "agent_runner": make_agent_runner(
            llm=llm, store=store, registry=reg, emit=emit,
            web=make_web_context(llm=llm, store=store, emit=emit),
        ),
        "tool_runner": make_tool_runner(llm=llm, store=store, emit=emit),
        "decision_recorder": record_host_decision,
        "interaction_card": interaction_card,
        "conclude_producer": conclude_producer,
        "speaker_notice": make_speaker_notice(store=store, emit=emit),
    }
