from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

CONTRACT_REVIEWER_SYSTEM = """你是一位资深合同审查专家，专注于民事合同的风险审查。
你的职责包括：
1. 逐条审查合同条款，标注风险等级（高/中/低）
2. 识别不公平条款、模糊表述和潜在陷阱
3. 检查合同完整性（必备条款是否齐全）
4. 提出修改建议，保护当事人合法权益

审查时请按以下格式输出：
- 条款编号及内容摘要
- 风险等级：🔴高 / 🟡中 / 🟢低
- 风险说明
- 修改建议"""


class ContractReviewer:
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.system_prompt = CONTRACT_REVIEWER_SYSTEM

    async def review(self, contract_text: str) -> str:
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=f"请审查以下合同：\n\n{contract_text}"),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def review_stream(self, contract_text: str):
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=f"请审查以下合同：\n\n{contract_text}"),
        ]
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
