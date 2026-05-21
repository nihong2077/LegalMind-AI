import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

JUDGE_SYSTEM_PROMPT = """你是一位资深法官，主持中国民事案件的庭审辩论流程。你的职责包括：

1. **流程控制**：决定发言顺序，引导双方围绕争议焦点展开辩论
2. **焦点归纳**：从双方陈述中提炼核心争议焦点，确保辩论不偏离主题
3. **事实认定**：基于证据和双方陈述，认定关键法律事实
4. **裁决意见**：在辩论结束后，综合双方观点和法律规定，给出裁决意见
5. **法律引用**：引用《中华人民共和国民法典》《民事诉讼法》等具体法条

输出格式要求：
- 归纳争议焦点时，用【争议焦点】标记
- 认定事实时，用【事实认定】标记
- 给出裁决意见时，用【裁决意见】标记
- 引用法条时标注法律全称和条号

请保持中立、公正，严格依据法律和事实作出判断。"""


class JudgeSkill:
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.system_prompt = JUDGE_SYSTEM_PROMPT

    async def preside_opening(self, plaintiff_claim: str, defendant_response: str = "") -> str:
        """开庭主持：归纳争议焦点，确定辩论方向"""
        prompt = f"""请作为法官主持本次庭审的开庭阶段。

原告诉求：
{plaintiff_claim}

被告回应：
{defendant_response or "（被告尚未回应）"}

请完成以下工作：
1. 归纳本案的核心争议焦点（2-4个）
2. 确定辩论顺序和需要查明的事实
3. 提示双方围绕焦点展开辩论"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def evaluate_round(
        self,
        plaintiff_arg: str,
        defendant_arg: str,
        focus_points: str,
        round_num: int,
    ) -> str:
        """评估本轮辩论，给出法官点评和下一轮指引"""
        prompt = f"""请作为法官评估第 {round_num} 轮辩论。

争议焦点：
{focus_points}

原告本轮陈述：
{plaintiff_arg}

被告本轮陈述：
{defendant_arg}

请完成以下工作：
1. 点评双方本轮辩论的要点和不足
2. 指出需要进一步查明的事实
3. 给出下一轮辩论的指引方向"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def render_verdict(
        self,
        plaintiff_args: list[str],
        defendant_args: list[str],
        kfe: dict,
        focus_points: str,
    ) -> str:
        """辩论结束后，综合所有信息给出最终裁决意见"""
        plaintiff_summary = "\n---\n".join(plaintiff_args) if plaintiff_args else "（无）"
        defendant_summary = "\n---\n".join(defendant_args) if defendant_args else "（无）"

        prompt = f"""请作为法官，在辩论结束后作出最终裁决意见。

争议焦点：
{focus_points}

关键法律事实（KFE）：
{json.dumps(kfe, ensure_ascii=False, indent=2)}

原告全部陈述：
{plaintiff_summary}

被告全部陈述：
{defendant_summary}

请完成以下工作：
1. 【事实认定】基于证据和辩论，认定本案关键事实
2. 【法律适用】引用具体法条，说明适用的法律依据
3. 【裁决意见】给出明确的裁决结论，包括责任认定、赔偿计算等
4. 【判决要点】列出判决的关键词和要点清单"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def preside_opening_stream(self, plaintiff_claim: str, defendant_response: str = ""):
        prompt = f"""请作为法官主持本次庭审的开庭阶段。

原告诉求：
{plaintiff_claim}

被告回应：
{defendant_response or "（被告尚未回应）"}

请完成以下工作：
1. 归纳本案的核心争议焦点（2-4个）
2. 确定辩论顺序和需要查明的事实
3. 提示双方围绕焦点展开辩论"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content

    async def render_verdict_stream(
        self,
        plaintiff_args: list[str],
        defendant_args: list[str],
        kfe: dict,
        focus_points: str,
    ):
        plaintiff_summary = "\n---\n".join(plaintiff_args) if plaintiff_args else "（无）"
        defendant_summary = "\n---\n".join(defendant_args) if defendant_args else "（无）"

        prompt = f"""请作为法官，在辩论结束后作出最终裁决意见。

争议焦点：
{focus_points}

关键法律事实（KFE）：
{json.dumps(kfe, ensure_ascii=False, indent=2)}

原告全部陈述：
{plaintiff_summary}

被告全部陈述：
{defendant_summary}

请完成以下工作：
1. 【事实认定】基于证据和辩论，认定本案关键事实
2. 【法律适用】引用具体法条，说明适用的法律依据
3. 【裁决意见】给出明确的裁决结论，包括责任认定、赔偿计算等
4. 【判决要点】列出判决的关键词和要点清单"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
