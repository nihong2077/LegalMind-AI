from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

LEGAL_ANALYZER_SYSTEM = """你是一位专业的法律分析师，擅长民事法律场景分析。
你的职责包括：
1. 分析案件事实，识别关键法律关系
2. 梳理法律依据，引用相关法条
3. 评估诉讼风险，给出专业建议
4. 识别合同条款中的风险点

请用专业但易懂的语言回答，必要时引用具体法条编号。"""


class LegalAnalyzer:
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.system_prompt = LEGAL_ANALYZER_SYSTEM

    async def analyze(self, query: str, context: str = "") -> str:
        messages = [SystemMessage(content=self.system_prompt)]
        if context:
            messages.append(SystemMessage(content=f"参考材料：\n{context}"))
        messages.append(HumanMessage(content=query))
        response = await self.llm.ainvoke(messages)
        return response.content

    async def analyze_stream(self, query: str, context: str = ""):
        messages = [SystemMessage(content=self.system_prompt)]
        if context:
            messages.append(SystemMessage(content=f"参考材料：\n{context}"))
        messages.append(HumanMessage(content=query))
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
