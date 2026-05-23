"""
LangGraph 多轮辩论工作流。

流程（增强版 — 融合 IRAC 框架 + 主动式法官）：
  收集案情 → KFE提取 → 证据检查(不足→中断) → 法律检索
  → 法官开庭(归纳焦点) → 原告陈述 → 被告陈述
  → 法庭调查(法官追问) → 辩论循环(原告反驳→被告反驳→法官点评→收敛判定)
  → 法官裁决(IRAC) → 判决书生成 → 白话化翻译(可选) → 汇总
"""

import json
import logging
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from ..agents.judge_skill import JudgeSkill
from ..agents.plaintiff_skill import PlaintiffSkill
from ..agents.defendant_skill import DefendantSkill
from ..agents.judgment_report_skill import JudgmentReportSkill
from ..legal.kfe_extractor import extract_kfe
from ..legal.convergence import should_converge
from ..legal.rag_retriever import format_retrieval_context, retrieve_legal_knowledge
from ..legal.aux_nodes import check_evidence_sufficiency, translate_to_plain_language

logger = logging.getLogger(__name__)

MODEL_HEAVY = "deepseek-v4-pro"
MODEL_FAST = "deepseek-flash"
MAX_DEBATE_ROUNDS = 3


class DebateWorkflowState(TypedDict):
    messages: Annotated[list, add_messages]
    case_description: str
    evidence_summary: str
    task_type: str

    kfe: dict
    evidence_sufficient: bool
    interrupt_reason: str

    focus_points: str
    plaintiff_opening: str
    defendant_opening: str

    # 法庭调查阶段
    court_investigation: str

    current_round: int
    plaintiff_args: list[str]
    defendant_args: list[str]
    judge_comments: list[str]

    converged: bool
    convergence_reason: str

    verdict: str
    judgment_report: str
    plain_language_version: str

    legal_knowledge: str
    final_result: str

    structured_summary: dict


async def extract_kfe_node(state: DebateWorkflowState, llm: BaseChatModel) -> dict:
    """节点1: 提取关键法律事实"""
    existing = state.get("kfe", {})
    if existing and existing.get("breach_type") != "不明确":
        logger.info("KFE 已预填，跳过提取")
        return {}

    logger.info("提取 KFE...")
    kfe = await extract_kfe(
        case_description=state["case_description"],
        evidence_summary=state.get("evidence_summary", ""),
        llm=llm,
    )
    return {"kfe": kfe}


async def check_evidence_node(state: DebateWorkflowState, _llm: BaseChatModel) -> dict:
    """节点2: 检查证据充分性"""
    sufficient, reason = check_evidence_sufficiency(state["kfe"])
    return {
        "evidence_sufficient": sufficient,
        "interrupt_reason": reason if not sufficient else "",
    }


async def retrieve_knowledge_node(state: DebateWorkflowState, llm: BaseChatModel) -> dict:
    """节点3: RAG 检索相关法律知识"""
    logger.info("检索法律知识...")
    results = await retrieve_legal_knowledge(
        query=state["case_description"],
        llm=llm,
        top_k=5,
        use_hyde=True,
    )
    context = format_retrieval_context(results)
    return {"legal_knowledge": context}


async def judge_opening_node(state: DebateWorkflowState, llm: BaseChatModel) -> dict:
    """节点4: 法官开庭，归纳争议焦点（增强版：注入 KFE + 法律知识）"""
    logger.info("法官开庭...")
    judge = JudgeSkill(llm)
    opening = await judge.preside_opening(
        plaintiff_claim=state["case_description"],
        defendant_response=state.get("evidence_summary", ""),
        kfe=state.get("kfe"),
        legal_knowledge=state.get("legal_knowledge", ""),
    )
    return {"focus_points": opening, "messages": [AIMessage(content=f"【法官开庭】\n{opening}")]}


