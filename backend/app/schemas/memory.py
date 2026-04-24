from datetime import datetime
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field


class MemoryBase(BaseModel):
    """记忆基础模型"""
    content: str = Field(..., min_length=1)
    memory_type: str = Field("general", max_length=50)
    metadata: Dict[str, Any] = dict()
    relevance_score: int = Field(50, ge=0, le=100)


class MemoryCreate(MemoryBase):
    """记忆创建模型"""
    case_id: Optional[int] = None


class MemoryUpdate(BaseModel):
    """记忆更新模型"""
    content: Optional[str] = Field(None, min_length=1)
    memory_type: Optional[str] = Field(None, max_length=50)
    metadata: Optional[Dict[str, Any]] = None
    relevance_score: Optional[int] = Field(None, ge=0, le=100)
    is_active: Optional[bool] = None


class MemoryResponse(MemoryBase):
    """记忆响应模型"""
    id: int
    user_id: int
    case_id: Optional[int] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
