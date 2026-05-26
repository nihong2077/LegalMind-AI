"""
Qdrant 向量检索 — 三套 Collection 对应三库

Collection 设计:
- judge_knowledge: 法官知识向量 (裁判文书、判例、量刑标准)
- lawyer_knowledge: 律师知识向量 (辩护策略、证据规则、合同审查)
- law_knowledge: 法条知识向量 (法律法规、司法解释、部门规章)
"""
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from .config import settings

logger = logging.getLogger(__name__)

COLLECTION_JUDGE = "judge_knowledge"
COLLECTION_LAWYER = "lawyer_knowledge"
COLLECTION_LAW = "law_knowledge"

COLLECTIONS = {
    "judge": COLLECTION_JUDGE,
    "lawyer": COLLECTION_LAWYER,
    "law": COLLECTION_LAW,
}

VECTOR_SIZE = settings.EMBEDDING_DIM

# 默认本地存储路径：项目根目录 data/qdrant_DATA
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_QDRANT_PATH = str(_PROJECT_ROOT / "data" / "qdrant_data")

_qdrant_client: Optional[AsyncQdrantClient] = None


def get_qdrant_client() -> AsyncQdrantClient:
    """获取 Qdrant 异步客户端（单例）

    优先使用本地文件路径模式（QDRANT_PATH），
    若未配置则回退到 URL 模式（QDRANT_URL）。
    """
    global _qdrant_client
    if _qdrant_client is None:
        # 解析 QDRANT_PATH：相对路径基于项目根目录
        raw_path = settings.QDRANT_PATH
        if raw_path:
            p = Path(raw_path)
            if not p.is_absolute():
                local_path = str(_PROJECT_ROOT / raw_path)
            else:
                local_path = raw_path
        else:
            local_path = _DEFAULT_QDRANT_PATH

        if os.path.isdir(local_path):
            _qdrant_client = AsyncQdrantClient(path=local_path)
            logger.info("Qdrant 客户端初始化 (本地模式): %s", local_path)
        else:
            _qdrant_client = AsyncQdrantClient(
                url=settings.QDRANT_URL,
                timeout=30.0,
            )
            logger.info("Qdrant 客户端初始化 (远程模式): %s", settings.QDRANT_URL)
    return _qdrant_client


async def init_qdrant():
    """初始化三套 Qdrant Collections"""
    client = get_qdrant_client()

    collection_defs = [
        (COLLECTION_JUDGE, "法官知识库 — 裁判文书、判例、量刑标准"),
        (COLLECTION_LAWYER, "律师知识库 — 辩护策略、证据规则、合同审查"),
        (COLLECTION_LAW, "法条知识库 — 法律法规、司法解释、部门规章"),
    ]

    for name, description in collection_defs:
        try:
            await client.get_collection(name)
            logger.info("Collection '%s' 已存在", name)
        except UnexpectedResponse:
            await client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=VECTOR_SIZE,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info("Collection '%s' 创建成功 (%s)", name, description)


async def close_qdrant():
    """关闭 Qdrant 连接"""
    global _qdrant_client
    if _qdrant_client:
        await _qdrant_client.close()
        _qdrant_client = None
        logger.info("Qdrant 连接已关闭")


async def upsert_vectors(
    collection_name: str,
    vectors: list[list[float]],
    payloads: list[dict],
    ids: Optional[list[str]] = None,
) -> list[str]:
    """批量插入/更新向量"""
    client = get_qdrant_client()

    if ids is None:
        ids = [str(uuid.uuid4()) for _ in vectors]

    points = [
        models.PointStruct(id=pid, vector=vec, payload=pl)
        for pid, vec, pl in zip(ids, vectors, payloads)
    ]

    await client.upsert(collection_name=collection_name, points=points)
    logger.info("Qdrant upsert: collection=%s, count=%d", collection_name, len(points))
    return ids


async def search_vectors(
    collection_name: str,
    query_vector: list[float],
    top_k: int = 5,
    score_threshold: float = 0.5,
    filter_conditions: Optional[dict] = None,
) -> list[dict]:
    """向量相似度检索"""
    client = get_qdrant_client()

    query_filter = None
    if filter_conditions:
        conditions = []
        for key, value in filter_conditions.items():
            conditions.append(
                models.FieldCondition(
                    key=key,
                    match=models.MatchValue(value=value),
                )
            )
        query_filter = models.Filter(must=conditions)

    # 兼容新版 qdrant_client：优先使用 query_points，回退 search
    try:
        results = await client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=query_filter,
        )
        hits = results.points
    except (AttributeError, TypeError):
        results = await client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=query_filter,
        )
        hits = results

    return [
        {
            "id": hit.id,
            "score": hit.score,
            "payload": hit.payload,
        }
        for hit in hits
    ]


async def delete_vectors(
    collection_name: str,
    ids: list[str],
) -> None:
    """删除指定向量"""
    client = get_qdrant_client()
    await client.delete(collection_name=collection_name, points_selector=ids)
    logger.info("Qdrant delete: collection=%s, count=%d", collection_name, len(ids))


async def get_collection_info(collection_name: str) -> dict:
    """获取 Collection 信息"""
    client = get_qdrant_client()
    info = await client.get_collection(collection_name)
    return {
        "name": collection_name,
        "vectors_count": info.vectors_count,
        "points_count": info.points_count,
        "status": info.status,
    }
