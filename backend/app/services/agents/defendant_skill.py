from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

DEFENDANT_SYSTEM_PROMPT = """你是一位专业的被告代理律师，擅长从被告立场出发进行法律抗辩。你的职责包括：

1. **事实抗辩**：对原告陈述的事实进行质疑和反驳，提出对被告有利的事实版本
2. **法律抗辩**：引用相关法条，论证被告行为不构成违约/侵权，或责任应减轻
3. **证据质疑**：指出原告证据的不足、矛盾或证明力问题
4. **反诉主张**：如适用，提出反诉请求和依据
5. **减责论证**：论证即使存在责任，也应减轻或免除

输出格式要求：
- 抗辩事实时，用【事实抗辩】标记
- 引用法条时，用【法律抗辩】标记，标注法律全称和条号
- 质疑证据时，用【证据质疑】标记
- 提出反诉时，用【反诉请求】标记

请以被告代理律师身份，为当事人争取最大合法权益。"""


class DefendantSkill:
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.system_prompt = DEFENDANT_SYSTEM_PROMPT

    async def opening_statement(self, case_facts: str, plaintiff_claim: str, focus_points: str = "") -> str:
        """被告律师开庭陈述"""
        prompt = f"""请作为被告代理律师进行开庭陈述。

案件事实：
{case_facts}

原告诉求：
{plaintiff_claim}

{"争议焦点：" + focus_points if focus_points else ""}

请完成以下工作：
1. 【事实抗辩】陈述对被告有利的案件事实版本
2. 【法律抗辩】引用相关法条，论证被告不构成违约/侵权或责任应减轻
3. 【证据质疑】指出原告诉求中的证据不足或矛盾之处"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def rebuttal(
        self,
        plaintiff_arg: str,
        case_facts: str,
        round_num: int,
    ) -> str:
        """被告律师反驳原告陈述"""
        prompt = f"""请作为被告代理律师，对原告第 {round_num} 轮陈述进行反驳。

案件事实：
{case_facts}

原告本轮陈述：
{plaintiff_arg}

请完成以下工作：
1. 【事实抗辩】逐条反驳原告的不实陈述
2. 【法律抗辩】补充支持被告立场的法条和司法解释
3. 【证据质疑】指出原告证据链中的薄弱环节"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def final_statement(self, all_plaintiff_args: list[str], case_facts: str) -> str:
        """被告律师最后陈述"""
        plaintiff_summary = "\n---\n".join(all_plaintiff_args) if all_plaintiff_args else "（无）"
        prompt = f"""请作为被告代理律师进行最后陈述。

案件事实：
{case_facts}

原告全部陈述摘要：
{plaintiff_summary}

请完成以下工作：
1. 总结被告的核心抗辩主张
2. 指出原告陈述中的主要矛盾和漏洞
3. 重申被告的最终立场和请求"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def opening_statement_stream(self, case_facts: str, plaintiff_claim: str, focus_points: str = ""):
        prompt = f"""请作为被告代理律师进行开庭陈述。

案件事实：
{case_facts}

原告诉求：
{plaintiff_claim}

{"争议焦点：" + focus_points if focus_points else ""}

请完成以下工作：
1. 【事实抗辩】陈述对被告有利的案件事实版本
2. 【法律抗辩】引用相关法条，论证被告不构成违约/侵权或责任应减轻
3. 【证据质疑】指出原告诉求中的证据不足或矛盾之处"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content

    async def rebuttal_stream(
        self,
        plaintiff_arg: str,
        case_facts: str,
        round_num: int,
    ):
        prompt = f"""请作为被告代理律师，对原告第 {round_num} 轮陈述进行反驳。

案件事实：
{case_facts}

原告本轮陈述：
{plaintiff_arg}

请完成以下工作：
1. 【事实抗辩】逐条反驳原告的不实陈述
2. 【法律抗辩】补充支持被告立场的法条和司法解释
3. 【证据质疑】指出原告证据链中的薄弱环节"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
