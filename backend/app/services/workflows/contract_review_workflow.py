"""
合同审查工作流 — 融合多开源项目最佳实践

流程: classify → scan_risks → generate_report → finalize

增强点:
- Playbook 合规检查（ContractIQ）
- 交叉引用检测（Ally Legal）
- 双维度风险评级（ContractIQ）
- Redline 修订建议
- 合规性验证（RAG+KG+CP）
- Guardrails 输出校验（Ally Legal）
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
    """节点1: 条款提取 + 合同分类 + Playbook 合规初检"""
    logger.info("条款提取与合同分类中...")
    skill = ContractReviewSkill(llm)
    classification = await skill.extract_and_classify(state["contract_text"])

    # 记录 Playbook 匹配结果
    playbook = classification.get("playbook", {})
    if playbook.get("matched"):
        logger.info(
            "Playbook 匹配: %s, 缺失条款: %s",
            playbook["contract_type"],
            ", ".join(playbook.get("missing", [])),
        )

    return {"classification": classification}


async def scan_risks_node(state: ContractReviewState, llm: BaseChatModel) -> dict:
    """节点2: 风险扫描 + 漏洞检测 + 合规验证"""
    logger.info("风险扫描与漏洞检测中...")
    skill = ContractReviewSkill(llm)
    risks = await skill.scan_risks(
        contract_text=state["contract_text"],
        user_position=state.get("user_position", "乙方"),
        review_stance=state.get("review_stance", "常规"),
        classification=state.get("classification"),
    )

    # 统计风险数量（安全处理非 dict 元素）
    all_issues = []
    for key in ("meso_issues", "micro_issues", "loopholes"):
        items = risks.get(key, [])
        if isinstance(items, list):
            all_issues.extend(i for i in items if isinstance(i, dict))
    p0 = len([r for r in all_issues if r.get("risk_level") == "P0"])
    p1 = len([r for r in all_issues if r.get("risk_level") == "P1"])
    compliance_items = risks.get("compliance_issues", [])
    compliance = len(compliance_items) if isinstance(compliance_items, list) else 0
    unfair_items = risks.get("unfair_terms", [])
    unfair = len(unfair_items) if isinstance(unfair_items, list) else 0
    logger.info("风险扫描完成: P0=%d, P1=%d, 合规问题=%d, 不公平条款=%d", p0, p1, compliance, unfair)

    return {"risks": risks}


async def generate_report_node(state: ContractReviewState, llm: BaseChatModel) -> dict:
    """节点3: 生成审查意见书（含 Redline 和谈判策略）"""
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
    # 安全提取风险列表
    meso = risks.get("meso_issues", []) if isinstance(risks.get("meso_issues"), list) else []
    micro = risks.get("micro_issues", []) if isinstance(risks.get("micro_issues"), list) else []
    loopholes = risks.get("loopholes", []) if isinstance(risks.get("loopholes"), list) else []
    all_issues = [i for i in meso + micro + loopholes if isinstance(i, dict)]
    p0_count = len([r for r in all_issues if r.get("risk_level") == "P0"])
    p1_count = len([r for r in all_issues if r.get("risk_level") == "P1"])
    p2_count = len([r for r in all_issues if r.get("risk_level") == "P2"])
    p3_count = len([r for r in all_issues if r.get("risk_level") == "P3"])
    p4_count = len([r for r in all_issues if r.get("risk_level") == "P4"])

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
        "p3_count": p3_count,
        "p4_count": p4_count,
        "total_risks": p0_count + p1_count + p2_count + p3_count + p4_count,
        "clause_count": classification.get("clause_count", 0),
        "readability_score": classification.get("readability", {}).get("readability_score", 0),
        "compliance_issues_count": len(risks.get("compliance_issues", [])),
        "unfair_terms_count": len(risks.get("unfair_terms", [])),
        "playbook_missing": classification.get("playbook", {}).get("missing", []),
    }

    return {"report": report, "summary": summary}


async def finalize_node(state: ContractReviewState, fast_llm: BaseChatModel) -> dict:
    """节点4: 汇总 + 用 flash 模型生成前端结构化数据"""
    summary = state.get("summary", {})
    classification = state.get("classification", {}) or {}
    risks = state.get("risks", {}) or {}

    clauses_raw = classification.get("auto_clauses", [])
    readability = classification.get("readability", {})
    playbook = classification.get("playbook", {})

    meso_issues = risks.get("meso_issues", [])
    micro_issues = risks.get("micro_issues", [])
    loopholes = risks.get("loopholes", [])
    missing_clauses = risks.get("missing_clauses", [])
    compliance_issues = risks.get("compliance_issues", [])
    unfair_terms = risks.get("unfair_terms", [])

    # 构建 Redline 数据（从风险中提取原文→建议文）
    redlines = []
    for issue in meso_issues + micro_issues:
        if issue.get("original_text") and issue.get("suggested_text"):
            redlines.append({
                "location": issue.get("related_clauses", ""),
                "risk_level": issue.get("risk_level", "P2"),
                "original_text": issue["original_text"],
                "suggested_text": issue["suggested_text"],
                "reason": issue.get("risk_name", ""),
            })
    for lo in loopholes:
        if lo.get("original_text") and lo.get("suggested_text"):
            redlines.append({
                "location": lo.get("type", ""),
                "risk_level": lo.get("risk_level", "P2"),
                "original_text": lo["original_text"],
                "suggested_text": lo["suggested_text"],
                "reason": lo.get("description", ""),
            })

    # 构建 Playbook 信息
    playbook_info = ""
    if playbook.get("matched"):
        playbook_info = f"""
