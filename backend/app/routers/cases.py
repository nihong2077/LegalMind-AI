from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from ..core.database import get_db
from ..core.security import get_current_active_user
from ..models import User, Case
from ..schemas import (
    CaseCreate,
    CaseUpdate,
    CaseResponse,
)

router = APIRouter(prefix="/cases", tags=["案件"])


@router.get("", response_model=List[CaseResponse])
async def get_cases(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的案件列表"""
    query = select(Case).where(Case.user_id == current_user.id)
    
    if status:
        query = query.where(Case.status == status)
    
    query = query.order_by(desc(Case.updated_at)).offset(skip).limit(limit)
    result = await db.execute(query)
    cases = result.scalars().all()
    
    return cases


@router.get("/{case_id}", response_model=CaseResponse)
async def get_case(
    case_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """获取指定案件详情"""
    result = await db.execute(
        select(Case).where(
            Case.id == case_id,
            Case.user_id == current_user.id
        )
    )
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案件不存在",
        )
    
    return case


@router.post("", response_model=CaseResponse, status_code=status.HTTP_201_CREATED)
async def create_case(
    case_data: CaseCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """创建新案件"""
    db_case = Case(
        user_id=current_user.id,
        title=case_data.title,
        description=case_data.description,
        case_type=case_data.case_type,
        status="draft",
    )
    
    db.add(db_case)
    await db.commit()
    await db.refresh(db_case)
    
    return db_case


@router.put("/{case_id}", response_model=CaseResponse)
async def update_case(
    case_id: int,
    case_data: CaseUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """更新案件"""
    result = await db.execute(
        select(Case).where(
            Case.id == case_id,
            Case.user_id == current_user.id
        )
    )
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案件不存在",
        )
    
    # 更新字段
    update_data = case_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(case, field, value)
    
    await db.commit()
    await db.refresh(case)
    
    return case


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case(
    case_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """删除案件"""
    result = await db.execute(
        select(Case).where(
            Case.id == case_id,
            Case.user_id == current_user.id
        )
    )
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="案件不存在",
        )
    
    await db.delete(case)
    await db.commit()
