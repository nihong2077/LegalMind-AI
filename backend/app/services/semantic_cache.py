from typing import Optional, Dict, Any, List
import json
import time
import numpy as np
from sentence_transformers import SentenceTransformer
from app.core.redis_client import get_redis_client

class SemanticCache:
    """语义缓存系统"""
    
    def __init__(self):
        self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        self.redis_client = get_redis_client()
        self.cache_ttl = 7200  # 缓存过期时间（秒）- 延长至2小时
        self.similarity_threshold = 0.85  # 语义相似度阈值 - 提高精确度
        self.max_cache_size = 1000  # 最大缓存数量
    
    async def embed_text(self, text: str) -> List[float]:
        """将文本转换为向量"""
        return self.model.encode(text).tolist()
    
    async def calculate_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算两个向量的余弦相似度"""
        vec1_np = np.array(vec1)
        vec2_np = np.array(vec2)
        return float(np.dot(vec1_np, vec2_np) / (np.linalg.norm(vec1_np) * np.linalg.norm(vec2_np)))
    
    async def get_cache(self, query: str) -> Optional[Dict[str, Any]]:
        """根据语义相似度获取缓存"""
        query_embedding = await self.embed_text(query)
        
        # 从Redis获取所有缓存键
        keys = await self.redis_client.keys("semantic_cache:*")
        
        for key in keys:
            # 获取缓存数据
            cache_data = await self.redis_client.get(key)
            if cache_data:
                try:
                    data = json.loads(cache_data)
                    stored_embedding = data.get("embedding")
                    if stored_embedding:
                        # 计算相似度
                        similarity = await self.calculate_similarity(query_embedding, stored_embedding)
                        if similarity >= self.similarity_threshold:
                            return data.get("result")
                except Exception as e:
                    print(f"缓存解析错误: {e}")
        
        return None
    
    async def set_cache(self, query: str, result: Dict[str, Any]) -> None:
        """设置语义缓存"""
        # 检查缓存大小
        await self._check_cache_size()
        
        query_embedding = await self.embed_text(query)
        cache_data = {
            "embedding": query_embedding,
            "result": result,
            "query": query,
            "timestamp": time.time()
        }
        
        # 生成缓存键
        cache_key = f"semantic_cache:{hash(query) % 1000000}"
        
        # 存储到Redis
        await self.redis_client.setex(
            cache_key,
            self.cache_ttl,
            json.dumps(cache_data)
        )
    
    async def _check_cache_size(self) -> None:
        """检查并控制缓存大小"""
        keys = await self.redis_client.keys("semantic_cache:*")
        if len(keys) >= self.max_cache_size:
            # 删除最旧的缓存
            oldest_key = None
            oldest_time = float('inf')
            
            for key in keys:
                cache_data = await self.redis_client.get(key)
                if cache_data:
                    try:
                        data = json.loads(cache_data)
                        timestamp = data.get("timestamp", 0)
                        if timestamp < oldest_time:
                            oldest_time = timestamp
                            oldest_key = key
                    except Exception:
                        pass
            
            if oldest_key:
                await self.redis_client.delete(oldest_key)
    
    async def clear_cache(self) -> None:
        """清除所有语义缓存"""
        keys = await self.redis_client.keys("semantic_cache:*")
        if keys:
            await self.redis_client.delete(*keys)
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        keys = await self.redis_client.keys("semantic_cache:*")
        return {
            "cache_count": len(keys),
            "cache_ttl": self.cache_ttl,
            "similarity_threshold": self.similarity_threshold
        }

# 全局单例
semantic_cache = SemanticCache()