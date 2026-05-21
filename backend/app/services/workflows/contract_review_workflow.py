"""
合同审查工作流 — 基于 contract-copilot 三层四步框架

流程: classify → scan_risks → generate_report → finalize
"""
import json
import logging
from typing import TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from ..agents.contract_review_skill import ContractReviewSkill

logger = logging.getLogger(__name__)


class ContractReviewState(TypedDict):
    contract_text: str
    user_position: str
    review_stance: str
    classification: dict
    risks: dict
    report: str
    summary: dict
    final_result: str
    structured_review: dict


async def classify_node(state: ContractReviewState, llm: BaseChatModel) -> dict:
    logger.info("条款提取与合同分类中...")
    skill = ContractReviewSkill(llm)
    classification = await skill.extract_and_classify(state["contract_text"])
    return {"classification": classification}


async def scan_risks_node(state: ContractReviewState, llm: BaseChatModel) -> dict:
    logger.info("风险扫描与漏洞检测中...")
    skill = ContractReviewSkill(llm)
    risks = await skill.scan_risks(
        contract_text=state["contract_text"],
        user_position=state.get("user_position", "乙方"),
        review_stance=state.get("review_stance", "常规"),
        classification=state.get("classification"),
    )
    return {"risks": risks}


async def generate_report_node(state: ContractReviewState, llm: BaseChatModel) -> dict:
    logger.info("生成审查报告...")
    skill = ContractReviewSkill(llm)
    report = await skill.generate_report(
        contract_text=state["contract_text"],
        classification=state.get("classification", {}),
        risks=state.get("risks", {}),
        user_position=state.get("user_position", "乙方"),
        review_stance=state.get("review_stance", "常规"),
    )

    classification = state.get("classification", {})
    risks = state.get("risks", {})
    all_issues = risks.get("meso_issues", []) + risks.get("micro_issues", []) + risks.get("loopholes", [])
    p0_count = len([r for r in all_issues if r.get("risk_level") == "P0"])
    p1_count = len([r for r in all_issues if r.get("risk_level") == "P1"])
    p2_count = len([r for r in all_issues if r.get("risk_level") == "P2"])

    can_sign = "可签"
    if "不建议签" in report:
        can_sign = "不建议签"
    elif "有条件可签" in report:
        can_sign = "有条件可签"

    summary = {
        "contract_type": classification.get("contract_type", "未识别"),
        "can_sign": can_sign,
        "p0_count": p0_count,
        "p1_count": p1_count,
        "p2_count": p2_count,
        "total_risks": p0_count + p1_count + p2_count,
        "clause_count": classification.get("clause_count", 0),
        "readability_score": classification.get("readability", {}).get("readability_score", 0),
    }

    return {"report": report, "summary": summary}