async def plaintiff_opening_node(state: DebateWorkflowState, llm: BaseChatModel) -> dict:
    """节点5: 原告律师开庭陈述（增强版：注入法律知识）"""
    logger.info("原告律师陈述...")
    lawyer = PlaintiffSkill(llm)

    opening = await lawyer.opening_statement(
        case_facts=state["case_description"],
        focus_points=state.get("focus_points", ""),
        legal_knowledge=state.get("legal_knowledge", ""),
    )
    return {
        "plaintiff_opening": opening,
        "plaintiff_args": [opening],
        "messages": [AIMessage(content=f"【原告律师陈述】\n{opening}")],
    }


async def defendant_opening_node(state: DebateWorkflowState, llm: BaseChatModel) -> dict:
    """节点6: 被告律师开庭陈述（增强版：注入法律知识）"""
    logger.info("被告律师陈述...")
    lawyer = DefendantSkill(llm)

    opening = await lawyer.opening_statement(
        case_facts=state["case_description"],
        plaintiff_claim=state.get("plaintiff_opening", state["case_description"]),
        focus_points=state.get("focus_points", ""),
        legal_knowledge=state.get("legal_knowledge", ""),
    )
    return {
        "defendant_opening": opening,
        "defendant_args": [opening],
        "messages": [AIMessage(content=f"【被告律师陈述】\n{opening}")],
    }


async def court_investigation_node(state: DebateWorkflowState, llm: BaseChatModel) -> dict:
    """节点7: 法庭调查 — 法官主动追问关键事实"""
    logger.info("法庭调查...")
    judge = JudgeSkill(llm)
    investigation = await judge.court_investigation(
        focus_points=state.get("focus_points", ""),
        plaintiff_opening=state.get("plaintiff_opening", ""),
        defendant_opening=state.get("defendant_opening", ""),
        kfe=state.get("kfe"),
    )
    return {
        "court_investigation": investigation,
        "messages": [AIMessage(content=f"【法庭调查】\n{investigation}")],
    }


async def plaintiff_rebuttal_node(state: DebateWorkflowState, llm: BaseChatModel) -> dict:
    """节点8: 原告律师反驳（增强版：辩论历史+法官点评+法律知识）"""
    round_num = state.get("current_round", 0) + 1
    logger.info("原告反驳 第%d轮...", round_num)

    lawyer = PlaintiffSkill(llm)
    last_defendant = state["defendant_args"][-1] if state["defendant_args"] else ""

    # 将法庭调查的问题融入反驳上下文
    investigation = state.get("court_investigation", "")
    case_facts = state["case_description"]
    if investigation:
        case_facts = f"{case_facts}\n\n法庭调查要点：{investigation[:500]}"

    # 获取最新法官点评
    judge_comments = state.get("judge_comments", [])
    last_judge_comment = judge_comments[-1] if judge_comments else ""

    rebuttal = await lawyer.rebuttal(
        defendant_arg=last_defendant,
        case_facts=case_facts,
        round_num=round_num,
        plaintiff_args=state.get("plaintiff_args", []),
        defendant_args=state.get("defendant_args", []),
        judge_comment=last_judge_comment,
        legal_knowledge=state.get("legal_knowledge", ""),
    )

    plaintiff_args = list(state.get("plaintiff_args", []))
    plaintiff_args.append(rebuttal)

    return {
        "current_round": round_num,
        "plaintiff_args": plaintiff_args,
        "messages": [AIMessage(content=f"【原告律师反驳 第{round_num}轮】\n{rebuttal}")],
    }