Playbook 合规检查：
- 合同类型：{playbook['contract_type']}
- 缺失必备条款：{', '.join(playbook.get('missing', []))}
- 常见风险：{', '.join(playbook.get('common_risks', []))}
"""

    RISK_FIELDS = ['risk_name', 'risk_level', 'severity', 'likelihood', 'risk_consequence', 'related_clauses', 'original_text', 'suggested_text']
    meso_filtered = [{k: v for k, v in i.items() if k in RISK_FIELDS} for i in meso_issues[:6]]
    micro_filtered = [{k: v for k, v in i.items() if k in RISK_FIELDS} for i in micro_issues[:6]]
    meso_json = json.dumps(meso_filtered, ensure_ascii=False)[:2000] if meso_issues else '无'
    micro_json = json.dumps(micro_filtered, ensure_ascii=False)[:2000] if micro_issues else '无'

    prompt = f"""基于以下合同审查结果，生成前端可用的结构化JSON（严格输出JSON，不要markdown标记）：

【合同基本信息】
类型：{summary.get('contract_type', '未知')}
条款数：{summary.get('clause_count', 0)}
可读性评分：{readability.get('readability_score', 0)}/100
模糊表述：{readability.get('vague_count', 0)}处
{playbook_info}
【风险统计】
P0致命：{summary.get('p0_count', 0)}项 | P1严重：{summary.get('p1_count', 0)}项 | P2中等：{summary.get('p2_count', 0)}项 | P3轻微：{summary.get('p3_count', 0)}项 | P4提示：{summary.get('p4_count', 0)}项
合规问题：{len(compliance_issues)}项 | 不公平条款：{len(unfair_terms)}项
结论：{summary.get('can_sign', '待评估')}

【提取的条款】({len(clauses_raw)}条)
{json.dumps([{'title': c.get('title',''), 'content': c.get('content','')[:200]} for c in clauses_raw[:12]], ensure_ascii=False)[:2000]}

【中观层问题】({len(meso_issues)}条)
{meso_json}

【微观层问题】({len(micro_issues)}条)
{micro_json}

【漏洞检测】({len(loopholes)}条)
{json.dumps(loopholes[:5], ensure_ascii=False)[:1500] if loopholes else '无'}

【合规问题】({len(compliance_issues)}条)
{json.dumps(compliance_issues[:5], ensure_ascii=False)[:1500] if compliance_issues else '无'}

【不公平条款】({len(unfair_terms)}条)
{json.dumps(unfair_terms[:5], ensure_ascii=False)[:1500] if unfair_terms else '无'}

