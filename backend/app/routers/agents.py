from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core.security import get_current_active_user
from ..models import User
from ..services.legal_agents import (
    get_legal_agent_workflow,
    get_simple_qa
)

router = APIRouter(prefix="/agents", tags=["智能体"])


class CaseDescription(BaseModel):
    case_description: str


class Question(BaseModel):
    question: str


@router.post("/complex-analysis")
async def complex_analysis(
    data: CaseDescription,
    current_user: User = Depends(get_current_active_user)
):
    """复杂案件分析"""
    try:
        workflow = get_legal_agent_workflow()
        
        async def generate():
            async for state in workflow.run_streaming(data.case_description):
                yield f"data: {__import__('json').dumps(state, ensure_ascii=False)}\n\n"
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"分析失败: {str(e)}"
        )


@router.post("/simple-qa")
async def simple_qa(
    data: Question,
    current_user: User = Depends(get_current_active_user)
):
    """简单问答"""
    try:
        qa = get_simple_qa()
        answer = await qa.answer(data.question)
        return {"answer": answer}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"回答失败: {str(e)}"
        )


@router.post("/courtroom-simulation")
async def courtroom_simulation(
    data: CaseDescription,
    current_user: User = Depends(get_current_active_user)
):
    """法庭模拟"""
    try:
        workflow = get_legal_agent_workflow()
        
        async def generate():
            async for message in workflow.run_courtroom_simulation(data.case_description):
                yield f"data: {__import__('json').dumps(message, ensure_ascii=False)}\n\n"
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"模拟失败: {str(e)}"
        )