async def defendant_rebuttal_node(state: DebateWorkflowState, llm: BaseChatModel) -> dict:
    """节点9: 被告律师反驳（增强版：辩论历史+法官点评+法律知识）"""
    round_num = state.get("current_round", 1)
    logger.info("被告反驳 第%d轮...", round_num)

    lawyer = DefendantSkill(llm)
    last_plaintiff = state["plaintiff_args"][-1] if state["plaintiff_args"] else ""

    # 将法庭调查的问题融入反驳上下文
    investigation = state.get("court_investigation", "")
    case_facts = state["case_description"]
    if investigation:
        case_facts = f"{case_facts}\n\n法庭调查要点：{investigation[:500]}"

    # 获取最新法官点评
    judge_comments = state.get("judge_comments", [])
    last_judge_comment = judge_comments[-1] if judge_comments else ""

    rebuttal = await lawyer.rebuttal(
        plaintiff_arg=last_plaintiff,
        case_facts=case_facts,
        round_num=round_num,
        plaintiff_args=state.get("plaintiff_args", []),
        defendant_args=state.get("defendant_args", []),
        judge_comment=last_judge_comment,
        legal_knowledge=state.get("legal_knowledge", ""),
    )

    defendant_args = list(state.get("defendant_args", []))
    defendant_args.append(rebuttal)

    return {
        "defendant_args": defendant_args,
        "messages": [AIMessage(content=f"【被告律师反驳 第{round_num}轮】\n{rebuttal}")],
    }


async def judge_comment_node(state: DebateWorkflowState, llm: BaseChatModel) -> dict:
    """节点10: 法官点评本轮辩论（增强版：传递历史点评 + 法律知识）"""
    round_num = state.get("current_round", 1)
    logger.info("法官点评 第%d轮...", round_num)

    judge = JudgeSkill(llm)
    comment = await judge.evaluate_round(
        plaintiff_arg=state["plaintiff_args"][-1] if state["plaintiff_args"] else "",
        defendant_arg=state["defendant_args"][-1] if state["defendant_args"] else "",
        focus_points=state.get("focus_points", ""),
        round_num=round_num,
        judge_comments_history=state.get("judge_comments", []),
        legal_knowledge=state.get("legal_knowledge", ""),
    )

    judge_comments = list(state.get("judge_comments", []))
    judge_comments.append(comment)

    return {
        "judge_comments": judge_comments,
        "messages": [AIMessage(content=f"【法官点评 第{round_num}轮】\n{comment}")],
    }


async def convergence_check_node(state: DebateWorkflowState, _llm: BaseChatModel) -> dict:
    """节点11: 收敛判定"""
    round_num = state.get("current_round", 1)

    last_p = state["plaintiff_args"][-1] if state["plaintiff_args"] else ""
    last_d = state["defendant_args"][-1] if state["defendant_args"] else ""

    from ..legal.convergence import compute_semantic_similarity
    similarity = compute_semantic_similarity(last_p, last_d)

    kfe_consistent = True
    mismatches: list[str] = []
    kfe = state.get("kfe", {})
    if kfe:
        from ..legal.kfe_extractor import compare_kfe
        plaintiff_args = state.get("plaintiff_args", [])
        defendant_args = state.get("defendant_args", [])
        if plaintiff_args and defendant_args:
            from ..legal.kfe_extractor import extract_kfe
            plaintiff_kfe = extract_kfe(" ".join(str(a) for a in plaintiff_args[-2:]))
            defendant_kfe = extract_kfe(" ".join(str(a) for a in defendant_args[-2:]))
            comparison = compare_kfe(plaintiff_kfe, defendant_kfe)
        else:
            comparison = compare_kfe(kfe, kfe)
        kfe_consistent = comparison["is_consistent"]
        mismatches = comparison["mismatches"]

    converged, reason = should_converge(
        semantic_similarity=similarity,
        kfe_consistency=kfe_consistent,
        mismatches=mismatches,
        round_num=round_num,
        max_rounds=MAX_DEBATE_ROUNDS,
    )

    logger.info("收敛判定: round=%d, sim=%.3f, converged=%s, reason=%s", round_num, similarity, converged, reason)
    return {"converged": converged, "convergence_reason": reason}


