"""
Qwen3-Embedding 嵌入服务 — 通义千问文本向量模型

模型: Qwen/Qwen3-Embedding-0.6B
向量维度: 1024
加载方式: sentence-transformers (兼容 HuggingFace)
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from sentence_transformers import SentenceTransformer

from .config import settings

logger = logging.getLogger(__name__)

_embedding_model: Optional[SentenceTransformer] = None

# 项目根目录（LegalMind AI/）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _resolve_model_path(model_name: str) -> str:
    """解析模型路径：如果是相对路径则基于项目根目录解析"""
    p = Path(model_name)
    if not p.is_absolute() and not p.name.startswith("Qwen/"):
        # 相对路径 → 基于项目根目录
        resolved = _PROJECT_ROOT / model_name
        if resolved.exists():
            return str(resolved)
    # 尝试项目根目录下 models/ 前缀
    candidate = _PROJECT_ROOT / model_name
    if candidate.exists():
        return str(candidate)
    return model_name


def get_embedding_model() -> SentenceTransformer:
    """获取或初始化 Qwen3-Embedding 模型（单例）"""
    global _embedding_model
    if _embedding_model is None:
        model_name = _resolve_model_path(settings.EMBEDDING_MODEL)
        device = settings.EMBEDDING_DEVICE
        logger.info("加载 Qwen 嵌入模型: %s (device=%s)", model_name, device)

        # 优先离线加载（避免网络不可达导致失败）
        try:
            _embedding_model = SentenceTransformer(
                model_name,
                device=device,
                trust_remote_code=True,
                local_files_only=True,
            )
            logger.info("Qwen 嵌入模型加载完成 (离线模式), 向量维度=%d",
                        _embedding_model.get_embedding_dimension())
        except Exception as e:
            logger.warning("离线加载失败 (%s), 尝试在线加载...", e)
            _embedding_model = SentenceTransformer(
                model_name,
                device=device,
                trust_remote_code=True,
            )

        dim = _embedding_model.get_embedding_dimension()
        logger.info("Qwen 嵌入模型加载完成, 向量维度=%d", dim)

    return _embedding_model


async def embed_texts(texts: list[str], batch_size: Optional[int] = None) -> list[list[float]]:
    """批量文本转向量"""
    if not texts:
        return []

    bs = batch_size or settings.EMBEDDING_BATCH_SIZE
    model = get_embedding_model()
    embeddings = await asyncio.to_thread(
        model.encode,
        texts,
        batch_size=bs,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    return embeddings.tolist()


async def embed_text(text: str) -> list[float]:
    """单条文本转向量"""
    results = await embed_texts([text])
    return results[0] if results else []


async def compute_similarity(text1: str, text2: str) -> float:
    """计算两条文本的余弦相似度"""
    emb1, emb2 = await embed_texts([text1, text2])
    if not emb1 or not emb2:
        return 0.0
    a, b = np.array(emb1), np.array(emb2)
    return float(np.dot(a, b))
