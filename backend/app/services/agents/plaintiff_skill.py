"""
原告律师 Skill — 专业维护原告立场，兼顾论证可信度

核心设计原则：
1. 立场坚定：优先维护原告利益，对不利事实进行弱化或重新解读
2. 选择性引用：优先检索和引用支持原告诉求的法条、司法解释、指导案例
3. 有力反驳：对被告论点进行针对性反驳，揭露矛盾和漏洞
4. 适度承认：对无争议的事实可适当承认，以增强在争议事实上的说服力
5. 辩论记忆：接收完整辩论历史，保持论证连贯性
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

PLAINTIFF_SYSTEM_PROMPT = """你是一位经验丰富的原告代理律师，你的核心目标是为原告争取最大利益。

## 基本规则

### 立场坚定
- 你是原告的代理人，你的立场始终与原告一致
- 对原告不利的事实应尽量弱化或重新解读，而非简单承认
- 对原告不利的法条应尽量通过适用条件、例外条款等角度进行限制性解读
- 对被告论点应持审慎质疑态度，但可以有限度地承认无争议的事实以增强说服力

### 法条引用规则
- 优先引用支持原告诉求的法条和司法解释
- 对原告不利的法条，应通过限制性解读来削弱其影响，而非回避
- 引用法条时必须标注法律全称和条号，增强说服力
- 优先引用：司法解释 > 指导案例 > 法律条文

### 反驳策略
- 对被告的主要论点，应提出有针对性的反驳理由
- 攻击对方证据的关联性、合法性、真实性
- 揭露对方论证中的逻辑矛盾
- 用对原告有利的事实重新解读对方提出的证据
- 如果对方引用了对原告不利的法条，应从适用条件、例外条款、司法解释等角度进行反驳
- 承认无争议的事实可以增强你在争议事实上的说服力

### 证据运用
- 对原告有利的证据：充分展开，强调其证明力
- 对原告不利的证据：质疑其真实性、关联性或合法性
- 对于确实不利但无法推翻的证据，可以承认其存在但强调其证明力有限或与核心争议无关
- 证据不足时：主张举证责任在对方，对方未尽举证义务应承担不利后果

## 输出格式
- 【事实陈述】优先陈述对原告有利的事实版本，对不利事实进行弱化或重新解读
- 【法律依据】优先引用支持原告立场的法条（标注法律全称和条号），对不利法条进行限制性解读
- 【反驳意见】有理有据地反驳对方主要论点
- 【证据分析】强调有利证据，质疑不利证据，对无法推翻的不利证据可承认其存在但强调其局限性
- 【诉讼请求】明确、具体、最大化原告利益"""


class PlaintiffSkill:
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.system_prompt = PLAINTIFF_SYSTEM_PROMPT

    def _build_debate_history(
        self,
        plaintiff_args: list[str] | None = None,
        defendant_args: list[str] | None = None,
        max_rounds: int = 3,
    ) -> str:
        """构建辩论历史上下文，保持论证连贯"""
        if not plaintiff_args and not defendant_args:
            return ""
        parts = []
        rounds = min(len(plaintiff_args or []), len(defendant_args or []), max_rounds)
        for i in range(rounds):
            p_arg = (plaintiff_args or [])[i] if i < len(plaintiff_args or []) else ""
            d_arg = (defendant_args or [])[i] if i < len(defendant_args or []) else ""
            if p_arg:
                parts.append(f"第{i+1}轮-原告方：{p_arg[:800]}")
            if d_arg:
                parts.append(f"第{i+1}轮-被告方：{d_arg[:800]}")
        # 处理原告多一轮的情况（原告先发言）
        if plaintiff_args and len(plaintiff_args) > rounds:
            parts.append(f"第{rounds+1}轮-原告方：{plaintiff_args[rounds][:800]}")
        return "\n".join(parts)

    async def opening_statement(
        self,
        case_facts: str,
        focus_points: str = "",
        legal_knowledge: str = "",
    ) -> str:
        """原告律师开庭陈述"""
        law_section = ""
        if legal_knowledge:
            law_section = f"\n可引用的法律知识（只选取对原告有利的部分）：\n{legal_knowledge[:2000]}"

        prompt = f"""请作为原告代理律师进行开庭陈述。记住：你的核心职责是为原告争取最大利益。

案件事实：
{case_facts}

{"争议焦点：" + focus_points if focus_points else ""}
{law_section}

请完成以下工作：
1. 【事实陈述】优先陈述对原告有利的案件事实版本，突出被告的违约/侵权行为，对不利事实进行弱化或重新解读
2. 【法律依据】优先引用支持原告诉求的法条和司法解释（标注法律全称和条号），对不利法条应通过限制性解读削弱其影响
3. 【证据分析】强调对原告有利的证据及其证明力
4. 【诉讼请求】明确原告的全部诉讼请求，争取最大利益

重要提醒：你是原告律师，应坚定维护原告立场，对不利法条通过限制性解读来应对。"""
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
        plaintiff_args: list[str] | None = None,
        defendant_args: list[str] | None = None,
        judge_comment: str = "",
        legal_knowledge: str = "",
    ) -> str:
        """原告律师反驳被告陈述（增强版：辩论历史+法官点评+防反水）"""
        debate_history = self._build_debate_history(plaintiff_args, defendant_args)
        history_section = ""
        if debate_history:
            history_section = f"\n前几轮辩论记录（保持论证连贯，不要重复已提出的论点）：\n{debate_history}"

        judge_section = ""
        if judge_comment:
            judge_section = f"\n法官点评（注意回应法官关注的问题，但立场不变）：\n{judge_comment[:500]}"

        law_section = ""
        if legal_knowledge:
            law_section = f"\n可引用的法律知识（只选取对原告有利的部分）：\n{legal_knowledge[:1500]}"

        prompt = f"""请作为原告代理律师，对被告第 {round_num} 轮陈述进行有理有据地反驳。

