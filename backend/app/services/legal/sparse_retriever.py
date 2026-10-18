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

    注意：Qdrant collection 本身已按 domain 路由（``COLLECTIONS[domain]``），
    且库内 payload 并不存在 ``domain`` 字段。旧实现在此处附加 ``domain`` 过滤条件，
    会使 Dense 召回恒为 0 条（每次都被迫回退关键词检索），故不再附加 payload 过滤。

    Returns:
        (keyword_terms, payload_filter) 关键词列表和 Qdrant payload 过滤器（恒为 None）
    """
    terms = extract_precise_terms(query)
    return terms, None


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
    合并时以 ``sparse_results``（字段更完整，含已提升的顶层 ``content``）为基，
    只从 ``qdrant_results`` 取 dense 分数；否则顶层 ``content`` 会在此处丢失，
    导致下游按 ``content`` 去重时把候选折叠成 1 条。
    """
    # id -> dense 原始命中（仅有 id/score/payload，缺顶层 content）
    dense_map = {}
    for r in qdrant_results:
        cid = r.get("id", "")
        if cid:
            dense_map[cid] = r

    # id -> sparse 候选（已携带 payload / 已提升的顶层 content / sparse_score 等完整字段）
    sparse_docs = {}
    for r in sparse_results:
        cid = r.get("id", "")
        if cid:
            sparse_docs[cid] = r

    # 合并所有候选 id
    all_ids = set(dense_map.keys()) | set(sparse_docs.keys())

    merged = []
    for cid in all_ids:
        dense_score = dense_map[cid].get("score", 0.0) if cid in dense_map else 0.0

        # 以 sparse_results（字段更完整）为基，避免丢掉已提升的顶层 content；
        # 仅在 sparse 中缺失时退回 dense 原始命中。
        base = sparse_docs.get(cid) or dense_map.get(cid) or {"id": cid}
        r = dict(base)

        sparse_score = float(r.get("sparse_score", 0.0) or 0.0)
        combined = (1 - sparse_weight) * dense_score + sparse_weight * sparse_score
        r["dense_score"] = dense_score
        r["sparse_score"] = sparse_score
        r["score"] = round(combined, 4)
        merged.append(r)

    merged.sort(key=lambda x: x["score"], reverse=True)
    return merged[:top_k]
