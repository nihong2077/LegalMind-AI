"""稀疏检索条件构建测试 —— 锁定「不得附加 domain payload 过滤」回归。

背景：Qdrant collection 本身已按 domain 路由（``COLLECTIONS[domain]``），库内 payload
并不存在 ``domain`` 字段。旧实现在 ``build_sparse_conditions`` 追加 ``domain`` 过滤条件，
使 Dense 召回恒为 0 条（每次都被迫回退关键词检索），直接导致工具辐条（法规/类案检索）
检索不到材料、产不出引用卡。本测试防止该过滤被重新引入。
"""
import sys

sys.path.insert(0, ".")

from app.services.legal.sparse_retriever import (
    build_sparse_conditions,
    extract_precise_terms,
)


def test_no_domain_payload_filter():
    """payload_filter 必须为 None（不得附加 domain 条件）。"""
    for domain in ("law", "judge", "lawyer"):
        _, payload_filter = build_sparse_conditions("竞业限制条款是否有效", domain)
        assert payload_filter is None


def test_extracts_domain_keywords():
    """领域关键词应被抽取为稀疏精确匹配术语。"""
    terms, _ = build_sparse_conditions("员工离职后竞业限制条款是否有效？经济补偿标准如何认定？", "law")
    assert "竞业限制" in terms
    assert "经济补偿" in terms


def test_article_number_and_amount_terms():
    """法条编号 / 金额亦属精确术语。"""
    terms = extract_precise_terms("依据《劳动合同法》第二十三条，约定违约金 10万元")
    assert "第二十三条" in terms
    assert "《劳动合同法》" in terms
