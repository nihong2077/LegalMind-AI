"""
Qwen3-Reranker 重排序服务 — 查询-文档相关性精排

模型: Qwen/Qwen3-Reranker-0.6B（默认加载项目内 `models/` 下的本地权重，离线优先）
输入: (query, 候选文档片段列表)
输出: 按相关性分数排序的文档列表

环境约束：本地权重缺失时**不再逐请求重试 HF**（此前约 2 分钟/次），
首次加载失败即「粘性禁用」重排，保持原顺序返回（rerank_score=0.5），
由下游按法源权重排序，并打一条可定位的告警日志。
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)

_reranker = None
# 加载失败后粘性禁用，避免每个请求都付出一次 HF 网络重试的代价
_load_failed = False

# 项目根目录（LegalMind AI/）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# 本地权重缺失时的官方仓库 id
_HF_FALLBACK_ID = "Qwen/Qwen3-Reranker-0.6B"


def _resolve_model_path(model_name: str) -> str:
    """解析模型路径：`models/` 前缀的相对路径基于项目根目录；本地缺失则回退官方 HF id"""
    if Path(model_name).is_absolute():
        return model_name if Path(model_name).exists() else _HF_FALLBACK_ID
    if model_name.startswith("models/"):
        candidate = _PROJECT_ROOT / model_name
        return str(candidate) if candidate.exists() else _HF_FALLBACK_ID
    return model_name


def _get_reranker():
    """获取或初始化 Qwen3-Reranker（单例；加载失败后粘性禁用）"""
    global _reranker, _load_failed
    if _reranker is not None:
        return _reranker
    if _load_failed:
        raise RuntimeError("Qwen3-Reranker 不可用（此前加载已失败，已粘性禁用）")

    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    model_name = _resolve_model_path(settings.RERANKER_MODEL)
    device = settings.RERANKER_DEVICE
    logger.info("加载重排序模型: %s (device=%s)", model_name, device)

    try:
        try:
            # 离线优先：本地权重存在时完全不触网
            tokenizer = AutoTokenizer.from_pretrained(
                model_name, trust_remote_code=True, local_files_only=True
            )
            model = AutoModelForSequenceClassification.from_pretrained(
                model_name, trust_remote_code=True, local_files_only=True
            )
        except Exception:  # noqa: BLE001
            logger.info("本地未找到重排序权重，允许联网下载一次: %s", model_name)
            tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            model = AutoModelForSequenceClassification.from_pretrained(
                model_name, trust_remote_code=True
            )
        model = model.to(device).eval()
    except Exception as e:  # noqa: BLE001
        _load_failed = True
        logger.warning(
            "重排序模型加载失败，本次及后续请求跳过重排（按原顺序返回）: %s；"
            "如需启用，请将权重放到 models/Qwen/Qwen3-Reranker-0.6B 或修正 RERANKER_MODEL",
            e,
        )
        raise

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
        [{content, score, ...}, ...] 按 score 降序排列；重排不可用时保持原顺序（score=0.5）
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

    except Exception as e:  # noqa: BLE001
        # 粘性禁用后仅记 debug，避免每个请求都刷一条告警
        if _load_failed:
            logger.debug("重排序已禁用，按原顺序返回: %s", e)
        else:
            logger.warning("重排序失败，回退原始顺序: %s", e)
        return [{"index": i, "content": d, "rerank_score": 0.5} for i, d in enumerate(documents[:top_n])]
