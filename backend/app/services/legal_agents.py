from typing import Dict, Any, List, Optional, AsyncGenerator
from langgraph.graph import StateGraph as Graph, END
from langchain_core.messages import HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
import logging

from ..core.llm_client import get_llm_client
from ..core.redis_client import get_redis_client
from .semantic_cache import semantic_cache

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LegalAgent:
    """法律智能体基类"""
    
    def __init__(self, name: str, role: str, system_prompt: str):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.llm = get_llm_client()
    
    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """运行智能体"""
        raise NotImplementedError
    
    async def generate_response(self, messages: List[Dict[str, Any]], **kwargs) -> str:
        """生成响应"""
        try:
            # 尝试从缓存获取
            cache_key = f"{self.role}:{hash(str(messages))}"
            cached_response = await semantic_cache.get(cache_key)
            if cached_response:
                logger.info(f"从缓存获取 {self.name} 的响应")
                return cached_response
            
            # 调用LLM生成响应
            response = await self.llm.chat(
                model="gpt-4o",
                messages=messages,
                temperature=0.7,
                **kwargs
            )
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # 缓存响应
            await semantic_cache.set(cache_key, content)
            
            return content
        except Exception as e:
            logger.error(f"{self.name} 生成响应时出错: {str(e)}")
            return f"Error: {str(e)}"


class CaseAnalystAgent(LegalAgent):
    """案情梳理智能体"""
    
    def __init__(self):
        system_prompt = """你是一名专业的法律案情分析师，擅长从复杂的案件描述中提取关键信息，梳理案件事实，识别法律关系和争议焦点。

请你：
1. 仔细分析用户提供的案件描述
2. 提取案件的核心事实要素（时间、地点、人物、事件经过等）
3. 识别涉案的法律关系和可能的法律问题
4. 归纳案件的争议焦点
5. 提出需要进一步澄清的事实问题
6. 评估案件的复杂度（1-100）

请以结构化的方式输出分析结果，确保逻辑清晰、层次分明。"""
        super().__init__("案情分析师", "analyst", system_prompt)
    
    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        case_description = context.get("case_description", "")
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"请分析以下案件：\n{case_description}"}
        ]
        
        analysis = await self.generate_response(messages)
        
        # 提取复杂度评分（简单实现，实际可以使用更复杂的方法）
        complexity_score = 50  # 默认复杂度
        
        return {
            "analyst_output": analysis,
            "complexity_score": complexity_score,
            "agent_name": self.name,
            "timestamp": context.get("timestamp", "")
        }


class PlaintiffLawyerAgent(LegalAgent):
    """原告律师智能体"""
    
    def __init__(self):
        system_prompt = """你是一名专业的原告律师，擅长构建证据链，论证诉求的合法性，预判对方可能的辩护策略。

请你：
1. 基于案件事实，构建原告的法律论证
2. 分析原告的诉讼请求是否合法合理
3. 识别支持原告诉求的法律法规和案例
4. 预判被告可能的辩护策略
5. 提出应对被告辩护的策略

请以专业、严谨的法律语言输出分析结果，确保论证充分、逻辑严密。"""
        super().__init__("原告律师", "plaintiff_lawyer", system_prompt)
    
    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        case_description = context.get("case_description", "")
        analyst_output = context.get("analyst_output", "")
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"基于以下案件事实和分析：\n案件事实：{case_description}\n案情分析：{analyst_output}\n\n请作为原告律师，分析原告的诉讼请求和策略。"}
        ]
        
        analysis = await self.generate_response(messages)
        
        return {
            "plaintiff_output": analysis,
            "agent_name": self.name,
            "timestamp": context.get("timestamp", "")
        }


class DefendantLawyerAgent(LegalAgent):
    """被告律师智能体"""
    
    def __init__(self):
        system_prompt = """你是一名专业的被告律师，擅长寻找控方漏洞，提出有力的辩护意见。

请你：
1. 基于案件事实，分析原告起诉的漏洞和弱点
2. 构建被告的辩护策略
3. 识别支持被告辩护的法律法规和案例
4. 对原告的证据链提出质疑
5. 提出有利于被告的事实和法律依据

请以专业、严谨的法律语言输出分析结果，确保论证充分、逻辑严密。"""
        super().__init__("被告律师", "defendant_lawyer", system_prompt)
    
    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        case_description = context.get("case_description", "")
        analyst_output = context.get("analyst_output", "")
        plaintiff_output = context.get("plaintiff_output", "")
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"基于以下案件事实和分析：\n案件事实：{case_description}\n案情分析：{analyst_output}\n原告律师分析：{plaintiff_output}\n\n请作为被告律师，分析被告的辩护策略。"}
        ]
        
        analysis = await self.generate_response(messages)
        
        return {
            "defendant_output": analysis,
            "agent_name": self.name,
            "timestamp": context.get("timestamp", "")
        }


