from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import tempfile
import os

from ..core.security import get_current_active_user
from ..models import User
from ..services.legal_agents import (
    get_legal_agent_workflow,
    get_simple_qa
)
from ..services.document_parser import get_document_parser_service

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


@router.post("/upload-document")
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user)
):
    """上传文档并解析"""
    try:
        # 保存临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        try:
            # 解析文档
            parser = get_document_parser_service()
            if file.filename.endswith('.pdf'):
                result = parser.parse_pdf(temp_file_path)
            elif file.filename.endswith('.txt'):
                result = parser.parse_text(temp_file_path)
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="不支持的文件类型，仅支持PDF和TXT文件"
                )
            
            return result
        finally:
            # 清理临时文件
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文档解析失败: {str(e)}"
        )
