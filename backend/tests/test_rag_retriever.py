"""检索结果去重 / 折叠回归测试（引用卡折叠问题）。

背景：Qdrant 命中只带 ``payload``（正文在 payload 内），旧实现未把正文提升到顶层
``content``，导致 ``apply_legal_filter`` 按 ``content[:120]`` 去重时把全部命中折叠成
1 条 —— 引用卡只剩 1 条引用。本测试锁定 ``_deduplicate_candidates`` 的正文提升。
"""
import sys

import pytest

sys.path.insert(0, ".")

from app.services.legal.legal_filter import apply_legal_filter
from app.services.legal.sparse_retriever import merge_dense_sparse_scores
from app.services.legal.rag_retriever import (
    _deduplicate_candidates,
    _resolve_payload_content,
)


def _qdrant_hit(pid, payload):
    return {"id": pid, "score": 0.7, "payload": payload}


def test_promotes_payload_content_for_qdrant_hits():
    """Qdrant 命中的正文必须提升到顶层 content（兼容法条正文 / 法规标题两种形态）。"""
    hits = [
        _qdrant_hit("1", {"content": "第一条 竞业限制", "law_name": "劳动合同法"}),
        _qdrant_hit("2", {"title": "中华人民共和国劳动法"}),
    ]
    merged = _deduplicate_candidates(hits, [])
    assert merged[0]["content"] == "第一条 竞业限制"
    assert merged[1]["content"] == "中华人民共和国劳动法"


@pytest.mark.asyncio
async def test_distinct_candidates_are_not_collapsed():
    """修复前：Qdrant 命中 content 为空 → apply_legal_filter 把 5 条折叠为 1 条。"""
    hits = [
        _qdrant_hit(str(i), {"content": f"法条正文 {i}：" + "x" * 150})
        for i in range(5)
    ]
    merged = _deduplicate_candidates(hits, [])
    filtered = await apply_legal_filter(candidates=merged, domain="law", final_top_k=5)
    assert len(filtered) == 5


def test_resolve_payload_content_fallback_order():
    assert _resolve_payload_content({"content": "正文", "title": "标题"}) == "正文"
    assert _resolve_payload_content({"facts_summary": "事实", "title": "标题"}) == "事实"
    assert _resolve_payload_content({"title": "标题"}) == "标题"
    assert _resolve_payload_content({}) == ""


def test_merge_preserves_promoted_content():
    """dense/sparse 合并后必须保留已提升的顶层 content（否则引用卡继续折叠）。"""
    dense = [{"id": "a", "score": 0.8, "payload": {"content": "正文A"}}]
    promoted = _deduplicate_candidates(dense, [])
    merged = merge_dense_sparse_scores(dense, promoted, sparse_weight=0.3, top_k=10)
    assert merged[0]["content"] == "正文A"