【缺失条款】
{json.dumps(missing_clauses[:8], ensure_ascii=False) if missing_clauses else '无'}

【Redline 修订】({len(redlines)}条)
{json.dumps(redlines[:8], ensure_ascii=False)[:2000] if redlines else '无'}

请输出以下JSON：
{{
    "case_name": "根据合同类型自动生成简短名称",
    "risk_level_label": "低/中/中高/高",
    "version": "v1.0",
    "review_time": "当前时间",

    "clause_tree": [
        {{"id": "basic", "label": "基本信息", "status": "pass/warning/danger/info", "risk_count": 0}},
        ...根据实际条款生成，每个条款对应一个节点
    ],

    "clauses_display": [
        {{
            "title": "条款标题",
            "content": "条款内容摘要",
            "status": "pass/warning/danger/info",
            "tags": ["标签1", "标签2"],
            "suggestion": "修改建议",
            "location": "条款位置",
            "severity": "S1-S5",
            "likelihood": "L1-L5"
        }}
    ],

    "risk_list": [
        {{
            "level": "高风险/P0",
            "title": "风险名称",
            "description": "问题描述（含法律后果+商业后果）",
            "location": "条款位置",
            "legal_basis": "法律依据",
            "suggestion": "整改建议",
            "severity": "S1-S5",
            "likelihood": "L1-L5",
            "negotiation_strategy": "谈判策略"
        }}
    ],

    "revision_list": [
        {{
            "level": "风险等级",
            "title": "修订标题",
            "description": "问题描述",
            "original_text": "原文",
            "suggested_text": "建议文本",
            "location": "条款位置",
            "reason": "修订理由"
        }}
    ],

    "compliance_list": [
        {{
            "regulation": "法规名称",
            "article": "条号",
            "issue": "合规问题",
            "risk_level": "P0-P4",
            "suggestion": "合规建议"
        }}
    ],

    "unfair_terms_list": [
        {{
            "clause": "条款位置",
            "issue": "不公平之处",
            "affected_party": "受影响方",
            "risk_level": "P0-P4",
            "suggestion": "公平化建议"
        }}
    ],

    "conclusion": {{
        "overall_assessment": "整体评价",
        "key_findings": ["发现1", "发现2", "发现3"],
        "must_fix_before_sign": ["必须修复项"],
        "negotiation_priority": ["谈判优先级"],
        "playbook_missing": ["Playbook缺失条款"]
    }},

    "report_sections": {{
        "summary": ["合同摘要要点"],
        "clause_details": ["条款详情"],
        "risk_summary": ["风险汇总"],
        "revision_summary": ["修订汇总"],
        "compliance_summary": ["合规汇总"],
        "conclusion": ["结论"]
    }},

    "stats": {{
        "total_clauses": {summary.get('clause_count', 0)},
        "high_risk": {summary.get('p0_count', 0)},
        "medium_risk": {summary.get('p1_count', 0)},
        "low_risk": {summary.get('p2_count', 0)},
        "passed": 0,
        "completion_rate": 0
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

        # 校验和补全 stats
        stats = structured.get("stats", {})
        passed = stats.get("total_clauses", 0) - stats.get("high_risk", 0) - stats.get("medium_risk", 0) - stats.get("low_risk", 0)
        stats["passed"] = max(0, passed)
        completion = min(100, int((passed / max(stats.get("total_clauses", 1), 1)) * 100))
        stats["completion_rate"] = completion

        # 补全 conclusion 中的 playbook_missing
        conclusion = structured.get("conclusion", {})
        if not conclusion.get("playbook_missing"):
            conclusion["playbook_missing"] = summary.get("playbook_missing", [])

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
            "compliance_list": [],
            "unfair_terms_list": [],
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
        f"- **P0 致命风险**: {summary.get('p0_count', 0)} 项",
        f"- **P1 严重风险**: {summary.get('p1_count', 0)} 项",
        f"- **P2 中等风险**: {summary.get('p2_count', 0)} 项",
        f"- **合规问题**: {summary.get('compliance_issues_count', 0)} 项",
        f"- **不公平条款**: {summary.get('unfair_terms_count', 0)} 项",
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
