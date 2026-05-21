"""
Qwen3-Reranker 重排序服务 — 查询-文档相关性精排

模型: Qwen/Qwen3-Reranker
输入: (query, 候选文档片段列表)
输出: 按相关性分数排序的文档列表
"""
import asyncio
import logging
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)

_reranker = None


def _get_reranker():
    """获取或初始化 Qwen3-Reranker（单例）"""
    global _reranker
    if _reranker is None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        model_name = settings.RERANKER_MODEL
        device = settings.RERANKER_DEVICE
        logger.info("加载重排序模型: %s (device=%s)", model_name, device)

        tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        model = AutoModelForSequenceClassification.from_pretrained(
            model_name,
            trust_remote_code=True,
        ).to(device).eval()

        _reranker = (tokenizer, model, device)
        logger.info("重排序模型加载完成")

    return _reranker


def _run_reranker_inference(tokenizer, model, device, pairs, top_n):
    """同步执行重排序推理（在线程池中运行）"""
    import torch
    inputs = tokenizer(
        pairs,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    ).to(device)
    with torch.no_grad():
        scores = model(**inputs, return_dict=True).logits.view(-1).float()
    return scores


async def rerank_documents(
    query: str,
    documents: list[str],
    top_n: Optional[int] = None,
    batch_size: int = 16,
) -> list[dict]:
    """
    对候选文档片段进行相关性重排序

    Args:
        query: 用户查询（或 HyDE 改写后的查询）
        documents: 候选文档内容列表
        top_n: 返回前 N 条，默认取配置 RERANKER_TOP_N
        batch_size: 批处理大小

    Returns:
        [{content, score, ...}, ...] 按 score 降序排列
    """
    if not documents:
        return []

    top_n = top_n or settings.RERANKER_TOP_N
    top_n = min(top_n, len(documents))

    try:
        tokenizer, model, device = _get_reranker()

        pairs = [[query, doc[:2048]] for doc in documents]
        scores = await asyncio.to_thread(
            _run_reranker_inference, tokenizer, model, device, pairs, top_n
        )

        results = [
            {"index": i, "content": documents[i], "rerank_score": round(scores[i].item(), 4)}
            for i in range(len(documents))
        ]
        results.sort(key=lambda x: x["rerank_score"], reverse=True)

        return results[:top_n]

    except Exception as e:
        logger.warning("重排序失败，回退原始顺序: %s", e)
        return [{"index": i, "content": d, "rerank_score": 0.5} for i, d in enumerate(documents[:top_n])]
