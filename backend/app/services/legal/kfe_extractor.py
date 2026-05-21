"""
KFE (Key Fact Extraction) 关键法律事实提取模块。

从案件描述、证据材料中结构化提取关键信息属性，
作为收敛判定和决策的硬性因素。
"""

import json
import logging
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

KFE_SYSTEM_PROMPT = """你是一位法律事实分析专家，擅长从案件描述中提取关键法律事实属性。

请从以下案件材料中提取结构化的关键法律事实（KFE），以 JSON 格式返回。

提取维度包括：
1. breach_type: 违约/侵权责任类型（"故意" / "过失" / "无过错" / "不明确"）
2. fault_ratio_plaintiff: 原告过错比例（0-100 的整数）
3. fault_ratio_defendant: 被告过错比例（0-100 的整数）
4. breach_category: 违约类别（"延迟履行" / "不完全履行" / "拒绝履行" / "履行不能" / "不适用"）
5. damage_amount: 主张的损失金额（数字，无则为 0）
6. evidence_strength_plaintiff: 原告证据强度（"强" / "中" / "弱"）
7. evidence_strength_defendant: 被告证据强度（"强" / "中" / "弱"）
8. contract_key_breach: 违反的关键合同条款描述
9. settlement_willingness: 调解意愿（"高" / "中" / "低" / "不明确"）
10. party_type: 当事人类型（"个人" / "企业" / "混合"）
11. limitation_period_risk: 诉讼时效风险（"已过期" / "临近" / "正常" / "不明确"）
12. jurisdiction: 管辖约定（"有约定" / "法定" / "不明确"）

请只返回 JSON，不要包含其他文字。"""

KFE_DEFAULTS: dict[str, Any] = {
    "breach_type": "不明确",
    "fault_ratio_plaintiff": 0,
    "fault_ratio_defendant": 0,
    "breach_category": "不适用",
    "damage_amount": 0,
    "evidence_strength_plaintiff": "中",
    "evidence_strength_defendant": "中",
    "contract_key_breach": "",
    "settlement_willingness": "不明确",
    "party_type": "个人",
    "limitation_period_risk": "不明确",
    "jurisdiction": "不明确",
}

KFE_CRITICAL_KEYS = [
    "breach_type",
    "fault_ratio_plaintiff",
    "fault_ratio_defendant",
    "breach_category",
    "evidence_strength_plaintiff",
    "evidence_strength_defendant",
]


def _parse_kfe_json(raw: str) -> dict:
    """从 LLM 返回的文本中提取 JSON"""
    raw = raw.strip()
    json_match = re.search(r"\{[\s\S]*\}", raw)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("KFE JSON 解析失败，使用默认值。原始输出: %.200s", raw)
        return {}


def _merge_with_defaults(parsed: dict) -> dict:
    """将解析结果与默认值合并，确保所有字段存在"""
    result = dict(KFE_DEFAULTS)
    for key in KFE_DEFAULTS:
        if key in parsed:
            result[key] = parsed[key]
    return result


async def extract_kfe(
    case_description: str,
    evidence_summary: str = "",
    llm: BaseChatModel | None = None,
) -> dict:
    """
    从案件描述中提取关键法律事实。

    Args:
        case_description: 案件描述文本
        evidence_summary: 证据摘要
        llm: 语言模型实例，为 None 时使用规则提取

    Returns:
        结构化的 KFE 字典
    """
    if llm is None:
        return _rule_based_extract(case_description, evidence_summary)

    prompt = f"""案件描述：
{case_description}

证据摘要：
{evidence_summary or "（无）"}"""

    messages = [
        SystemMessage(content=KFE_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]
    try:
        response = await llm.ainvoke(messages)
        parsed = _parse_kfe_json(response.content)
        return _merge_with_defaults(parsed)
    except Exception as e:
        logger.error("KFE LLM 提取失败: %s，回退到规则提取", e)
        return _rule_based_extract(case_description, evidence_summary)


def _rule_based_extract(case_description: str, evidence_summary: str = "") -> dict:
    """基于规则的 KFE 提取（不依赖 LLM 的快速回退方案）"""
    result = dict(KFE_DEFAULTS)
    text = case_description + " " + evidence_summary

    if re.search(r"故意|恶意|明知|欺诈", text):
        result["breach_type"] = "故意"
    elif re.search(r"过失|疏忽|未尽.*义务|大意", text):
        result["breach_type"] = "过失"

    if re.search(r"延迟|逾期|超期|未按时|拖延", text):
        result["breach_category"] = "延迟履行"
    elif re.search(r"不完全|部分.*履行|瑕疵|质量.*问题", text):
        result["breach_category"] = "不完全履行"
    elif re.search(r"拒绝|明确.*不.*履行|拒不", text):
        result["breach_category"] = "拒绝履行"

    amount_match = re.search(r"(\d+\.?\d*)\s*(万|元|美元|万元)", text)
    if amount_match:
        try:
            amount = float(amount_match.group(1))
            if "万" in amount_match.group(2):
                amount *= 10000
            result["damage_amount"] = amount
        except ValueError:
            pass

    if re.search(r"企业|公司|有限公司|集团", text):
        result["party_type"] = "企业"

    if re.search(r"调解|和解|协商|愿意.*解决", text):
        result["settlement_willingness"] = "高"

    if re.search(r"时效|过期|超过.*年|三年.*前", text):
        result["limitation_period_risk"] = "临近"

    return result


def compare_kfe(kfe_a: dict, kfe_b: dict) -> dict:
    """
    比较两份 KFE 是否在关键维度上一致。

    Returns:
        {
            "is_consistent": bool,
            "mismatches": list[str],  # 不一致的字段列表
            "details": dict,          # 逐字段比较详情
        }
    """
    mismatches = []
    details = {}

    for key in KFE_CRITICAL_KEYS:
        val_a = kfe_a.get(key, KFE_DEFAULTS.get(key))
        val_b = kfe_b.get(key, KFE_DEFAULTS.get(key))

        if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
            is_match = abs(val_a - val_b) <= 10
        else:
            is_match = str(val_a).strip() == str(val_b).strip()

        details[key] = {
            "a": val_a,
            "b": val_b,
            "match": is_match,
        }
        if not is_match:
            mismatches.append(key)

    return {
        "is_consistent": len(mismatches) == 0,
        "mismatches": mismatches,
        "details": details,
    }
