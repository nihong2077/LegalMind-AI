from typing import Optional, Dict, Any, List
import json
import time
import numpy as np
from app.core.redis_client import get_redis

class SemanticCache:
    """语义缓存系统"""
    
    def __init__(self):
        self.model = None
        self.redis_client = None
        self.cache_ttl = 7200  # 缓存过期时间（秒）- 延长至2小时
        self.similarity_threshold = 0.85  # 语义相似度阈值 - 提高精确度
        self.max_cache_size = 1000  # 最大缓存数量
        self._init_model()
        self._init_redis()
    
    def _init_redis(self):
        """初始化Redis客户端"""
        try:
            self.redis_client = get_redis()
        except Exception as e:
            print(f"Redis初始化失败: {e}")
            self.redis_client = None
    
    def _init_model(self):
        """初始化模型"""
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        except Exception as e:
            print(f"模型初始化失败: {e}")
            self.model = None
    
    async def embed_text(self, text: str) -> List[float]:
        """将文本转换为向量"""
        if not self.model:
            # 如果模型未初始化，返回简单的哈希值作为向量
            return [hash(text) % 1000 / 1000 for _ in range(384)]
        return self.model.encode(text).tolist()
    
    async def calculate_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算两个向量的余弦相似度"""
        vec1_np = np.array(vec1)
        vec2_np = np.array(vec2)
        return float(np.dot(vec1_np, vec2_np) / (np.linalg.norm(vec1_np) * np.linalg.norm(vec2_np)))
    
    async def get_cache(self, query: str) -> Optional[Dict[str, Any]]:
        """根据语义相似度获取缓存"""
        if not self.redis_client:
            return None
            
        query_embedding = await self.embed_text(query)
        
        try:
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
        except Exception as e:
            print(f"获取缓存失败: {e}")
        
        return None
    
    async def set_cache(self, query: str, result: Dict[str, Any]) -> None:
        """设置语义缓存"""
        if not self.redis_client:
            return
            
        try:
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
        except Exception as e:
            print(f"设置缓存失败: {e}")
    
    async def _check_cache_size(self) -> None:
        """检查并控制缓存大小"""
        if not self.redis_client:
            return
            
        try:
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
        except Exception as e:
            print(f"检查缓存大小失败: {e}")
    
    async def clear_cache(self) -> None:
        """清除所有语义缓存"""
        if not self.redis_client:
            return
            
        try:
            keys = await self.redis_client.keys("semantic_cache:*")
            if keys:
                await self.redis_client.delete(*keys)
        except Exception as e:
            print(f"清除缓存失败: {e}")
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        if not self.redis_client:
            return {
                "cache_count": 0,
                "cache_ttl": self.cache_ttl,
                "similarity_threshold": self.similarity_threshold,
                "redis_available": False
            }
            
        try:
            keys = await self.redis_client.keys("semantic_cache:*")
            return {
                "cache_count": len(keys),
                "cache_ttl": self.cache_ttl,
                "similarity_threshold": self.similarity_threshold,
                "redis_available": True
            }
        except Exception as e:
            print(f"获取缓存统计失败: {e}")
            return {
                "cache_count": 0,
                "cache_ttl": self.cache_ttl,
                "similarity_threshold": self.similarity_threshold,
                "redis_available": False
            }

# 全局单例
semantic_cache = SemanticCache()