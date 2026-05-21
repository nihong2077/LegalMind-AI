from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

PLAINTIFF_SYSTEM_PROMPT = """你是一位专业的原告代理律师，擅长从原告立场出发进行法律论证。你的职责包括：

1. **事实陈述**：清晰陈述对原告有利的案件事实，突出对方违约/侵权要点
2. **法律论证**：引用相关法条，论证原告主张的合法性和合理性
3. **证据运用**：结合已有证据，构建完整的证据链
4. **诉求量化**：明确原告的诉讼请求，包括赔偿金额、履行要求等
5. **反驳预判**：预判被告可能的抗辩理由，提前准备应对策略

输出格式要求：
- 陈述事实时，用【事实陈述】标记
- 引用法条时，用【法律依据】标记，标注法律全称和条号
- 提出诉求时，用【诉讼请求】标记
- 反驳对方时，用【反驳意见】标记

请以原告代理律师身份，为当事人争取最大合法权益。"""


class PlaintiffSkill:
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.system_prompt = PLAINTIFF_SYSTEM_PROMPT

    async def opening_statement(self, case_facts: str, focus_points: str = "") -> str:
        """原告律师开庭陈述"""
        prompt = f"""请作为原告代理律师进行开庭陈述。

案件事实：
{case_facts}

{"争议焦点：" + focus_points if focus_points else ""}

请完成以下工作：
1. 【事实陈述】清晰陈述对原告有利的案件事实
2. 【法律依据】引用相关法条，论证被告的违约/侵权责任
3. 【诉讼请求】明确原告的全部诉讼请求"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def rebuttal(
        self,
        defendant_arg: str,
        case_facts: str,
        round_num: int,
    ) -> str:
        """原告律师反驳被告陈述"""
        prompt = f"""请作为原告代理律师，对被告第 {round_num} 轮陈述进行反驳。

案件事实：
{case_facts}

被告本轮陈述：
{defendant_arg}

请完成以下工作：
1. 【反驳意见】逐条反驳被告的不实陈述和法律错误
2. 【法律依据】补充支持原告立场的法条和司法解释
3. 【证据强调】重申对原告有利的关键证据"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def final_statement(self, all_defendant_args: list[str], case_facts: str) -> str:
        """原告律师最后陈述"""
        defendant_summary = "\n---\n".join(all_defendant_args) if all_defendant_args else "（无）"
        prompt = f"""请作为原告代理律师进行最后陈述。

案件事实：
{case_facts}

被告全部陈述摘要：
{defendant_summary}

请完成以下工作：
1. 总结原告的核心主张和论据
2. 指出被告陈述中的主要矛盾和漏洞
3. 重申原告的最终诉讼请求"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def opening_statement_stream(self, case_facts: str, focus_points: str = ""):
        prompt = f"""请作为原告代理律师进行开庭陈述。

案件事实：
{case_facts}

{"争议焦点：" + focus_points if focus_points else ""}

请完成以下工作：
1. 【事实陈述】清晰陈述对原告有利的案件事实
2. 【法律依据】引用相关法条，论证被告的违约/侵权责任
3. 【诉讼请求】明确原告的全部诉讼请求"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content

    async def rebuttal_stream(
        self,
        defendant_arg: str,
        case_facts: str,
        round_num: int,
    ):
        prompt = f"""请作为原告代理律师，对被告第 {round_num} 轮陈述进行反驳。

案件事实：
{case_facts}

被告本轮陈述：
{defendant_arg}

请完成以下工作：
1. 【反驳意见】逐条反驳被告的不实陈述和法律错误
2. 【法律依据】补充支持原告立场的法条和司法解释
3. 【证据强调】重申对原告有利的关键证据"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
