import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from qdrant_client.models import PointStruct
from sentence_transformers import SentenceTransformer

from ..core.qdrant_client import get_qdrant_client


class KnowledgeBaseService:
    """知识库服务"""
    
    def __init__(self):
        self.qdrant_client = get_qdrant_client()
        # 使用 sentence-transformers 作为向量模型
        self.vector_model = SentenceTransformer('all-MiniLM-L6-v2')
        self.vector_size = 384  # all-MiniLM-L6-v2 的向量维度
    
    async def create_collection(self, collection_name: str) -> bool:
        """创建知识库集合"""
        return await self.qdrant_client.create_collection(
            collection_name=collection_name,
            vector_size=self.vector_size
        )
    
    def split_text(self, text: str, doc_type: str = "general") -> List[Dict[str, Any]]:
        """文本分块
        
        采用结构感知分块策略，根据文档类型进行不同的分块
        """
        chunks = []
        
        if doc_type == "law":
            # 法律法规分块 - 按条/款/项
            chunks = self._split_law_text(text)
        elif doc_type == "judgment":
            # 裁判文书分块 - 按段落
            chunks = self._split_judgment_text(text)
        elif doc_type == "contract":
            # 合同文件分块 - 按条款
            chunks = self._split_contract_text(text)
        else:
            # 通用分块 - 按段落
            chunks = self._split_general_text(text)
        
        # 对每个块生成父块和子块
        processed_chunks = []
        for i, chunk in enumerate(chunks):
            # 父块
            parent_chunk = {
                "id": f"parent_{i}",
                "type": "parent",
                "content": chunk["content"],
                "metadata": {
                    "doc_type": doc_type,
                    "chunk_type": "parent",
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "created_at": datetime.now().isoformat(),
                    **chunk.get("metadata", {})
                }
            }
            processed_chunks.append(parent_chunk)
            
            # 生成子块
            child_chunks = self._generate_child_chunks(chunk["content"], parent_id=parent_chunk["id"])
            processed_chunks.extend(child_chunks)
        
        return processed_chunks
    
    def _split_law_text(self, text: str) -> List[Dict[str, Any]]:
        """法律法规分块"""
        chunks = []
        # 匹配条文结构：第一条、第二条等
        pattern = r'(第[一二三四五六七八九十百千]+条|第\d+条)'
        sections = re.split(pattern, text)
        
        for i in range(1, len(sections), 2):
            title = sections[i]
            content = sections[i+1].strip() if i+1 < len(sections) else ""
            if content:
                chunks.append({
                    "content": f"{title} {content}",
                    "metadata": {"section_title": title}
                })
        
        return chunks
    
    def _split_judgment_text(self, text: str) -> List[Dict[str, Any]]:
        """裁判文书分块"""
        # 按段落分块
        paragraphs = text.split('\n\n')
        chunks = []
        
        for i, para in enumerate(paragraphs):
            para = para.strip()
            if para:
                chunks.append({
                    "content": para,
                    "metadata": {"paragraph_index": i}
                })
        
        return chunks
    
    def _split_contract_text(self, text: str) -> List[Dict[str, Any]]:
        """合同文件分块"""
        chunks = []
        # 匹配合同条款：第一条、1.1、第一条第一款等
        pattern = r'(第[一二三四五六七八九十百千]+条|\d+\.\d+|第[一二三四五六七八九十百千]+条第[一二三四五六七八九十]款)'
        sections = re.split(pattern, text)
        
        for i in range(1, len(sections), 2):
            title = sections[i]
            content = sections[i+1].strip() if i+1 < len(sections) else ""
            if content:
                chunks.append({
                    "content": f"{title} {content}",
                    "metadata": {"clause_title": title}
                })
        
        return chunks
    
    def _split_general_text(self, text: str) -> List[Dict[str, Any]]:
        """通用文本分块"""
        # 按段落分块，控制块大小
        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk = ""
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            if len(current_chunk) + len(para) < 1000:
                current_chunk += " " + para
            else:
                if current_chunk:
                    chunks.append({"content": current_chunk.strip()})
                current_chunk = para
        
        if current_chunk:
            chunks.append({"content": current_chunk.strip()})
        
        return chunks
    
    def _generate_child_chunks(self, content: str, parent_id: str) -> List[Dict[str, Any]]:
        """生成子块"""
        child_chunks = []
        # 按句子分割生成子块
        sentences = re.split(r'[。！？.!?]', content)
        
        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if sentence and len(sentence) > 20:
                child_chunks.append({
                    "id": f"child_{parent_id}_{i}",
                    "type": "child",
                    "content": sentence,
                    "metadata": {
                        "chunk_type": "child",
                        "parent_id": parent_id,
                        "sentence_index": i
                    }
                })
        
        return child_chunks
    
    def vectorize_text(self, text: str) -> List[float]:
        """文本向量化"""
        return self.vector_model.encode(text).tolist()
    
    async def add_document(self, collection_name: str, text: str, doc_type: str = "general", metadata: Optional[Dict[str, Any]] = None) -> bool:
        """添加文档到知识库"""
        # 文本分块
        chunks = self.split_text(text, doc_type)
        
        # 向量化并准备点
        points = []
        for i, chunk in enumerate(chunks):
            vector = self.vectorize_text(chunk["content"])
            chunk_metadata = chunk.get("metadata", {})
            if metadata:
                chunk_metadata.update(metadata)
            
            point = PointStruct(
                id=i,
                vector=vector,
                payload={
                    "content": chunk["content"],
                    "type": chunk["type"],
                    **chunk_metadata
                }
            )
            points.append(point)
        
        # 插入到 Qdrant
        return await self.qdrant_client.upsert_points(collection_name, points)
    
    async def search(self, collection_name: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """搜索知识库"""
        # 向量化查询
        query_vector = self.vectorize_text(query)
        
        # 搜索
        results = await self.qdrant_client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=limit
        )
        
        return results
    
    async def delete_document(self, collection_name: str, doc_id: str) -> bool:
        """删除文档"""
        # 根据 doc_id 过滤删除
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        filter_query = Filter(
            must=[
                FieldCondition(
                    key="metadata.doc_id",
                    match=MatchValue(value=doc_id)
                )
            ]
        )
        
        return await self.qdrant_client.delete_points(
            collection_name=collection_name,
            filter_query=filter_query
        )
    
    async def get_collection_stats(self, collection_name: str) -> Optional[Dict[str, Any]]:
        """获取集合统计信息"""
        return await self.qdrant_client.get_collection_info(collection_name)


# 全局单例
_knowledge_base_service: Optional[KnowledgeBaseService] = None


def get_knowledge_base_service() -> KnowledgeBaseService:
    """获取知识库服务"""
    global _knowledge_base_service
    if _knowledge_base_service is None:
        _knowledge_base_service = KnowledgeBaseService()
    return _knowledge_base_service
