from typing import List, Optional, Dict, Any
from qdrant_client import QdrantClient, models
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter

from .config import settings


class VectorStore:
    """Qdrant向量数据库客户端"""
    
    def __init__(self, url: Optional[str] = None):
        self.url = url or settings.QDRANT_URL
        self.client = QdrantClient(url=self.url)
        self.default_collection = "legal_knowledge"
        
    async def create_collection(
        self,
        collection_name: str,
        vector_size: int = 1024,
        distance: Distance = Distance.COSINE,
    ) -> bool:
        """创建向量集合"""
        try:
            if not self.client.collection_exists(collection_name):
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=vector_size,
                        distance=distance,
                    ),
                )
            return True
        except Exception as e:
            print(f"创建集合失败: {e}")
            return False
    
    async def delete_collection(self, collection_name: str) -> bool:
        """删除向量集合"""
        try:
            if self.client.collection_exists(collection_name):
                self.client.delete_collection(collection_name=collection_name)
            return True
        except Exception as e:
            print(f"删除集合失败: {e}")
            return False
    
    async def upsert_points(
        self,
        collection_name: str,
        points: List[PointStruct],
    ) -> bool:
        """插入或更新向量点"""
        try:
            self.client.upsert(
                collection_name=collection_name,
                points=points,
            )
            return True
        except Exception as e:
            print(f"插入向量点失败: {e}")
            return False
    
    async def search(
        self,
        collection_name: str,
        query_vector: List[float],
        limit: int = 10,
        filter_query: Optional[Filter] = None,
    ) -> List[Dict[str, Any]]:
        """搜索相似向量"""
        try:
            results = self.client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter=filter_query,
            )
            return [
                {
                    "id": result.id,
                    "score": result.score,
                    "payload": result.payload,
                }
                for result in results
            ]
        except Exception as e:
            print(f"搜索向量失败: {e}")
            return []
    
    async def delete_points(
        self,
        collection_name: str,
        point_ids: Optional[List[int]] = None,
        filter_query: Optional[Filter] = None,
    ) -> bool:
        """删除向量点"""
        try:
            if point_ids:
                self.client.delete(
                    collection_name=collection_name,
                    points_selector=models.PointIdsList(
                        points=point_ids,
                    ),
                )
            elif filter_query:
                self.client.delete(
                    collection_name=collection_name,
                    points_selector=models.FilterSelector(
                        filter=filter_query,
                    ),
                )
            return True
        except Exception as e:
            print(f"删除向量点失败: {e}")
            return False
    
    async def get_collection_info(self, collection_name: str) -> Optional[Dict[str, Any]]:
        """获取集合信息"""
        try:
            info = self.client.get_collection(collection_name)
            return {
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status,
            }
        except Exception as e:
            print(f"获取集合信息失败: {e}")
            return None
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            # 尝试列出集合来检查连接
            self.client.get_collections()
            return True
        except Exception as e:
            print(f"Qdrant健康检查失败: {e}")
            return False


# 全局单例
_qdrant_client: Optional[VectorStore] = None


def get_qdrant_client() -> VectorStore:
    """获取Qdrant客户端"""
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = VectorStore()
    return _qdrant_client


async def close_qdrant_client():
    """关闭Qdrant客户端"""
    global _qdrant_client
    if _qdrant_client is not None:
        _qdrant_client = None