async def judge_verdict_node(state: DebateWorkflowState, llm: BaseChatModel) -> dict:
    """节点12: 法官最终裁决（增强版：IRAC 框架 + 法条注入）"""
    logger.info("法官作出最终裁决...")
    judge = JudgeSkill(llm)

    verdict = await judge.render_verdict(
        plaintiff_args=state.get("plaintiff_args", []),
        defendant_args=state.get("defendant_args", []),
        kfe=state.get("kfe", {}),
        focus_points=state.get("focus_points", ""),
        judge_comments=state.get("judge_comments", []),
        legal_knowledge=state.get("legal_knowledge", ""),
    )

    return {
        "verdict": verdict,
        "messages": [AIMessage(content=f"【法官裁决】\n{verdict}")],
    }


async def judgment_report_node(state: DebateWorkflowState, llm: BaseChatModel) -> dict:
    """节点13: 生成判决书"""
    logger.info("生成判决书...")
    reporter = JudgmentReportSkill(llm)

    case_info = {
        "case_type": state.get("kfe", {}).get("breach_category", "合同纠纷"),
        "plaintiff_name": "原告",
        "defendant_name": "被告",
    }

    report = await reporter.generate_judgment(
        verdict=state.get("verdict", ""),
        case_info=case_info,
        plaintiff_args=state.get("plaintiff_args", []),
        defendant_args=state.get("defendant_args", []),
    )

    return {
        "judgment_report": report,
        "messages": [AIMessage(content=f"【判决书】\n{report}")],
    }


async def plain_language_node(state: DebateWorkflowState, llm: BaseChatModel) -> dict:
    """节点14: 白话化翻译"""
    logger.info("生成白话版本...")
    source = state.get("judgment_report") or state.get("verdict", "")
    if not source:
        return {"plain_language_version": ""}

    plain = await translate_to_plain_language(source, llm)
    return {
        "plain_language_version": plain,
        "messages": [AIMessage(content=f"【通俗版】\n{plain}")],
    }


