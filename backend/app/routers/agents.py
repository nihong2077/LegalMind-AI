from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import json

from ..core.database import get_db
from ..core.security import get_current_active_user
from ..models import User
from ..schemas import CaseCreate, CaseResponse
from ..services.legal_agents import get_legal_agent_workflow
from ..services.knowledge_base import get_knowledge_base_service
from ..services.document_parser import get_document_parser_service

router = APIRouter(prefix="/agents", tags=["智能体"])


@router.post("/analyze-case")
async def analyze_case(
    case_description: str,
    current_user: User = Depends(get_current_active_user),
):
    """分析案件 - 运行完整的法律智能体工作流"""
    try:
        workflow = get_legal_agent_workflow()
        result = await workflow.run(case_description)
        
        return {
            "success": True,
            "data": result,
            "message": "案件分析完成"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"分析案件失败: {str(e)}"
        )


@router.post("/analyze-case/stream")
async def analyze_case_stream(
    case_description: str,
    current_user: User = Depends(get_current_active_user),
):
    """分析案件 - 流式输出"""
    async def stream_response():
        try:
            workflow = get_legal_agent_workflow()
            
            # 模拟流式输出
            steps = ["案情分析", "原告律师分析", "被告律师分析", "法官裁判"]
            
            for step in steps:
                yield f"event: step\ndata: {json.dumps({"step": step, "status": "开始"})}\n\n"
                await asyncio.sleep(1)  # 模拟处理时间
            
            # 运行完整工作流
            result = await workflow.run(case_description)
            
            for step in steps:
                if step == "案情分析" and "analyst_output" in result:
                    yield f"event: analyst\ndata: {json.dumps({"content": result["analyst_output"]})}\n\n"
                elif step == "原告律师分析" and "plaintiff_output" in result:
                    yield f"event: plaintiff\ndata: {json.dumps({"content": result["plaintiff_output"]})}\n\n"
                elif step == "被告律师分析" and "defendant_output" in result:
                    yield f"event: defendant\ndata: {json.dumps({"content": result["defendant_output"]})}\n\n"
                elif step == "法官裁判" and "judge_output" in result:
                    yield f"event: judge\ndata: {json.dumps({"content": result["judge_output"]})}\n\n"
                await asyncio.sleep(0.5)
            
            yield f"event: complete\ndata: {json.dumps({"success": True, "message": "分析完成"})}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({"error": str(e)})}\n\n"
    
    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream"
    )


@router.post("/knowledge-base/add")
async def add_to_knowledge_base(
    text: str,
    doc_type: str = "general",
    metadata: dict = None,
    current_user: User = Depends(get_current_active_user),
):
    """添加文档到知识库"""
    try:
        kb_service = get_knowledge_base_service()
        success = await kb_service.add_document(
            collection_name="legal_knowledge",
            text=text,
            doc_type=doc_type,
            metadata=metadata
        )
        
        if success:
            return {
                "success": True,
                "message": "文档已添加到知识库"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="添加文档失败"
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加文档失败: {str(e)}"
        )


@router.get("/knowledge-base/search")
async def search_knowledge_base(
    query: str,
    limit: int = 5,
    current_user: User = Depends(get_current_active_user),
):
    """搜索知识库"""
    try:
        kb_service = get_knowledge_base_service()
        results = await kb_service.search(
            collection_name="legal_knowledge",
            query=query,
            limit=limit
        )
        
        return {
            "success": True,
            "data": results
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"搜索知识库失败: {str(e)}"
        )


@router.post("/document/parse")
async def parse_document(
    file_path: str,
    current_user: User = Depends(get_current_active_user),
):
    """解析文档"""
    try:
        parser = get_document_parser_service()
        result = parser.smart_parse(file_path)
        
        if result.get("success"):
            return {
                "success": True,
                "data": result
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"解析文档失败: {result.get('error', '未知错误')}"
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"解析文档失败: {str(e)}"
        )
