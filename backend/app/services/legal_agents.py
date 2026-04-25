from typing import Dict, Any, List, Optional
from langgraph.graph import Graph, END
from langchain_core.messages import HumanMessage, AIMessage
from langchain_openai import ChatOpenAI

from ..core.llm_client import get_llm_client


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
            response = await self.llm.chat(
                model="gpt-4o",
                messages=messages,
                temperature=0.7,
                **kwargs
            )
            return response.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
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

请以结构化的方式输出分析结果，确保逻辑清晰、层次分明。"""
        super().__init__("案情分析师", "analyst", system_prompt)
    
    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        case_description = context.get("case_description", "")
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"请分析以下案件：\n{case_description}"}
        ]
        
        analysis = await self.generate_response(messages)
        
        return {
            "analyst_output": analysis,
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


class LegalAgentWorkflow:
    """法律智能体工作流"""
    
    def __init__(self):
        self.agents = {
            "analyst": CaseAnalystAgent(),
            "plaintiff_lawyer": PlaintiffLawyerAgent(),
            "defendant_lawyer": DefendantLawyerAgent(),
            "judge": JudgeAgent()
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
        
        # 定义边
        graph.add_edge("analyze_case", "plaintiff_lawyer")
        graph.add_edge("plaintiff_lawyer", "defendant_lawyer")
        graph.add_edge("defendant_lawyer", "judge")
        graph.add_edge("judge", END)
        
        # 设置入口点
        graph.set_entry_point("analyze_case")
        
        return graph
    
    async def _analyze_case(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """分析案件"""
        agent = self.agents["analyst"]
        result = await agent.run(state)
        return {**state, **result}
    
    async def _run_plaintiff_lawyer(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """运行原告律师智能体"""
        agent = self.agents["plaintiff_lawyer"]
        result = await agent.run(state)
        return {**state, **result}
    
    async def _run_defendant_lawyer(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """运行被告律师智能体"""
        agent = self.agents["defendant_lawyer"]
        result = await agent.run(state)
        return {**state, **result}
    
    async def _run_judge(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """运行法官智能体"""
        agent = self.agents["judge"]
        result = await agent.run(state)
        return {**state, **result}
    
    async def run(self, case_description: str) -> Dict[str, Any]:
        """运行完整工作流"""
        from datetime import datetime
        
        initial_state = {
            "case_description": case_description,
            "timestamp": datetime.now().isoformat()
        }
        
        result = await self.graph.ainvoke(initial_state)
        return result


# 全局单例
_legal_agent_workflow: Optional[LegalAgentWorkflow] = None


def get_legal_agent_workflow() -> LegalAgentWorkflow:
    """获取法律智能体工作流"""
    global _legal_agent_workflow
    if _legal_agent_workflow is None:
        _legal_agent_workflow = LegalAgentWorkflow()
    return _legal_agent_workflow