async def finalize_node(state: DebateWorkflowState, llm: BaseChatModel) -> dict:
    """节点15: 汇总最终结果 + 用v4-flash生成结构化分析报告"""
    parts = []

    if state.get("verdict"):
        parts.append(f"## 法官裁决\n\n{state['verdict']}")

    if state.get("judgment_report"):
        parts.append(f"## 判决书\n\n{state['judgment_report']}")

    if state.get("plain_language_version"):
        parts.append(f"## 通俗版\n\n{state['plain_language_version']}")

    if state.get("convergence_reason"):
        parts.append(f"\n> 辩论结束原因：{state['convergence_reason']}")

    final = "\n\n---\n\n".join(parts) if parts else "未能生成结果"

    summary_prompt = f"""基于以下庭审辩论完整记录，生成结构化分析报告（严格JSON格式）：

【案情描述】
{state.get('case_description', '')[:2000]}

【关键法律事实KFE】
{json.dumps(state.get('kfe', {}), ensure_ascii=False, indent=2)[:1500]}

【争议焦点】
{state.get('focus_points', '')[:1000]}

【法庭调查】
{state.get('court_investigation', '')[:500]}

【原告主要论点】
{"；".join(state.get('plaintiff_args', [])[-3:])[:1500]}

【被告主要论点】
{"；".join(state.get('defendant_args', [])[-3:])[:1500]}

【法官裁决】
{state.get('verdict', '')[:1000]}

请输出以下JSON结构（不要输出其他内容）：
{{
    "case_type": "案件类型",
    "focus_points": ["争议焦点1", "争议焦点2"],
    "kfe_items": [
        {{"label": "要素名", "value": "认定结论", "status": "verified/unverified/pending"}}
    ],
    "evidence_analysis": [
        {{"name": "证据名称", "type": "pdf/image/text", "relevance": "高/中/低", "conclusion": "证据效力认定"}}
    ],
    "law_articles": [
        {{"title": "法条全称", "source": "法律名称", "excerpt": "核心条文摘要", "relevance": "直接相关/间接相关"}}
    ],
    "report_sections": {{
        "case_analysis": ["1.案件基本事实", "2.争议焦点归纳"],
        "fact_finding": ["1.关键事实认定1", "2.关键事实认定2"],
        "legal_application": ["1.法律适用分析1", "2.法律适用分析2"],
        "conclusion": ["1.裁判结论", "2.理由与依据"]
    }},
    "mediation_suggestion": {{
        "draft": "调解方案草案要点",
        "enforcement": "执行保障措施建议"
    }},
    "confidence_score": 85,
    "can_sign": "可签/有条件可签/不建议签"
}}"""

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        response = await llm.ainvoke([
            SystemMessage(content="你是资深法律文书分析师。只输出JSON，不要任何markdown标记或解释。"),
            HumanMessage(content=summary_prompt),
        ])
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        structured = json.loads(text)
        logger.info("结构化报告生成成功，置信度=%s", structured.get("confidence_score"))
    except Exception as e:
        logger.warning("结构化报告生成失败，使用默认结构: %s", e)
        kfe_raw = state.get("kfe", {})
        kfe_list = []
        for k, v in kfe_raw.items():
            if isinstance(v, dict):
                for sk, sv in v.items():
                    kfe_list.append({"label": f"{k}-{sk}", "value": str(sv), "status": "verified"})
            else:
                kfe_list.append({"label": k, "value": str(v), "status": "verified"})

        structured = {
            "case_type": kfe_raw.get("breach_category", "待定"),
            "focus_points": state.get("focus_points", "").split("；")[:3],
            "kfe_items": kfe_list or [{"label": "待提取", "value": "暂无数据", "status": "pending"}],
            "evidence_analysis": [],
            "law_articles": [],
            "report_sections": {
                "case_analysis": ["案件基本事实已归纳"],
                "fact_finding": ["关键事实正在认定"],
                "legal_application": ["法律适用分析中"],
                "conclusion": [state.get("verdict", "")[:50] or "等待裁决"],
            },
            "mediation_suggestion": {"draft": "", "enforcement": ""},
            "confidence_score": 70,
            "can_sign": "待评估",
        }

    return {"final_result": final, "structured_summary": structured}


def route_after_evidence(state: DebateWorkflowState) -> Literal["retrieve_knowledge", "__end__"]:
    """证据检查后的路由"""
    if state.get("evidence_sufficient", True):
        return "retrieve_knowledge"
    return "__end__"


def route_after_convergence(state: DebateWorkflowState) -> Literal["plaintiff_rebuttal", "judge_verdict"]:
    """收敛判定后的路由"""
    if state.get("converged", False):
        return "judge_verdict"
    return "plaintiff_rebuttal"


def route_after_verdict(state: DebateWorkflowState) -> Literal["judgment_report", "finalize"]:
    """裁决后的路由：是否需要生成判决书"""
    task_type = state.get("task_type", "debate")
    if task_type in ("debate", "full"):
        return "judgment_report"
    return "finalize"


