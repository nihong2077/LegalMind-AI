"""
法律规则过滤器 — 法源权重 / 时效 / 文书类型 / KFE 标签命中率

四级检索链路第四阶段：在重排序 Top-20 基础上叠加法律领域二次过滤，
最终筛选 Top-5～Top-8 高置信度材料注入 Skill。
"""
import logging
from datetime import datetime, timedelta
from typing import Literal, Optional

DomainType = Literal["judge", "lawyer", "law"]

logger = logging.getLogger(__name__)

SOURCE_WEIGHTS = {
    "法律": 1.2,
    "全国人民代表大会": 1.2,
    "全国人大常委会": 1.2,
    "最高人民法院": 1.1,
    "司法解释": 1.1,
    "行政法规": 0.9,
    "部门规章": 0.85,
    "地方性法规": 0.75,
    "规范性文件": 0.7,
    "裁判文书": 0.8,
    "量刑标准": 0.85,
    "合同审查": 0.8,
}

DOC_TYPE_WEIGHTS = {
    "judge": {"判决书": 1.0, "裁定书": 0.9, "调解书": 0.7, "量刑指导": 1.1},
    "lawyer": {"辩护策略": 1.0, "证据规则": 1.0, "合同审查模板": 1.0, "代理词": 0.9, "法律意见书": 0.9},
    "law": {"法律": 1.2, "司法解释": 1.1, "行政法规": 0.9, "部门规章": 0.85},
}

DEFAULT_EFFECTIVE_DAYS_BACK = 365 * 10


def compute_legal_score(
    doc: dict,
    domain: DomainType = "law",
    kfe_tags: Optional[list[str]] = None,
) -> float:
    """
    计算法律规则加权分数

    评分因素:
    1. 法源权重 (source_weight) — 法律来源权威性加成
    2. 时效衰减 (freshness_decay) — 越新越相关
    3. 文书类型匹配 (doc_type_bonus) — 类型与领域匹配度
    4. KFE 标签命中率 (kfe_hit_rate) — 关键法律事实覆盖
    """
    base_score = doc.get("score", doc.get("rerank_score", 0.5))

    source_weight = _get_source_weight(doc)
    freshness_decay = _get_freshness_decay(doc)
    doc_type_bonus = _get_doc_type_bonus(doc, domain)
    kfe_hit_rate = _compute_kfe_hit_rate(doc, kfe_tags) if kfe_tags else 1.0

    legal_score = base_score * source_weight * freshness_decay * doc_type_bonus * kfe_hit_rate

    return round(legal_score, 4)


def _get_source_weight(doc: dict) -> float:
    """根据法源信息计算权威性权重"""
    source_name = doc.get("source_name", "")
    source_type = doc.get("source_type", "")
    doc_type = doc.get("doc_type", "")

    for key, weight in SOURCE_WEIGHTS.items():
        if key in source_name or key in source_type or key in doc_type:
            return weight

    payload = doc.get("payload", {})
    if isinstance(payload, dict):
        payload_source = payload.get("source_name", "") or payload.get("source", "")
        for key, weight in SOURCE_WEIGHTS.items():
            if key in payload_source:
                return weight

    return 0.8


def _get_freshness_decay(doc: dict) -> float:
    """计算时效衰减因子（越新越相关）"""
    now = datetime.now()

    effective_date = doc.get("effective_date")
    issue_date = doc.get("issue_date") or doc.get("judgment_date")
    created_at = doc.get("created_at")

    date_str = effective_date or issue_date or created_at
    if not date_str:
        payload = doc.get("payload", {})
        if isinstance(payload, dict):
            date_str = payload.get("effective_date") or payload.get("issue_date")

    if not date_str:
        return 0.9

    try:
        if isinstance(date_str, str):
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y%m%d"):
                try:
                    doc_date = datetime.strptime(date_str[:len(fmt)], fmt)
                    break
                except ValueError:
                    continue
            else:
                return 0.9
        elif isinstance(date_str, datetime):
            doc_date = date_str
        else:
            return 0.9

        days_passed = (now - doc_date).days
        if days_passed < 0:
            return 1.0

        half_life = 365 * 3
        decay = 0.5 ** (days_passed / half_life)
        return max(0.4, decay)
    except Exception:
        return 0.9


def _get_doc_type_bonus(doc: dict, domain: DomainType) -> float:
    """根据文书类型与角色知识域匹配度加权"""
    doc_type = doc.get("doc_type", "")
    source_type = doc.get("source_type", "")

    weights = DOC_TYPE_WEIGHTS.get(domain, {})

    for key, weight in weights.items():
        if key in doc_type or key in source_type:
            return weight

    payload = doc.get("payload", {})
    if isinstance(payload, dict):
        payload_type = payload.get("doc_type", "") or payload.get("source_type", "")
        for key, weight in weights.items():
            if key in payload_type:
                return weight

    return 0.85


def _compute_kfe_hit_rate(doc: dict, kfe_tags: list[str]) -> float:
    """计算 KFE（关键法律事实）标签命中率"""
    if not kfe_tags:
        return 1.0

    content = doc.get("content", "")
    keywords = doc.get("keywords", [])

    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",")]

    text = (content or "") + " " + " ".join(keywords)

    hits = sum(1 for tag in kfe_tags if tag in text)
    rate = hits / max(len(kfe_tags), 1)
    return 0.5 + 0.5 * rate


async def apply_legal_filter(
    candidates: list[dict],
    domain: DomainType = "law",
    kfe_tags: Optional[list[str]] = None,
    final_top_k: int = 8,
) -> list[dict]:
    """
    对重排序后的候选集执行法律规则过滤

    Args:
        candidates: 重排序后的候选文档列表 (Top-20)
        domain: 知识域 (judge/lawyer/law)
        kfe_tags: KFE 关键法律事实标签
        final_top_k: 最终返回条数

    Returns:
        过滤排序后的高置信度材料 (Top-5~8)
    """
    if not candidates:
        return []

    scored = []
    for doc in candidates:
        doc = dict(doc)
        legal_score = compute_legal_score(doc, domain, kfe_tags)
        doc["legal_score"] = legal_score
        scored.append(doc)

    scored.sort(key=lambda x: x["legal_score"], reverse=True)

    filtered = []
    seen_content_sig = set()

    for doc in scored:
        content = doc.get("content", "")
        sig = content[:120]
        if sig not in seen_content_sig:
            seen_content_sig.add(sig)
            filtered.append(doc)

        if len(filtered) >= final_top_k:
            break

    logger.debug(
        "法律过滤: %d 候选 → %d 最终输出 (domain=%s, kfe_tags=%s)",
        len(candidates), len(filtered), domain, kfe_tags[:3] if kfe_tags else [],
    )

    return filtered
