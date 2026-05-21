import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

MEDIATOR_SYSTEM_PROMPT = """你是一位专业的法律调解员，擅长促成民事纠纷的和解。你的职责包括：

1. **利益分析**：分析双方的核心利益和底线，寻找共同点
2. **方案设计**：设计公平合理的调解方案，平衡双方利益
3. **法律框架**：在法律规定框架内提出调解建议
4. **风险评估**：帮助双方评估诉讼与调解的利弊
5. **执行保障**：设计可执行的调解协议条款

输出格式要求：
- 分析利益时，用【利益分析】标记
- 提出方案时，用【调解方案】标记
- 风险评估时，用【风险评估】标记
- 协议条款时，用【协议条款】标记

请保持中立，以促成和解为目标，同时确保方案合法合规。"""


class MediatorSkill:
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.system_prompt = MEDIATOR_SYSTEM_PROMPT

    async def propose_mediation(
        self,
        plaintiff_position: str,
        defendant_position: str,
        case_facts: str,
        kfe: dict,
    ) -> str:
        """基于双方立场和案件事实，提出调解方案"""
        prompt = f"""请作为调解员，为以下案件提出调解方案。

案件事实：
{case_facts}

关键法律事实：
{json.dumps(kfe, ensure_ascii=False, indent=2)}

原告立场：
{plaintiff_position}

被告立场：
{defendant_position}

请完成以下工作：
1. 【利益分析】分析双方的核心利益、底线和可能的让步空间
2. 【调解方案】提出2-3个具体的调解方案选项
3. 【风险评估】分析如果调解失败进入诉讼，双方各自面临的风险
4. 【协议条款】草拟调解协议的核心条款框架"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def evaluate_settlement(
        self,
        proposed_settlement: str,
        plaintiff_response: str,
        defendant_response: str,
    ) -> str:
        """评估双方对调解方案的反馈，调整方案"""
        prompt = f"""请作为调解员，评估双方对调解方案的反馈。

调解方案：
{proposed_settlement}

原告反馈：
{plaintiff_response}

被告反馈：
{defendant_response}

请完成以下工作：
1. 分析双方分歧的核心原因
2. 提出调整后的调解方案
3. 给出促成和解的具体建议"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def propose_mediation_stream(
        self,
        plaintiff_position: str,
        defendant_position: str,
        case_facts: str,
        kfe: dict,
    ):
        prompt = f"""请作为调解员，为以下案件提出调解方案。

案件事实：
{case_facts}

关键法律事实：
{json.dumps(kfe, ensure_ascii=False, indent=2)}

原告立场：
{plaintiff_position}

被告立场：
{defendant_position}

请完成以下工作：
1. 【利益分析】分析双方的核心利益、底线和可能的让步空间
2. 【调解方案】提出2-3个具体的调解方案选项
3. 【风险评估】分析如果调解失败进入诉讼，双方各自面临的风险
4. 【协议条款】草拟调解协议的核心条款框架"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