def build_debate_workflow(
    heavy_llm: BaseChatModel,
    fast_llm: BaseChatModel | None = None,
) -> StateGraph:
    """
    构建多轮辩论工作流（增强版）。

    模型分配：
    - KFE提取、法官开庭/调查/点评/裁决、律师陈述/反驳 → heavy_llm (V4 Pro)
    - 法律检索、白话翻译、结构化报告 → fast_llm (Flash)
    """
    _fast = fast_llm or heavy_llm

    graph = StateGraph(DebateWorkflowState)

    async def _extract_kfe(state: DebateWorkflowState) -> dict:
        return await extract_kfe_node(state, heavy_llm)

    async def _check_evidence(state: DebateWorkflowState) -> dict:
        return await check_evidence_node(state, heavy_llm)

    async def _retrieve_knowledge(state: DebateWorkflowState) -> dict:
        return await retrieve_knowledge_node(state, _fast)

    async def _judge_opening(state: DebateWorkflowState) -> dict:
        return await judge_opening_node(state, heavy_llm)

    async def _plaintiff_opening(state: DebateWorkflowState) -> dict:
        return await plaintiff_opening_node(state, heavy_llm)

    async def _defendant_opening(state: DebateWorkflowState) -> dict:
        return await defendant_opening_node(state, heavy_llm)

    async def _court_investigation(state: DebateWorkflowState) -> dict:
        return await court_investigation_node(state, heavy_llm)

    async def _plaintiff_rebuttal(state: DebateWorkflowState) -> dict:
        return await plaintiff_rebuttal_node(state, heavy_llm)

    async def _defendant_rebuttal(state: DebateWorkflowState) -> dict:
        return await defendant_rebuttal_node(state, heavy_llm)

    async def _judge_comment(state: DebateWorkflowState) -> dict:
        return await judge_comment_node(state, heavy_llm)

    async def _convergence_check(state: DebateWorkflowState) -> dict:
        return await convergence_check_node(state, heavy_llm)

    async def _judge_verdict(state: DebateWorkflowState) -> dict:
        return await judge_verdict_node(state, heavy_llm)

    async def _judgment_report(state: DebateWorkflowState) -> dict:
        return await judgment_report_node(state, heavy_llm)

    async def _plain_language(state: DebateWorkflowState) -> dict:
        return await plain_language_node(state, _fast)

    async def _finalize(state: DebateWorkflowState) -> dict:
        return await finalize_node(state, _fast)

    # 注册节点
    graph.add_node("extract_kfe", _extract_kfe)
    graph.add_node("check_evidence", _check_evidence)
    graph.add_node("retrieve_knowledge", _retrieve_knowledge)
    graph.add_node("judge_opening", _judge_opening)
    graph.add_node("plaintiff_opening", _plaintiff_opening)
    graph.add_node("defendant_opening", _defendant_opening)
    graph.add_node("court_investigation", _court_investigation)
    graph.add_node("plaintiff_rebuttal", _plaintiff_rebuttal)
    graph.add_node("defendant_rebuttal", _defendant_rebuttal)
    graph.add_node("judge_comment", _judge_comment)
    graph.add_node("convergence_check", _convergence_check)
    graph.add_node("judge_verdict", _judge_verdict)
    graph.add_node("judgment_report", _judgment_report)
    graph.add_node("plain_language", _plain_language)
    graph.add_node("finalize", _finalize)

    # 设置入口
    graph.set_entry_point("extract_kfe")

    # 定义边
    graph.add_edge("extract_kfe", "check_evidence")
    graph.add_conditional_edges("check_evidence", route_after_evidence, {
        "retrieve_knowledge": "retrieve_knowledge",
        "__end__": END,
    })

    graph.add_edge("retrieve_knowledge", "judge_opening")
    graph.add_edge("judge_opening", "plaintiff_opening")
    graph.add_edge("plaintiff_opening", "defendant_opening")
    # 新增：被告陈述后进入法庭调查
    graph.add_edge("defendant_opening", "court_investigation")
    # 法庭调查后进入辩论循环
    graph.add_edge("court_investigation", "plaintiff_rebuttal")
    graph.add_edge("plaintiff_rebuttal", "defendant_rebuttal")
    graph.add_edge("defendant_rebuttal", "judge_comment")
    graph.add_edge("judge_comment", "convergence_check")

    graph.add_conditional_edges("convergence_check", route_after_convergence, {
        "plaintiff_rebuttal": "plaintiff_rebuttal",
        "judge_verdict": "judge_verdict",
    })

    graph.add_conditional_edges("judge_verdict", route_after_verdict, {
        "judgment_report": "judgment_report",
        "finalize": "finalize",
    })

    graph.add_edge("judgment_report", "plain_language")
    graph.add_edge("plain_language", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()