class JudgeAgent(LegalAgent):
    """法官智能体"""
    
    def __init__(self):
        system_prompt = """你是一名公正、专业的法官，擅长综合双方意见，基于法律和事实做出中立的评判。

请你：
1. 综合案件事实和双方律师的意见
2. 基于法律法规和相关案例进行分析
3. 对案件的争议焦点做出判断
4. 提出最终的裁判意见
5. 说明裁判的法律依据和理由

请以中立、客观的语言输出分析结果，确保裁判公正、法律适用正确。"""
        super().__init__("法官", "judge", system_prompt)
    
    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        case_description = context.get("case_description", "")
        analyst_output = context.get("analyst_output", "")
        plaintiff_output = context.get("plaintiff_output", "")
        defendant_output = context.get("defendant_output", "")
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"基于以下案件事实和双方律师的意见：\n案件事实：{case_description}\n案情分析：{analyst_output}\n原告律师意见：{plaintiff_output}\n被告律师意见：{defendant_output}\n\n请作为法官，做出最终的裁判意见。"}
        ]
        
        analysis = await self.generate_response(messages)
        
        return {
            "judge_output": analysis,
            "agent_name": self.name,
            "timestamp": context.get("timestamp", "")
        }


class MediatorAgent(LegalAgent):
    """调解员智能体"""
    
    def __init__(self):
        system_prompt = """你是一名专业的法律调解员，擅长分析案件争议，提出公平合理的和解方案，促进双方达成庭外和解。

请你：
1. 综合案件事实和双方律师的意见
2. 分析双方的核心诉求和利益点
3. 识别可能的和解空间和妥协点
4. 提出具体、可行的和解方案
5. 说明和解方案的公平性和合理性
6. 提供和解协议的主要条款建议

请以中立、专业的语言输出和解方案，确保方案公平合理、切实可行。"""
        super().__init__("调解员", "mediator", system_prompt)
    
    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        case_description = context.get("case_description", "")
        analyst_output = context.get("analyst_output", "")
        plaintiff_output = context.get("plaintiff_output", "")
        defendant_output = context.get("defendant_output", "")
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"基于以下案件事实和双方律师的意见：\n案件事实：{case_description}\n案情分析：{analyst_output}\n原告律师意见：{plaintiff_output}\n被告律师意见：{defendant_output}\n\n请作为调解员，提出公平合理的和解方案。"}
        ]
        
        analysis = await self.generate_response(messages)
        
        return {
            "mediator_output": analysis,
            "agent_name": self.name,
            "timestamp": context.get("timestamp", "")
        }


