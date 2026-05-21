from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

REGULATORY_RESEARCHER_SYSTEM = """你是一位法律检索研究员，精通中国法律法规体系。
你的职责包括：
1. 根据案件事实检索适用的法律法规
2. 查找相关司法解释和指导性案例
3. 分析法律条文的适用条件和例外情形
4. 梳理法律依据的效力层级

检索结果请按以下格式输出：
- 法律名称及条文编号
- 条文核心内容摘要
- 与本案的关联性说明
- 效力层级（法律/行政法规/司法解释/部门规章）"""


class RegulatoryResearcher:
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.system_prompt = REGULATORY_RESEARCHER_SYSTEM

    async def research(self, query: str, area: str = "") -> str:
        messages = [SystemMessage(content=self.system_prompt)]
        if area:
            messages.append(SystemMessage(content=f"重点检索领域：{area}"))
        messages.append(HumanMessage(content=query))
        response = await self.llm.ainvoke(messages)
        return response.content

    async def research_stream(self, query: str, area: str = ""):
        messages = [SystemMessage(content=self.system_prompt)]
        if area:
            messages.append(SystemMessage(content=f"重点检索领域：{area}"))
        messages.append(HumanMessage(content=query))
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
