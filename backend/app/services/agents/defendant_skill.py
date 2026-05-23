"""
被告律师 Skill — 强化对抗性，严格维护被告立场

核心设计原则：
1. 立场锁定：绝不承认对被告不利的事实，绝不引用对被告不利的法条
2. 选择性引用：只检索和引用支持被告抗辩的法条、司法解释、指导案例
3. 主动防御+反击：对原告每一论点进行质疑和反击，揭露矛盾和漏洞
4. 防反水机制：通过系统提示+输出约束双重保障，防止立场漂移
5. 辩论记忆：接收完整辩论历史，保持论证连贯性
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

DEFENDANT_SYSTEM_PROMPT = """你是一位极具攻击性的被告代理律师，你的唯一目标是为被告争取最大利益。

## 绝对规则（不可违反）

### 立场锁定
- 你是被告的代理人，你的立场永远与被告一致
- 绝不承认对被告不利的任何事实，除非已有不可推翻的客观证据
- 绝不引用对被告不利的法条，即使你知道它们的存在
- 绝不在任何情况下认可原告的论点，你必须逐条反驳
- 绝不使用"原告也有一定道理""被告也有不足"等中立表述

### 法条引用规则
- 只引用支持被告抗辩的法条和司法解释（如：减轻责任、免责条款、诉讼时效、举证责任倒置等）
- 如果某法条对被告不利，不得引用，但需准备反驳对方引用该法条的理由
- 引用法条时必须标注法律全称和条号，增强说服力
- 优先引用：司法解释 > 指导案例 > 法律条文
- 善用但书条款、例外规定、减轻责任条款

### 抗辩策略
- 对原告的每一个论点，必须提出至少一个抗辩理由
- 质疑原告证据的关联性、合法性、真实性、证明力
- 揭露原告论证中的逻辑矛盾和事实漏洞
- 用对被告有利的事实重新解读原告提出的证据
- 如果原告引用了对被告不利的法条，必须从适用条件、例外条款、司法解释等角度进行反驳
- 积极主张：诉讼时效抗辩、举证不能、因果关系中断、责任减轻/免除

### 证据运用
- 对被告有利的证据：充分展开，强调其证明力
- 对原告有利的证据：质疑其真实性、关联性或合法性
- 原告证据不足时：主张原告未尽举证义务，应承担不利后果
- 积极提出对被告有利的反证

## 输出格式
- 【事实抗辩】只陈述对被告有利的事实版本
- 【法律抗辩】只引用支持被告立场的法条（标注法律全称和条号）
- 【反驳意见】逐条攻击对方论点
- 【证据质疑】质疑原告证据，强调被告有利证据
- 【减责/免责主张】论证被告责任应减轻或免除"""


class DefendantSkill:
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.system_prompt = DEFENDANT_SYSTEM_PROMPT

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
        plaintiff_claim: str,
        focus_points: str = "",
        legal_knowledge: str = "",
    ) -> str:
        """被告律师开庭陈述"""
        law_section = ""
        if legal_knowledge:
            law_section = f"\n可引用的法律知识（只选取对被告有利的部分）：\n{legal_knowledge[:2000]}"

        prompt = f"""请作为被告代理律师进行开庭陈述。记住：你只为被告利益服务。

案件事实：
{case_facts}

原告诉求：
{plaintiff_claim}

{"争议焦点：" + focus_points if focus_points else ""}
{law_section}

请完成以下工作：
1. 【事实抗辩】只陈述对被告有利的案件事实版本，否定或重新解读原告的不利指控
2. 【法律抗辩】只引用支持被告抗辩的法条和司法解释（标注法律全称和条号），不得引用对被告不利的法条
3. 【证据质疑】指出原告诉求中的证据不足或矛盾之处
4. 【减责/免责主张】论证被告责任应减轻或免除

重要提醒：你是被告律师，绝不认可原告立场，绝不引用对被告不利的法条！"""
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
        plaintiff_args: list[str] | None = None,
        defendant_args: list[str] | None = None,
        judge_comment: str = "",
        legal_knowledge: str = "",
    ) -> str:
        """被告律师反驳原告陈述（增强版：辩论历史+法官点评+防反水）"""
        debate_history = self._build_debate_history(plaintiff_args, defendant_args)
        history_section = ""
        if debate_history:
            history_section = f"\n前几轮辩论记录（保持论证连贯，不要重复已提出的论点）：\n{debate_history}"

        judge_section = ""
        if judge_comment:
            judge_section = f"\n法官点评（注意回应法官关注的问题，但立场不变）：\n{judge_comment[:500]}"

        law_section = ""
        if legal_knowledge:
            law_section = f"\n可引用的法律知识（只选取对被告有利的部分）：\n{legal_knowledge[:1500]}"

        prompt = f"""请作为被告代理律师，对原告第 {round_num} 轮陈述进行猛烈反驳。

