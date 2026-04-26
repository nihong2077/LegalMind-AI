from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from app.services.legal_agents import get_legal_agent_workflow

# 延迟导入语义缓存，避免服务启动时卡在模型下载
semantic_cache = None

def get_semantic_cache():
    global semantic_cache
    if semantic_cache is None:
        try:
            from app.services.semantic_cache import semantic_cache as sc
            semantic_cache = sc
        except Exception as e:
            print(f"初始化语义缓存失败: {e}")
            # 创建一个简单的内存缓存作为降级方案
            class SimpleCache:
                def __init__(self):
                    self.cache = {}
                async def get_cache(self, query: str):
                    return None
                async def set_cache(self, query: str, result: Dict[str, Any]):
                    pass
            semantic_cache = SimpleCache()
    return semantic_cache

router = APIRouter()

async def route_request(query: str) -> Dict[str, Any]:
    """根据语义内容路由请求"""
    # 先检查语义缓存
    cached_result = await semantic_cache.get_cache(query)
    if cached_result:
        return {
            "result": cached_result,
            "source": "cache"
        }
    
    # 运行法律智能体工作流
    workflow = get_legal_agent_workflow()
    result = await workflow.run(query)
    
    # 缓存结果
    await semantic_cache.set_cache(query, result)
    
    return {
        "result": result,
        "source": "agent"
    }

@router.post("/query")
async def process_query(query: str) -> Dict[str, Any]:
    """处理用户查询"""
    try:
        result = await route_request(query)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理查询失败: {str(e)}")

@router.get("/cache/stats")
async def get_cache_stats() -> Dict[str, Any]:
    """获取缓存统计信息"""
    return await semantic_cache.get_cache_stats()

@router.post("/cache/clear")
async def clear_cache() -> Dict[str, Any]:
    """清除缓存"""
    await semantic_cache.clear_cache()
    return {"message": "缓存已清除"}