class LegalAgentWorkflow:
    """法律智能体工作流"""
    
    def __init__(self):
        self.agents = {
            "analyst": CaseAnalystAgent(),
            "plaintiff_lawyer": PlaintiffLawyerAgent(),
            "defendant_lawyer": DefendantLawyerAgent(),
            "judge": JudgeAgent(),
            "mediator": MediatorAgent()
        }
        self.graph = self._build_graph()
    
    def _build_graph(self) -> Graph:
        """构建LangGraph工作流"""
        graph = Graph()
        
        # 定义节点
        graph.add_node("analyze_case", self._analyze_case)
        graph.add_node("plaintiff_lawyer", self._run_plaintiff_lawyer)
        graph.add_node("defendant_lawyer", self._run_defendant_lawyer)
        graph.add_node("judge", self._run_judge)
        graph.add_node("mediator", self._run_mediator)
        graph.add_node("finalize", self._finalize)
        
        # 定义边
        graph.add_edge("analyze_case", "plaintiff_lawyer")
        graph.add_edge("plaintiff_lawyer", "defendant_lawyer")
        graph.add_edge("defendant_lawyer", "judge")
        graph.add_edge("judge", "mediator")
        graph.add_edge("mediator", "finalize")
        graph.add_edge("finalize", END)
        
        # 设置入口点
        graph.set_entry_point("analyze_case")
        
        return graph
    
    async def _analyze_case(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """分析案件"""
        try:
            logger.info("开始分析案件")
            agent = self.agents["analyst"]
            result = await agent.run(state)
            logger.info("案件分析完成")
            return {**state, **result}
        except Exception as e:
            logger.error(f"案件分析失败: {str(e)}")
            return {**state, "error": f"案件分析失败: {str(e)}"}
    
    async def _run_plaintiff_lawyer(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """运行原告律师智能体"""
        try:
            logger.info("开始运行原告律师智能体")
            agent = self.agents["plaintiff_lawyer"]
            result = await agent.run(state)
            logger.info("原告律师智能体运行完成")
            return {**state, **result}
        except Exception as e:
            logger.error(f"原告律师智能体运行失败: {str(e)}")
            return {**state, "error": f"原告律师智能体运行失败: {str(e)}"}
    
    async def _run_defendant_lawyer(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """运行被告律师智能体"""
        try:
            logger.info("开始运行被告律师智能体")
            agent = self.agents["defendant_lawyer"]
            result = await agent.run(state)
            logger.info("被告律师智能体运行完成")
            return {**state, **result}
        except Exception as e:
            logger.error(f"被告律师智能体运行失败: {str(e)}")
            return {**state, "error": f"被告律师智能体运行失败: {str(e)}"}
    
    async def _run_judge(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """运行法官智能体"""
        try:
            logger.info("开始运行法官智能体")
            agent = self.agents["judge"]
            result = await agent.run(state)
            logger.info("法官智能体运行完成")
            return {**state, **result}
        except Exception as e:
            logger.error(f"法官智能体运行失败: {str(e)}")
            return {**state, "error": f"法官智能体运行失败: {str(e)}"}
    
    async def _run_mediator(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """运行调解员智能体"""
        try:
            logger.info("开始运行调解员智能体")
            agent = self.agents["mediator"]
            result = await agent.run(state)
            logger.info("调解员智能体运行完成")
            return {**state, **result}
        except Exception as e:
            logger.error(f"调解员智能体运行失败: {str(e)}")
            return {**state, "error": f"调解员智能体运行失败: {str(e)}"}
    
    async def _finalize(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """最终处理"""
        try:
            logger.info("开始最终处理")
            # 生成总结
            summary = "# 案件分析总结\n\n"
            summary += f"## 案情分析\n{state.get('analyst_output', '')}\n\n"
            summary += f"## 原告律师意见\n{state.get('plaintiff_output', '')}\n\n"
            summary += f"## 被告律师意见\n{state.get('defendant_output', '')}\n\n"
            summary += f"## 法官裁判意见\n{state.get('judge_output', '')}\n\n"
            summary += f"## 调解员和解方案\n{state.get('mediator_output', '')}\n\n"
            
            # 添加案件信息
            summary += f"## 案件信息\n"
            summary += f"- 复杂度评分: {state.get('complexity_score', 0)}\n"
            summary += f"- 处理时间: {state.get('timestamp', '')}\n"
            
            state["summary"] = summary
            logger.info("最终处理完成")
            return state
        except Exception as e:
            logger.error(f"最终处理失败: {str(e)}")
            return {**state, "error": f"最终处理失败: {str(e)}"}
    
    async def run(self, case_description: str) -> Dict[str, Any]:
        """运行完整工作流"""
        from datetime import datetime
        from app.services.input_validator import input_validator
        from app.services.output_auditor import output_auditor
        
        try:
            logger.info("开始运行法律智能体工作流")
            
            # 验证输入
            input_validator.validate_input({"case_description": case_description})
            sanitized_input = input_validator.sanitize_input(case_description)
            
            initial_state = {
                "case_description": sanitized_input,
                "timestamp": datetime.now().isoformat(),
                "step": "开始"
            }
            
            result = await self.graph.ainvoke(initial_state)
            
            # 审核输出
            for key, value in result.items():
                if isinstance(value, str) and "_output" in key:
                    audit_result = await output_auditor.audit_output(value, result)
                    result[key] = audit_result["modified_output"]
                    result[f"{key}_audit"] = audit_result
            
            logger.info("法律智能体工作流运行完成")
            return result
        except Exception as e:
            logger.error(f"工作流运行失败: {str(e)}")
            return {"error": f"工作流运行失败: {str(e)}"}
    
    async def run_streaming(self, case_description: str) -> AsyncGenerator[Dict[str, Any], None]:
        """流式运行工作流"""
        from datetime import datetime
        from app.services.input_validator import input_validator
        from app.services.output_auditor import output_auditor
        
        try:
            logger.info("开始流式运行法律智能体工作流")
            
            # 验证输入
            input_validator.validate_input({"case_description": case_description})
            sanitized_input = input_validator.sanitize_input(case_description)
            
            initial_state = {
                "case_description": sanitized_input,
                "timestamp": datetime.now().isoformat(),
                "step": "开始"
            }
            
            # 流式执行工作流
            async for state in self.graph.astream(initial_state):
                # 审核输出
                for key, value in state.items():
                    if isinstance(value, str) and "_output" in key:
                        audit_result = await output_auditor.audit_output(value, state)
                        state[key] = audit_result["modified_output"]
                        state[f"{key}_audit"] = audit_result
                
                yield state
            
            logger.info("流式工作流运行完成")
        except Exception as e:
            logger.error(f"流式工作流运行失败: {str(e)}")
            yield {"error": f"流式工作流运行失败: {str(e)}"}


# 全局单例
_legal_agent_workflow: Optional[LegalAgentWorkflow] = None


def get_legal_agent_workflow() -> LegalAgentWorkflow:
    """获取法律智能体工作流"""
    global _legal_agent_workflow
    if _legal_agent_workflow is None:
        _legal_agent_workflow = LegalAgentWorkflow()
    return _legal_agent_workflow
