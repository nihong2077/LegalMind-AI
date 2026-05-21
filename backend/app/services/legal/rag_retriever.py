"""
RAG 四级检索收敛链路 — LegalMind AI 核心检索模块

┌──────────────────────────────────────────────────────────────┐
│  Stage 1: HyDE 查询改写 (V4-Flash)                            │
│   用户口语化案情 → 结构化法律叙述，保留原始事实锚点            │
├──────────────────────────────────────────────────────────────┤
│  Stage 2: 混合召回 (Dense + Sparse → Qdrant Hybrid Query)     │
│   Dense: Qwen3-Embedding 语义向量                            │
│   Sparse: BM25/关键词 + Payload 过滤                         │
│   初步召回 Top-100 候选片段                                   │
├──────────────────────────────────────────────────────────────┤
│  Stage 3: 专用重排序 (Qwen3-Reranker)                        │
│   候选片段与查询相关性精排 → 压缩至 Top-20                     │
├──────────────────────────────────────────────────────────────┤
│  Stage 4: 法律规则过滤                                       │
│   法源权重 × 时效衰减 × 文书类型 × KFE 标签命中              │
│   最终筛选 Top-5~8 高置信度材料                               │
└──────────────────────────────────────────────────────────────┘

三库路由策略:
- judge: 法官视角 → 检索裁判文书、判例、量刑标准
- lawyer: 律师视角 → 检索辩护策略、证据规则、合同审查
- law: 法条视角 → 检索法律法规、司法解释、部门规章
"""
import logging
from typing import Literal, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ...core.config import settings
from ...core.embedding import embed_text
from ...core.pg_client import (
    search_contract_review_by_vector,
    search_defense_strategies_by_vector,
    search_evidence_rules_by_vector,
    search_judge_cases_by_vector,
    search_law_by_keyword,
    search_law_by_vector,
    search_sentencing_by_vector,
)
from ...core.qdrant_client import (
    COLLECTION_JUDGE,
    COLLECTION_LAW,
    COLLECTION_LAWYER,
    COLLECTIONS,
    search_vectors,
)
from ...core.reranker import rerank_documents
from .legal_filter import apply_legal_filter
from .sparse_retriever import (
    build_sparse_conditions,
    extract_precise_terms,
    merge_dense_sparse_scores,
    sparse_search_keywords,
)

logger = logging.getLogger(__name__)

DomainType = Literal["judge", "lawyer", "law"]

HYDE_SYSTEM_PROMPT = """你是一位法律文书撰写专家。请将用户的口语化法律问题，
转换为一段标准、专业的法律叙述文本（假设文档）。

要求：
1. 使用正式的法律术语和表达方式
2. 明确法律关系、权利义务和争议焦点
3. 控制在 100-200 字以内
4. 保留原文中的关键事实信息（金额、日期、当事人关系、合同条款等）
5. 不要添加任何解释或前缀，直接输出转换后的文本"""


