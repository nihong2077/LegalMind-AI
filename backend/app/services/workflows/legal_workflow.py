import logging
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langchain_core.language_models import BaseChatModel

from ..agents.legal_analyzer import LegalAnalyzer
from ..agents.contract_reviewer import ContractReviewer
from ..agents.regulatory_researcher import RegulatoryResearcher

logger = logging.getLogger(__name__)

MODEL_HEAVY = "deepseek-v4-pro"
MODEL_FAST = "deepseek-flash"


class LegalWorkflowState(TypedDict):
    messages: Annotated[list, add_messages]
    query: str
    context: str
    analysis_result: str
    review_result: str
    research_result: str
    final_result: str
    task_type: str


async def analyze_node(state: LegalWorkflowState, llm: BaseChatModel) -> dict:
    analyzer = LegalAnalyzer(llm)
    result = await analyzer.analyze(state["query"], state.get("context", ""))
    return {"analysis_result": result}


async def review_node(state: LegalWorkflowState, llm: BaseChatModel) -> dict:
    reviewer = ContractReviewer(llm)
    result = await reviewer.review(state.get("context", state["query"]))
    return {"review_result": result}


async def research_node(state: LegalWorkflowState, llm: BaseChatModel) -> dict:
    researcher = RegulatoryResearcher(llm)
    result = await researcher.research(state["query"])
    return {"research_result": result}


async def synthesize_node(state: LegalWorkflowState, llm: BaseChatModel) -> dict:
    parts = []
    if state.get("analysis_result"):
        parts.append(f"【案件分析】\n{state['analysis_result']}")
    if state.get("review_result"):
        parts.append(f"【合同审查】\n{state['review_result']}")
    if state.get("research_result"):
        parts.append(f"【法律检索】\n{state['research_result']}")

    final = "\n\n---\n\n".join(parts) if parts else "未能生成分析结果"
    return {"final_result": final}


def route_by_task_type(state: LegalWorkflowState) -> list[str]:
    task_type = state.get("task_type", "analyze")
    routes = []
    if task_type in ("analyze", "full"):
        routes.append("analyze")
    if task_type in ("review", "full"):
        routes.append("review")
    if task_type in ("research", "full"):
        routes.append("research")
    return routes if routes else ["analyze"]


def build_legal_workflow(
    heavy_llm: BaseChatModel,
    fast_llm: BaseChatModel | None = None,
) -> StateGraph:
    """
    构建法律工作流图。

    模型分配策略：
    - analyze / review → heavy_llm (deepseek-v4-pro)：大型分析任务
    - research → fast_llm (deepseek-flash)：快速检索任务
    - synthesize → fast_llm：汇总任务较轻
    """
    _fast = fast_llm or heavy_llm

    graph = StateGraph(LegalWorkflowState)

    async def _analyze(state: LegalWorkflowState) -> dict:
        return await analyze_node(state, heavy_llm)

    async def _review(state: LegalWorkflowState) -> dict:
        return await review_node(state, heavy_llm)

    async def _research(state: LegalWorkflowState) -> dict:
        return await research_node(state, _fast)

    async def _synthesize(state: LegalWorkflowState) -> dict:
        return await synthesize_node(state, _fast)

    graph.add_node("analyze", _analyze)
    graph.add_node("review", _review)
    graph.add_node("research", _research)
    graph.add_node("synthesize", _synthesize)

    graph.set_conditional_entry_point(
        route_by_task_type,
        {
            "analyze": "analyze",
            "review": "review",
            "research": "research",
        },
    )

    graph.add_edge("analyze", "synthesize")
    graph.add_edge("review", "synthesize")
    graph.add_edge("research", "synthesize")
    graph.add_edge("synthesize", END)

    return graph.compile()
