from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from app.services.llm_evaluator import llm_evaluator
from app.services.legal_agents import get_legal_agent_workflow

router = APIRouter()

@router.post("/evaluate/response")
async def evaluate_response(
    query: str,
    response: str,
    context: Dict[str, Any] = None
) -> Dict[str, Any]:
    """评估单个响应"""
    try:
        result = await llm_evaluator.evaluate_response(query, response, context)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"评估失败: {str(e)}")

@router.post("/evaluate/workflow")
async def evaluate_workflow(case_description: str) -> Dict[str, Any]:
    """评估完整工作流"""
    try:
        # 先运行工作流
        workflow = get_legal_agent_workflow()
        workflow_result = await workflow.run(case_description)
        
        # 然后评估结果
        evaluation = await llm_evaluator.evaluate_agent_workflow(case_description, workflow_result)
        
        return {
            "workflow_result": workflow_result,
            "evaluation": evaluation
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"评估失败: {str(e)}")