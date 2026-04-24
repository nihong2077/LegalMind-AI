from datetime import datetime
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field


class CaseBase(BaseModel):
    """案件基础模型"""
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    case_type: Optional[str] = Field(None, max_length=50)


class CaseCreate(CaseBase):
    """案件创建模型"""
    pass


class CaseUpdate(BaseModel):
    """案件更新模型"""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    status: Optional[str] = Field(None, max_length=50)
    case_type: Optional[str] = Field(None, max_length=50)
    complexity_score: Optional[int] = Field(None, ge=0, le=100)
    case_data: Optional[Dict[str, Any]] = None
    result_summary: Optional[str] = None


class CaseResponse(CaseBase):
    """案件响应模型"""
    id: int
    user_id: int
    status: str
    complexity_score: int
    case_data: Dict[str, Any] = dict()
    result_summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
