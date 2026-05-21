"""
BM25 / 关键词稀疏检索 — 精确匹配能力补充

设计:
- Dense 通道负责语义覆盖（Qwen3-Embedding）
- Sparse 通道负责精确匹配（法条编号、金额、日期、专有术语）
- 两路结果送入 Qdrant Hybrid Query 初步召回 Top-100
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

LAW_ARTICLE_PATTERN = re.compile(
    r'第[零一二三四五六七八九十百千]+条|'
    r'第\d+条|'
    r'《[^》]+》|'
    r'\b\d{4}年\d{1,2}月\d{1,2}日\b|'
    r'\b\d+万?元?\b|'
)

LEGAL_KEYWORDS = {
    "合同纠纷": ["违约责任", "合同解除", "缔约过失", "格式条款", "定金", "违约金"],
    "侵权责任": ["过错", "因果关系", "损害赔偿", "精神损害", "连带责任"],
    "婚姻家庭": ["离婚", "抚养权", "财产分割", "赡养", "继承"],
    "劳动争议": ["劳动合同", "工伤", "经济补偿", "加班工资", "竞业限制"],
    "公司纠纷": ["股权", "股东会", "董事会", "清算", "法定代表人"],
    "知识产权": ["专利权", "商标权", "著作权", "侵权", "许可使用"],
    "行政诉讼": ["行政复议", "行政强制", "行政许可", "政府信息公开"],
    "刑事诉讼": ["故意伤害", "盗窃", "诈骗", "贪污", "受贿", "寻衅滋事"],
}


def extract_precise_terms(query: str) -> list[str]:
    """从查询中提取精确匹配术语（法条编号、日期、金额等）"""
    terms = []

    matches = LAW_ARTICLE_PATTERN.findall(query)
    terms.extend(matches)

    for category, keywords in LEGAL_KEYWORDS.items():
        for kw in keywords:
            if kw in query:
                terms.append(kw)

    amount_matches = re.findall(r'\d+(?:\.\d+)?万?元', query)
    terms.extend(amount_matches)

    return list(set(terms))


def build_sparse_conditions(
    query: str,
    domain: str = "law",
) -> tuple[list[str], Optional[dict]]:
    """
    构建稀疏检索条件和 Payload 过滤条件

    Returns:
        (keyword_terms, payload_filter) 关键词列表和 Qdrant payload 过滤器
    """
    terms = extract_precise_terms(query)

    payload_filter = {}
    if domain:
        payload_filter["domain"] = domain

    return terms, payload_filter if payload_filter else None


async def sparse_search_keywords(
    keywords: list[str],
    documents: list[dict],
    top_k: int = 100,
) -> list[dict]:
    """
    对候选文档执行关键词匹配打分
    使用简化的 BM25-like 评分：命中关键词数 / max(文档长度, 平均长度)
    """
    if not keywords or not documents:
        return documents

    scored = []
    for doc in documents:
        content = doc.get("content", "")
        if not content:
            doc["sparse_score"] = 0.0
            scored.append(doc)
            continue

        hit_count = 0
        for kw in keywords:
            if kw in content:
                hit_count += 1

        doc["sparse_score"] = round(hit_count / max(len(keywords), 1), 4)
        scored.append(doc)

    return scored


def merge_dense_sparse_scores(
    qdrant_results: list[dict],
    sparse_results: list[dict],
    sparse_weight: float = 0.3,
    top_k: int = 100,
) -> list[dict]:
    """
    融合 Dense 和 Sparse 通道分数

    combined_score = (1 - w) * dense_score + w * sparse_score
    同时保留仅在 sparse_results 中出现但不在 qdrant_results 中的候选
    """
    # 构建 qdrant 的 id -> result 映射
    dense_map = {}
    for r in qdrant_results:
        cid = r.get("id", "")
        if cid:
            dense_map[cid] = r

    # 构建 sparse 的 id -> score 映射
    sparse_map = {}
    for r in sparse_results:
        cid = r.get("id", "")
        if cid:
            sparse_map[cid] = r.get("sparse_score", 0.0)

    # 合并所有候选 id
    all_ids = set(dense_map.keys()) | set(sparse_map.keys())

    merged = []
    for cid in all_ids:
        dense_r = dense_map.get(cid)
        dense_score = dense_r.get("score", 0.0) if dense_r else 0.0
        sparse_score = sparse_map.get(cid, 0.0)

        # 如果有 dense 结果，在其基础上更新分数
        if dense_r:
            r = dict(dense_r)
        else:
            # 仅在 sparse 中出现的候选，使用 sparse 结果作为基础
            r = next((s for s in sparse_results if s.get("id") == cid), {"id": cid})
            r = dict(r)

        combined = (1 - sparse_weight) * dense_score + sparse_weight * sparse_score
        r["dense_score"] = dense_score
        r["sparse_score"] = sparse_score
        r["score"] = round(combined, 4)
        merged.append(r)

    merged.sort(key=lambda x: x["score"], reverse=True)
    return merged[:top_k]