async def finalize_node(state: ContractReviewState, fast_llm: BaseChatModel) -> dict:
    """节点4: 汇总 + 用v4-flash生成完整结构化审查数据供前端渲染"""
    summary = state.get("summary", {})
    classification = state.get("classification", {}) or {}
    risks = state.get("risks", {}) or {}

    clauses_raw = classification.get("auto_clauses", [])
    readability = classification.get("readability", {})

    meso_issues = risks.get("meso_issues", [])
    micro_issues = risks.get("micro_issues", [])
    loopholes = risks.get("loopholes", [])
    missing_clauses = risks.get("missing_clauses", [])

    prompt = f"""基于以下合同审查结果，生成前端可用的结构化JSON（严格输出JSON，不要markdown标记）：

【合同基本信息】
类型：{summary.get('contract_type', '未知')}
条款数：{summary.get('clause_count', 0)}
可读性评分：{readability.get('readability_score', 0)}/100
模糊表述：{readability.get('vague_count', 0)}处

【风险统计】
P0严重：{summary.get('p0_count', 0)}项 | P1重要：{summary.get('p1_count', 0)}项 | P2建议：{summary.get('p2_count', 0)}项
结论：{summary.get('can_sign', '待评估')}

【提取的条款】({len(clauses_raw)}条)
{json.dumps([{'title': c.get('title',''), 'content': c.get('content','')[:200]} for c in clauses_raw[:12]], ensure_ascii=False)[:2000]}

【中观层问题】({len(meso_issues)}条)
{json.dumps(meso_issues[:6], ensure_ascii=False)[:2000] if meso_issues else '无'}

【微观层问题】({len(micro_issues)}条)
{json.dumps(micro_issues[:6], ensure_ascii=False)[:2000] if micro_issues else '无'}

【漏洞检测】({len(loopholes)}条)
{json.dumps(loopholes[:5], ensure_ascii=False)[:1500] if loopholes else '无'}

【缺失条款】
{json.dumps(missing_clauses[:8], ensure_ascii=False) if missing_clauses else '无'}

请输出以下JSON：
{{
    "case_name": "根据合同类型自动生成简短名称",
    "risk_level_label": "低/中/中高/高",
    "version": "v1.0",
    "review_time": "当前时间",

    "clause_tree": [
        {{"id": "basic", "label": "基本信息", "status": "pass/warning/danger/info", "risk_count": 0}},
        {{"id": "payment", "label": "付款条款", "status": "warning", "risk_count": 1}},
        {{"id": "breach", "label": "违约责任", "status": "danger", "risk_count": 1}},
        {{"id": "dispute", "label": "争议解决", "status": "pass", "risk_count": 0}},
        {{"id": "personal", "label": "个人信息", "status": "info", "risk_count": 0}},
        {{"id": "attachment", "label": "附件", "status": "pass", "risk_count": 0}}
    ],

    "clauses_display": [
        {{
            "title": "第七条 违约责任",
            "content": "条款内容摘要...",
            "status": "danger",
            "tags": ["违约过高", "模糊程度"],
            "suggestion": "修改建议...",
            "location": "第七条 7.1"
        }}
    ],

    "risk_list": [
        {{
            "level": "高风险/P0",
            "title": "违约金过高",
            "description": "问题描述",
            "location": "第七条 7.1",
            "legal_basis": "法律依据",
            "suggestion": "整改建议"
        }}
    ],

    "revision_list": [
        {{
            "level": "中风险/P1",
            "title": "逾期比例过高",
            "description": "问题描述",
            "original_text": "原文",
            "suggested_text": "建议文本",
            "location": "第六条 6.2"
        }}
    ],

    "conclusion": {{
        "overall_assessment": "整体评价",
        "key_findings": ["发现1", "发现2"],
        "must_fix_before_sign": ["必须修复项"],
        "negotiation_priority": ["谈判优先级"]
    }},

    "report_sections": {{
        "summary": ["合同摘要要点1", "合同摘要要点2"],
        "clause_details": ["条款详情1", "条款详情2"],
        "risk_summary": ["风险汇总1", "风险汇总2"],
        "revision_summary": ["修订汇总1", "修订汇总2"],
        "conclusion": ["结论1", "结论2"]
    }},

    "stats": {{
        "total_clauses": {summary.get('clause_count', 0)},
        "high_risk": {summary.get('p0_count', 0)},
        "medium_risk": {summary.get('p1_count', 0)},
        "low_risk": {summary.get('p2_count', 0)},
        "passed": 0,
        "completion_rate": 83
    }},
    "can_sign": "{summary.get('can_sign', '待评估')}"
}}"""

    try:
        response = await fast_llm.ainvoke([
            SystemMessage(content="你是资深合同审查分析师。只输出严格JSON，不要任何markdown或解释。"),
            HumanMessage(content=prompt),
        ])
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        structured = json.loads(text)

        stats = structured.get("stats", {})
        passed = stats.get("total_clauses", 0) - stats.get("high_risk", 0) - stats.get("medium_risk", 0) - stats.get("low_risk", 0)
        stats["passed"] = max(0, passed)
        completion = min(100, int((passed / max(stats.get("total_clauses", 1), 1)) * 100))
        stats["completion_rate"] = completion

        logger.info("结构化审查报告生成成功, 风险等级=%s, 完成度=%d%%", structured.get("risk_level_label"), completion)
    except Exception as e:
        logger.warning("结构化报告生成失败: %s", e)
        structured = {
            "case_name": f"{summary.get('contract_type', '合同')}审查",
            "risk_level_label": "中高" if summary.get("p0_count", 0) > 0 else "中",
            "version": "v1.0",
            "review_time": "",
            "clause_tree": [],
            "clauses_display": [],
            "risk_list": [],
            "revision_list": [],
            "conclusion": {},
            "report_sections": {},
            "stats": {
                "total_clauses": summary.get("clause_count", 0),
                "high_risk": summary.get("p0_count", 0),
                "medium_risk": summary.get("p1_count", 0),
                "low_risk": summary.get("p2_count", 0),
                "passed": max(0, summary.get("clause_count", 0) - summary.get("total_risks", 0)),
                "completion_rate": 70,
            },
            "can_sign": summary.get("can_sign", "待评估"),
        }

    parts = [
        f"## 合同审查完成\n",
        f"- **合同类型**: {summary.get('contract_type', '未识别')}",
        f"- **审查结论**: {summary.get('can_sign', '待评估')}",
        f"- **P0 严重风险**: {summary.get('p0_count', 0)} 项",
        f"- **P1 重要风险**: {summary.get('p1_count', 0)} 项",
        f"- **P2 建议优化**: {summary.get('p2_count', 0)} 项",
        f"- **条款数量**: {summary.get('clause_count', 0)}",
        f"\n---\n\n",
        state.get("report", ""),
    ]

    return {
        "final_result": "\n".join(parts),
        "structured_review": structured,
    }


def build_contract_review_workflow(
    heavy_llm: BaseChatModel,
    fast_llm: BaseChatModel | None = None,
) -> StateGraph:
    _fast = fast_llm or heavy_llm

    graph = StateGraph(ContractReviewState)

    async def _classify(state: ContractReviewState) -> dict:
        return await classify_node(state, heavy_llm)

    async def _scan(state: ContractReviewState) -> dict:
        return await scan_risks_node(state, heavy_llm)

    async def _report(state: ContractReviewState) -> dict:
        return await generate_report_node(state, heavy_llm)

    async def _finalize(state: ContractReviewState) -> dict:
        return await finalize_node(state, _fast)

    graph.add_node("classify", _classify)
    graph.add_node("scan_risks", _scan)
    graph.add_node("generate_report", _report)
    graph.add_node("finalize", _finalize)

    graph.set_entry_point("classify")
    graph.add_edge("classify", "scan_risks")
    graph.add_edge("scan_risks", "generate_report")
    graph.add_edge("generate_report", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()