案件事实：
{case_facts}
{history_section}
{judge_section}
{law_section}

被告本轮陈述：
{defendant_arg}

请完成以下工作：
1. 【反驳意见】有理有据地反驳被告的主要论点，揭露其逻辑漏洞、事实错误和法律适用错误
2. 【法律依据】优先引用支持原告立场的法条和司法解释（标注法律全称和条号），如果被告引用了对原告不利的法条，应从适用条件、例外条款角度进行限制性解读
3. 【证据分析】强调对原告有利的关键证据，质疑被告证据的证明力
4. 【新论点】如有可能，提出新的对原告有利的论据（每轮至少一个新角度）

注意事项：
- 应聚焦于对原告不利的论据进行反驳，对无争议的事实可适当承认
- 对不利的法条应通过限制性解读来削弱其影响
- 应尽力维护原告的诉讼请求"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def final_statement(
        self,
        all_defendant_args: list[str],
        case_facts: str,
        plaintiff_args: list[str] | None = None,
        judge_comments: list[str] | None = None,
    ) -> str:
        """原告律师最后陈述（增强版）"""
        defendant_summary = "\n---\n".join(all_defendant_args[-3:]) if all_defendant_args else "（无）"
        plaintiff_summary = ""
        if plaintiff_args:
            plaintiff_summary = f"\n原告历轮论点回顾：\n" + "\n---\n".join(plaintiff_args[-3:])
        judge_section = ""
        if judge_comments:
            judge_section = f"\n法官历轮点评：\n" + "\n---\n".join(judge_comments[-3:])

        prompt = f"""请作为原告代理律师进行最后陈述。这是你最后的发言机会，应全力为原告争取。

案件事实：
{case_facts}

{plaintiff_summary}

被告全部陈述摘要：
{defendant_summary}
{judge_section}

请完成以下工作：
1. 总结原告的核心主张和全部论据，强调最有力的论点
2. 系统性指出被告陈述中的矛盾、漏洞和逻辑错误
3. 有理有据地反驳被告的核心抗辩
4. 重申原告的最终诉讼请求

提醒：应坚定维护原告立场，对无争议的事实可适当承认以增强说服力。"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    # ----------------------------------------------------------
    # 流式输出方法
    # ----------------------------------------------------------

    async def opening_statement_stream(
        self,
        case_facts: str,
        focus_points: str = "",
        legal_knowledge: str = "",
    ):
        law_section = ""
        if legal_knowledge:
            law_section = f"\n可引用的法律知识（只选取对原告有利的部分）：\n{legal_knowledge[:2000]}"

        prompt = f"""请作为原告代理律师进行开庭陈述。记住：你的核心职责是为原告争取最大利益。

案件事实：
{case_facts}

{"争议焦点：" + focus_points if focus_points else ""}
{law_section}

请完成以下工作：
1. 【事实陈述】优先陈述对原告有利的案件事实版本，突出被告的违约/侵权行为，对不利事实进行弱化或重新解读
2. 【法律依据】优先引用支持原告诉求的法条和司法解释（标注法律全称和条号），对不利法条应通过限制性解读削弱其影响
3. 【证据分析】强调对原告有利的证据及其证明力
4. 【诉讼请求】明确原告的全部诉讼请求，争取最大利益

重要提醒：你是原告律师，应坚定维护原告立场，对不利法条通过限制性解读来应对。"""
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
        plaintiff_args: list[str] | None = None,
        defendant_args: list[str] | None = None,
        judge_comment: str = "",
        legal_knowledge: str = "",
    ):
        debate_history = self._build_debate_history(plaintiff_args, defendant_args)
        history_section = ""
        if debate_history:
            history_section = f"\n前几轮辩论记录（保持论证连贯，不要重复已提出的论点）：\n{debate_history}"

        judge_section = ""
        if judge_comment:
            judge_section = f"\n法官点评（注意回应法官关注的问题，但立场不变）：\n{judge_comment[:500]}"

        law_section = ""
        if legal_knowledge:
            law_section = f"\n可引用的法律知识（只选取对原告有利的部分）：\n{legal_knowledge[:1500]}"

        prompt = f"""请作为原告代理律师，对被告第 {round_num} 轮陈述进行有理有据地反驳。

案件事实：
{case_facts}
{history_section}
{judge_section}
{law_section}

被告本轮陈述：
{defendant_arg}

请完成以下工作：
1. 【反驳意见】有理有据地反驳被告的主要论点，揭露其逻辑漏洞、事实错误和法律适用错误
2. 【法律依据】优先引用支持原告立场的法条和司法解释（标注法律全称和条号），如果被告引用了对原告不利的法条，应从适用条件、例外条款角度进行限制性解读
3. 【证据分析】强调对原告有利的关键证据，质疑被告证据的证明力
4. 【新论点】如有可能，提出新的对原告有利的论据（每轮至少一个新角度）

注意事项：
- 应聚焦于对原告不利的论据进行反驳，对无争议的事实可适当承认
- 对不利的法条应通过限制性解读来削弱其影响
- 应尽力维护原告的诉讼请求"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
