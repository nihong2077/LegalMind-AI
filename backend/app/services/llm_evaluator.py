from typing import Dict, Any, List, Tuple
from app.core.llm_client import get_llm_client

class LLMEvaluator:
    """LLM自动评估体系"""
    
    def __init__(self):
        self.llm = get_llm_client()
        self.evaluation_criteria = [
            "accuracy",      # 准确性
            "relevance",     # 相关性
            "completeness",  # 完整性
            "coherence",     # 连贯性
            "professionalism", # 专业性
            "ethicality"     # 伦理性
        ]
    
    async def evaluate_response(self, query: str, response: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """评估LLM响应"""
        evaluation_prompt = self._generate_evaluation_prompt(query, response, context)
        
        messages = [
            {"role": "system", "content": self._get_evaluator_system_prompt()},
            {"role": "user", "content": evaluation_prompt}
        ]
        
        try:
            eval_response = await self.llm.chat(
                model="gpt-4o",
                messages=messages,
                temperature=0.3
            )
            
            eval_content = eval_response.get("choices", [{}])[0].get("message", {}).get("content", "")
            return self._parse_evaluation(eval_content)
        except Exception as e:
            return {
                "error": str(e),
                "scores": {criteria: 0 for criteria in self.evaluation_criteria},
                "overall_score": 0,
                "feedback": "评估失败"
            }
    
    def _get_evaluator_system_prompt(self) -> str:
        """获取评估器系统提示"""
        return """你是一名专业的法律AI评估专家，负责评估法律智能体的响应质量。

请你基于以下标准评估响应：
1. 准确性（Accuracy）：响应是否基于正确的法律知识和事实
2. 相关性（Relevance）：响应是否与用户查询直接相关
3. 完整性（Completeness）：响应是否全面覆盖了问题的各个方面
4. 连贯性（Coherence）：响应是否逻辑清晰、结构合理
5. 专业性（Professionalism）：响应是否使用专业、严谨的法律语言
6. 伦理性（Ethicality）：响应是否符合法律伦理和职业道德

评估要求：
- 为每个标准给出1-5分的评分（5分最高）
- 计算总体评分（所有标准的平均值）
- 提供详细的评估反馈，说明评分理由
- 输出格式：JSON格式，包含scores对象（各标准评分）、overall_score（总体评分）和feedback（详细反馈）"""
    
    def _generate_evaluation_prompt(self, query: str, response: str, context: Dict[str, Any] = None) -> str:
        """生成评估提示"""
        prompt = f"用户查询：{query}\n\nAI响应：{response}\n"
        if context:
            prompt += f"\n上下文信息：{context}\n"
        prompt += "\n请根据评估标准对上述响应进行评估，并以JSON格式输出评估结果。"
        return prompt
    
    def _parse_evaluation(self, eval_content: str) -> Dict[str, Any]:
        """解析评估结果"""
        import json
        try:
            # 提取JSON部分
            start_idx = eval_content.find('{')
            end_idx = eval_content.rfind('}') + 1
            if start_idx != -1 and end_idx != -1:
                json_str = eval_content[start_idx:end_idx]
                result = json.loads(json_str)
                
                # 验证结果格式
                if "scores" in result and "overall_score" in result and "feedback" in result:
                    return result
        except Exception as e:
            print(f"解析评估结果失败: {e}")
        
        # 解析失败时返回默认值
        return {
            "scores": {criteria: 0 for criteria in self.evaluation_criteria},
            "overall_score": 0,
            "feedback": "评估结果解析失败"
        }
    
    async def evaluate_agent_workflow(self, case_description: str, workflow_result: Dict[str, Any]) -> Dict[str, Any]:
        """评估智能体工作流结果"""
        evaluations = {}
        
        # 评估案情分析师
        if "analyst_output" in workflow_result:
            evaluations["analyst"] = await self.evaluate_response(
                case_description,
                workflow_result["analyst_output"]
            )
        
        # 评估原告律师
        if "plaintiff_output" in workflow_result:
            evaluations["plaintiff_lawyer"] = await self.evaluate_response(
                case_description,
                workflow_result["plaintiff_output"],
                {"analyst_output": workflow_result.get("analyst_output", "")}
            )
        
        # 评估被告律师
        if "defendant_output" in workflow_result:
            evaluations["defendant_lawyer"] = await self.evaluate_response(
                case_description,
                workflow_result["defendant_output"],
                {
                    "analyst_output": workflow_result.get("analyst_output", ""),
                    "plaintiff_output": workflow_result.get("plaintiff_output", "")
                }
            )
        
        # 评估法官
        if "judge_output" in workflow_result:
            evaluations["judge"] = await self.evaluate_response(
                case_description,
                workflow_result["judge_output"],
                {
                    "analyst_output": workflow_result.get("analyst_output", ""),
                    "plaintiff_output": workflow_result.get("plaintiff_output", ""),
                    "defendant_output": workflow_result.get("defendant_output", "")
                }
            )
        
        # 评估调解员
        if "mediator_output" in workflow_result:
            evaluations["mediator"] = await self.evaluate_response(
                case_description,
                workflow_result["mediator_output"],
                {
                    "analyst_output": workflow_result.get("analyst_output", ""),
                    "plaintiff_output": workflow_result.get("plaintiff_output", ""),
                    "defendant_output": workflow_result.get("defendant_output", ""),
                    "judge_output": workflow_result.get("judge_output", "")
                }
            )
        
        # 计算总体评估
        overall_scores = []
        for agent, eval_result in evaluations.items():
            if "overall_score" in eval_result:
                overall_scores.append(eval_result["overall_score"])
        
        overall_score = sum(overall_scores) / len(overall_scores) if overall_scores else 0
        
        return {
            "agent_evaluations": evaluations,
            "overall_score": overall_score,
            "timestamp": workflow_result.get("timestamp", "")
        }

# 全局单例
llm_evaluator = LLMEvaluator()