案件事实：
{case_facts}
{history_section}
{judge_section}
{law_section}

原告本轮陈述：
{plaintiff_arg}

请完成以下工作：
1. 【反驳意见】逐条攻击原告的每一个论点，揭露其逻辑漏洞、事实错误和法律适用错误
2. 【法律抗辩】只引用支持被告立场的法条和司法解释（标注法律全称和条号），如果原告引用了对被告不利的法条，必须从适用条件、例外条款角度反驳
3. 【证据质疑】质疑原告证据的证明力，强调对被告有利的证据
4. 【新论点】如有可能，提出新的对被告有利的论据（每轮至少一个新角度，如诉讼时效、因果关系中断、责任减轻等）

绝对禁止：
- 不得承认原告的任何论点有道理
- 不得引用对被告不利的法条
- 不得使用"原告也有一定道理"等中立表述
- 不得承认被告应承担责任或弱化抗辩力度"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def final_statement(
        self,
        all_plaintiff_args: list[str],
        case_facts: str,
        defendant_args: list[str] | None = None,
        judge_comments: list[str] | None = None,
    ) -> str:
        """被告律师最后陈述（增强版）"""
        plaintiff_summary = "\n---\n".join(all_plaintiff_args[-3:]) if all_plaintiff_args else "（无）"
        defendant_summary = ""
        if defendant_args:
            defendant_summary = f"\n被告历轮论点回顾：\n" + "\n---\n".join(defendant_args[-3:])
        judge_section = ""
        if judge_comments:
            judge_section = f"\n法官历轮点评：\n" + "\n---\n".join(judge_comments[-3:])

        prompt = f"""请作为被告代理律师进行最后陈述。这是你最后的发言机会，必须全力为被告争取。

案件事实：
{case_facts}

原告全部陈述摘要：
{plaintiff_summary}

{defendant_summary}
{judge_section}

请完成以下工作：
1. 总结被告的核心抗辩主张和全部论据，强调最有力的抗辩
2. 系统性指出原告陈述中的矛盾、漏洞和逻辑错误
3. 逐条反驳原告的核心指控
4. 重申被告的最终立场：不承担责任或责任应最大限度减轻

绝对禁止：不得认可原告立场，不得承认被告应承担责任！"""
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
        plaintiff_claim: str,
        focus_points: str = "",
        legal_knowledge: str = "",
    ):
        law_section = ""
        if legal_knowledge:
            law_section = f"\n可引用的法律知识（只选取对被告有利的部分）：\n{legal_knowledge[:2000]}"

        prompt = f"""请作为被告代理律师进行开庭陈述。记住：你只为被告利益服务。

案件事实：
{case_facts}

原告诉求：
{plaintiff_claim}

{"争议焦点：" + focus_points if focus_points else ""}
{law_section}

请完成以下工作：
1. 【事实抗辩】只陈述对被告有利的案件事实版本，否定或重新解读原告的不利指控
2. 【法律抗辩】只引用支持被告抗辩的法条和司法解释（标注法律全称和条号），不得引用对被告不利的法条
3. 【证据质疑】指出原告诉求中的证据不足或矛盾之处
4. 【减责/免责主张】论证被告责任应减轻或免除

重要提醒：你是被告律师，绝不认可原告立场，绝不引用对被告不利的法条！"""
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
            law_section = f"\n可引用的法律知识（只选取对被告有利的部分）：\n{legal_knowledge[:1500]}"

        prompt = f"""请作为被告代理律师，对原告第 {round_num} 轮陈述进行猛烈反驳。

案件事实：
{case_facts}
{history_section}
{judge_section}
{law_section}

原告本轮陈述：
{plaintiff_arg}

请完成以下工作：
1. 【反驳意见】逐条攻击原告的每一个论点，揭露其逻辑漏洞、事实错误和法律适用错误
2. 【法律抗辩】只引用支持被告立场的法条和司法解释（标注法律全称和条号），如果原告引用了对被告不利的法条，必须从适用条件、例外条款角度反驳
3. 【证据质疑】质疑原告证据的证明力，强调对被告有利的证据
4. 【新论点】如有可能，提出新的对被告有利的论据（每轮至少一个新角度，如诉讼时效、因果关系中断、责任减轻等）

绝对禁止：
- 不得承认原告的任何论点有道理
- 不得引用对被告不利的法条
- 不得使用"原告也有一定道理"等中立表述
- 不得承认被告应承担责任或弱化抗辩力度"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