async def generate_hyde_document(
    query: str,
    llm: BaseChatModel,
    num_variants: int = 3,
) -> list[str]:
    """
    Stage 1: HyDE 查询改写 (V4-Flash)

    将用户口语化案情转化为结构化法律叙述，保留原始事实锚点
    """
    variants = []
    for i in range(num_variants):
        temperature = 0.5 + i * 0.2
        prompt = f"请将以下用户问题转换为标准法律叙述：\n\n{query}"
        messages = [
            SystemMessage(content=HYDE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        try:
            response = await llm.ainvoke(messages)
            variants.append(response.content.strip())
        except Exception as e:
            logger.warning("HyDE 变体 %d 生成失败: %s", i + 1, e)

    return variants if variants else [query]


async def retrieve_legal_knowledge(
    query: str,
    llm: BaseChatModel,
    top_k: int = 8,
    use_hyde: bool = True,
    domain: DomainType = "law",
    kfe_tags: Optional[list[str]] = None,
) -> list[dict]:
    """
    四级检索收敛链路总入口

    Args:
        query: 用户原始查询（口语化）
        llm: V4-Flash LLM 实例（用于 HyDE 改写）
        top_k: 最终返回结果数 (默认 8)
        use_hyde: 是否启用 HyDE 查询改写
        domain: 检索领域 (judge/lawyer/law)
        kfe_tags: KFE 关键法律事实标签（用于第四阶段过滤）
    """
    search_query = query
    original_query = query

    # ================================================================
    # Stage 1: HyDE 查询改写
    # ================================================================
    if use_hyde:
        hyde_docs = await generate_hyde_document(query, llm, num_variants=2)
        if hyde_docs:
            search_query = hyde_docs[0]
            logger.info(
                "Stage1 HyDE 改写完成: %.60s → %.120s",
                original_query[:60], search_query[:120],
            )

    # ================================================================
    # Stage 2: 混合召回 — Dense + Sparse → Qdrant
    # ================================================================
    try:
        query_embedding = await embed_text(search_query)
    except Exception as e:
        logger.warning("Dense 嵌入生成失败，回退纯关键词: %s", e)
        return await _keyword_fallback(original_query, top_k, domain)

    sparse_terms, payload_filter = build_sparse_conditions(original_query, domain)
    logger.debug("Sparse 精确匹配术语: %s", sparse_terms)

    qdrant_collection = COLLECTIONS.get(domain, COLLECTION_LAW)

    qdrant_candidates = []
    try:
        qdrant_candidates = await search_vectors(
            collection_name=qdrant_collection,
            query_vector=query_embedding,
            top_k=settings.HYBRID_RECALL_TOP_K,
            score_threshold=settings.SCORE_THRESHOLD_DENSE,
            filter_conditions=payload_filter,
        )
        logger.info("Stage2 Qdrant Dense 召回: %d 条", len(qdrant_candidates))
    except Exception as e:
        logger.warning("Qdrant 检索失败: %s", e)

    pg_candidates = await _pg_parallel_recall(query_embedding, domain)

    all_candidates = _deduplicate_candidates(qdrant_candidates, pg_candidates)

    if sparse_terms:
        all_candidates = await sparse_search_keywords(sparse_terms, all_candidates, settings.HYBRID_RECALL_TOP_K)
        all_candidates = merge_dense_sparse_scores(
            qdrant_candidates, all_candidates, sparse_weight=0.3, top_k=settings.HYBRID_RECALL_TOP_K
        )
        logger.info("Stage2 混合召回完成 (Dense+Sparse): %d 条候选", len(all_candidates))
    else:
        all_candidates.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        all_candidates = all_candidates[:settings.HYBRID_RECALL_TOP_K]
        logger.info("Stage2 Dense 召回完成: %d 条候选", len(all_candidates))

    if not all_candidates:
        logger.info("混合召回无结果，回退关键词检索")
        return await _keyword_fallback(original_query, top_k, domain)

    # ================================================================
    # Stage 3: 专用重排序 — Qwen3-Reranker
    # ================================================================
    candidate_texts = []
    for c in all_candidates:
        payload = c.get("payload", {})
        text = c.get("content", "") or payload.get("content", "") or ""
        if not text:
            text = str(payload)
        candidate_texts.append(text)

    reranked = await rerank_documents(
        query=search_query,
        documents=candidate_texts,
        top_n=settings.RERANKER_TOP_N,
    )
    logger.info("Stage3 Qwen3-Reranker 精排完成: Top-%d", len(reranked))

    for i, rr in enumerate(reranked):
        idx = rr["index"]
        if idx < len(all_candidates):
            all_candidates[idx]["rerank_score"] = rr["rerank_score"]
            all_candidates[idx]["score"] = rr["rerank_score"]

    scored_candidates = [all_candidates[rr["index"]] for rr in reranked if rr["index"] < len(all_candidates)]

    # ================================================================
    # Stage 4: 法律规则过滤
    # ================================================================
    final_results = await apply_legal_filter(
        candidates=scored_candidates,
        domain=domain,
        kfe_tags=kfe_tags,
        final_top_k=top_k,
    )
    logger.info("Stage4 法律规则过滤完成: %d → %d 条", len(scored_candidates), len(final_results))

    if not final_results:
        return await _keyword_fallback(original_query, top_k, domain)

    return _format_final_results(final_results)


async def _pg_parallel_recall(
    query_embedding: list[float],
    domain: DomainType,
) -> list[dict]:
    """pgvector 并行召回 — 根据领域路由不同表"""
    results: list[dict] = []

    try:
        if domain == "judge":
            results.extend(await search_judge_cases_by_vector(query_embedding, top_k=50))
            results.extend(await search_sentencing_by_vector(query_embedding, top_k=30))
        elif domain == "lawyer":
            results.extend(await search_defense_strategies_by_vector(query_embedding, top_k=40))
            results.extend(await search_evidence_rules_by_vector(query_embedding, top_k=30))
            results.extend(await search_contract_review_by_vector(query_embedding, top_k=30))
        else:
            results.extend(await search_law_by_vector(query_embedding, top_k=60))
    except Exception as e:
        logger.warning("pgvector 并行召回异常: %s", e)

    logger.debug("pgvector 召回: %d 条 (domain=%s)", len(results), domain)
    return results


def _deduplicate_candidates(
    qdrant_results: list[dict],
    pg_results: list[dict],
) -> list[dict]:
    """Qdrant + pgvector 结果去重合并"""
    seen_ids = set()
    seen_content_sig = set()
    merged = []

    for r in qdrant_results:
        cid = r.get("id", "")
        if cid not in seen_ids:
            seen_ids.add(cid)
            merged.append(r)

    for r in pg_results:
        rid = str(r.get("id", ""))
        if rid in seen_ids:
            continue
        content = r.get("content", "")
        sig = content[:100] if content else rid
        if sig in seen_content_sig:
            continue
        seen_ids.add(rid)
        seen_content_sig.add(sig)
        merged.append({
            "id": rid,
            "score": r.get("score", 0.5),
            "payload": r,
            "content": content,
        })

    return merged


async def _keyword_fallback(
    query: str,
    top_k: int,
    domain: DomainType = "law",
) -> list[dict]:
    """关键词检索回退方案"""
    try:
        results = await search_law_by_keyword(query, top_k=top_k)
        return [
            {
                "content": f"{r['law_name']} 第{r.get('article_number', '')}条: {r['content'][:300]}",
                "source": r["law_name"],
                "score": 0.7,
            }
            for r in results
        ]
    except Exception as e:
        logger.error("关键词回退失败: %s", e)

    return [{"content": "未能检索到相关法律知识", "source": "system", "score": 0.0}]


def _format_final_results(results: list[dict]) -> list[dict]:
    """格式化最终输出，提取核心字段"""
    formatted = []
    for r in results:
        payload = r.get("payload", {}) if isinstance(r.get("payload"), dict) else {}
        content = r.get("content", "") or payload.get("content", "") or ""
        source = (
            r.get("source_name", "")
            or payload.get("source_name", "")
            or payload.get("law_name", "")
            or payload.get("case_name", "")
            or payload.get("source", "")
        )

        formatted.append({
            "content": content[:500],
            "source": source or "系统",
            "score": r.get("legal_score", r.get("rerank_score", r.get("score", 0.0))),
            "domain": r.get("domain", ""),
            "doc_type": r.get("doc_type", "") or payload.get("doc_type", ""),
        })

    formatted.sort(key=lambda x: x["score"], reverse=True)
    return formatted


def format_retrieval_context(results: list[dict]) -> str:
    """将检索结果格式化为 LLM 可用的上下文文本"""
    if not results:
        return ""

    lines = ["【相关法律知识】"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['content']}")
        meta_parts = []
        if r.get("source"):
            meta_parts.append(f"来源: {r['source']}")
        if r.get("score"):
            meta_parts.append(f"置信度: {r['score']:.2f}")
        if meta_parts:
            lines.append("   " + " | ".join(meta_parts))
    return "\n".join(lines)
