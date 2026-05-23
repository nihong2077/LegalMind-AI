"""
法官 Skill — 模拟法庭核心裁判能力

设计原则（融合 AgentCourt / ChatLaw / IRAC 框架最佳实践）：
1. IRAC 法律推理：Issue → Rule → Application → Conclusion
2. 主动式法官：可追问、可引导、可制止无关发言
3. 递进式焦点收敛：每轮更新争议焦点状态（已解决/未解决/新增）
4. 结构化输出：JSON Schema 约束，便于下游节点消费
5. 法条注入：法官独立检索法条，不依赖律师引用
"""

import json
import logging
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

# ============================================================
# 系统 Prompt — 法官角色定义
# ============================================================

JUDGE_SYSTEM_PROMPT = """你是一位资深中国法官，主持民事/刑事案件的模拟庭审。你的核心职责：

## 一、庭审流程控制
1. 严格按照中国庭审程序主持：开庭准备 → 法庭调查 → 法庭辩论 → 最后陈述 → 当庭宣判
2. 控制发言顺序：原告先发言，被告后答辩，交替进行
3. 及时制止与本案无关的发言，引导双方围绕争议焦点辩论
4. 对关键事实不清之处，主动追问双方

## 二、争议焦点归纳
- 从双方陈述中提炼2-4个核心争议焦点
- 每个焦点必须明确、具体、可辩论
- 区分事实争议（"是否发生"）和法律争议（"如何适用"）
- 辩论过程中动态更新焦点状态

## 三、事实认定
- 基于"谁主张谁举证"原则分配举证责任
- 评估证据的关联性、合法性和证明力
- 对双方无争议的事实直接认定
- 对有争议的事实，根据证据优势原则判断

## 四、法律推理（IRAC框架）
- Issue: 识别需要裁决的法律问题
- Rule: 检索并引用具体的法律条文（标注法律全称和条号）
- Application: 将法律规则适用于认定的事实
- Conclusion: 得出明确的裁判结论

## 五、裁决输出
- 事实认定：逐项列出认定的事实和依据
- 法律适用：引用具体法条，说明适用理由
- 裁判主文：明确、具体的判决结果
- 诉讼费用：明确各方承担比例

请保持中立、公正，严格依据法律和事实作出判断。所有法条引用必须标注法律全称和条号。"""


# ============================================================
# 法官 Skill 主类
# ============================================================

class JudgeSkill:
    """法官 Skill — 模拟法庭裁判能力"""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.system_prompt = JUDGE_SYSTEM_PROMPT

    # ----------------------------------------------------------
    # 1. 开庭主持 — 归纳争议焦点，确定辩论方向
    # ----------------------------------------------------------

    async def preside_opening(
        self,
        plaintiff_claim: str,
        defendant_response: str = "",
        kfe: Optional[dict] = None,
        legal_knowledge: str = "",
    ) -> str:
        """开庭主持：归纳争议焦点，确定辩论方向"""
        kfe_section = ""
        if kfe:
            kfe_section = f"\n关键法律事实（KFE）：\n{json.dumps(kfe, ensure_ascii=False, indent=2)}"

        law_section = ""
        if legal_knowledge:
            law_section = f"\n相关法律知识：\n{legal_knowledge[:2000]}"

        prompt = f"""请作为法官主持本次庭审的开庭阶段。

原告诉求：
{plaintiff_claim}

被告回应：
{defendant_response or "（被告尚未回应）"}
{kfe_section}
{law_section}

请完成以下工作（严格按JSON格式输出）：
{{
    "opening_statement": "法官开庭致辞，说明庭审程序和注意事项",
    "focus_points": [
        {{
            "id": "F1",
            "description": "争议焦点描述",
            "type": "事实争议/法律争议",
            "status": "pending",
            "plaintiff_position": "原告立场摘要",
            "defendant_position": "被告立场摘要"
        }}
    ],
    "facts_to_clarify": ["需要进一步查明的事实1", "需要进一步查明的事实2"],
    "debate_direction": "对双方辩论的指引和注意事项"
}}"""

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return self._extract_json_or_text(response.content)

    # ----------------------------------------------------------
    # 2. 法庭调查 — 主动追问关键事实
    # ----------------------------------------------------------

    async def court_investigation(
        self,
        focus_points: str,
        plaintiff_opening: str,
        defendant_opening: str,
        kfe: Optional[dict] = None,
    ) -> str:
        """法庭调查阶段：法官主动追问关键事实"""
        kfe_section = ""
        if kfe:
            kfe_section = f"\n关键法律事实（KFE）：\n{json.dumps(kfe, ensure_ascii=False, indent=2)}"

        prompt = f"""请作为法官进行法庭调查，对双方陈述中的关键事实进行追问。

争议焦点：
{focus_points}

原告陈述：
{plaintiff_opening[:2000]}

被告陈述：
{defendant_opening[:2000]}
{kfe_section}

请完成以下工作（严格按JSON格式输出）：
{{
    "investigation_questions": [
        {{
            "target": "原告/被告/双方",
            "question": "法官追问的问题",
            "purpose": "追问目的（查明事实/澄清矛盾/确认证据）",
            "related_focus": "关联的争议焦点ID"
        }}
    ],
    "facts_confirmed": ["双方无争议、可直接认定的事实"],
    "facts_disputed": ["双方存在争议、需进一步举证的事实"],
    "evidence_gaps": ["证据链中的薄弱环节"]
}}"""

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return self._extract_json_or_text(response.content)

    # ----------------------------------------------------------
    # 3. 辩论点评 — 评估本轮辩论，更新焦点状态
    # ----------------------------------------------------------

    async def evaluate_round(
        self,
        plaintiff_arg: str,
        defendant_arg: str,
        focus_points: str,
        round_num: int,
        judge_comments_history: Optional[list[str]] = None,
        legal_knowledge: str = "",
    ) -> str:
        """评估本轮辩论，给出法官点评和下一轮指引"""
        history_section = ""
        if judge_comments_history:
            history_section = f"\n法官前几轮点评：\n" + "\n---\n".join(judge_comments_history[-2:])

        law_section = ""
        if legal_knowledge:
            law_section = f"\n相关法律知识：\n{legal_knowledge[:1500]}"

        prompt = f"""请作为法官评估第 {round_num} 轮辩论。

争议焦点：
{focus_points}

原告本轮陈述：
{plaintiff_arg[:2000]}

被告本轮陈述：
{defendant_arg[:2000]}
{history_section}
{law_section}

请完成以下工作（严格按JSON格式输出）：
{{
    "round_evaluation": {{
        "plaintiff_strength": "原告本轮论证的优点",
        "plaintiff_weakness": "原告本轮论证的不足",
        "defendant_strength": "被告本轮论证的优点",
        "defendant_weakness": "被告本轮论证的不足"
    }},
    "focus_updates": [
        {{
            "focus_id": "F1",
            "status": "resolved/partially_resolved/unresolved/new_issue",
            "progress": "该焦点的进展说明"
        }}
    ],
    "facts_established": ["本轮新认定的事实"],
    "legal_issues_remaining": ["仍需解决的法律问题"],
    "next_round_guidance": "对下一轮辩论的指引方向，要求双方重点辩论什么",
    "judge_comment": "法官对双方的本轮综合点评（面向当事人的正式表述）"
}}"""

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return self._extract_json_or_text(response.content)

    # ----------------------------------------------------------
    # 4. 最终裁决 — IRAC 框架结构化裁决
    # ----------------------------------------------------------

    async def render_verdict(
        self,
        plaintiff_args: list[str],
        defendant_args: list[str],
        kfe: dict,
        focus_points: str,
        judge_comments: Optional[list[str]] = None,
        legal_knowledge: str = "",
    ) -> str:
        """辩论结束后，基于 IRAC 框架给出结构化裁决意见"""
        plaintiff_summary = "\n---\n".join(plaintiff_args[-3:]) if plaintiff_args else "（无）"
        defendant_summary = "\n---\n".join(defendant_args[-3:]) if defendant_args else "（无）"

        comments_section = ""
        if judge_comments:
            comments_section = f"\n法官历轮点评：\n" + "\n---\n".join(judge_comments)

        law_section = ""
        if legal_knowledge:
            law_section = f"\n相关法律知识：\n{legal_knowledge[:2000]}"

        prompt = f"""请作为法官，在辩论结束后基于 IRAC 框架作出最终裁决意见。

争议焦点：
{focus_points}

关键法律事实（KFE）：
{json.dumps(kfe, ensure_ascii=False, indent=2)}

原告主要陈述：
{plaintiff_summary}

被告主要陈述：
{defendant_summary}
{comments_section}
{law_section}

请严格按照 IRAC 框架输出裁决（JSON格式）：
{{
    "issue": {{
        "legal_questions": ["需要裁决的核心法律问题1", "核心法律问题2"],
        "dispute_nature": "案件性质（合同纠纷/侵权纠纷/劳动争议等）"
    }},
    "rule": {{
        "applicable_laws": [
            {{
                "law_name": "法律全称",
                "article_number": "条号",
                "article_content": "条文核心内容摘要",
                "relevance": "直接适用/参照适用"
            }}
        ],
        "judicial_interpretations": ["相关司法解释（如有）"]
    }},
    "application": {{
        "fact_finding": [
            {{
                "fact": "认定的事实",
                "evidence_basis": "证据依据",
                "certainty": "确定/高度可能/可能"
            }}
        ],
        "legal_analysis": "将法律规则适用于认定事实的分析过程",
        "fault_determination": {{
            "plaintiff_fault_ratio": 0,
            "defendant_fault_ratio": 100,
            "reasoning": "过错比例划分理由"
        }}
    }},
    "conclusion": {{
        "verdict": "明确的裁判结论",
        "specific_orders": ["判决主文第1项", "判决主文第2项"],
        "damage_calculation": {{
            "total_amount": 0,
            "breakdown": "赔偿计算明细"
        }},
        "litigation_costs": "诉讼费用承担方案",
        "enforcement_period": "履行期限"
    }},
    "dissenting_opinion": "如有多数意见外的不同观点，在此说明（无则留空）"
}}"""

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return self._extract_json_or_text(response.content)

    # ----------------------------------------------------------
    # 5. 调解建议 — 基于辩论情况给出调解方案
    # ----------------------------------------------------------

    async def suggest_mediation(
        self,
        plaintiff_args: list[str],
        defendant_args: list[str],
        kfe: dict,
        focus_points: str,
    ) -> str:
        """基于辩论情况给出调解建议"""
        prompt = f"""请作为法官，基于庭审辩论情况，提出调解建议方案。

争议焦点：
{focus_points}

关键法律事实（KFE）：
{json.dumps(kfe, ensure_ascii=False, indent=2)}

原告主要诉求：
{"；".join(plaintiff_args[-2:])[:1000]}

被告主要抗辩：
{"；".join(defendant_args[-2:])[:1000]}

请输出调解建议（JSON格式）：
{{
    "mediation_feasibility": "高/中/低",
    "mediation_basis": "调解的法律和事实基础",
    "proposed_plan": {{
        "core_terms": ["调解核心条款1", "调解核心条款2"],
        "payment_plan": "付款安排（如适用）",
        "performance_deadline": "履行期限",
        "breach_clause": "违约条款"
    }},
    "plaintiff_concessions": "建议原告作出的让步",
    "defendant_concessions": "建议被告作出的让步",
    "risk_warning": "不接受调解可能面临的风险"
}}"""

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return self._extract_json_or_text(response.content)

    # ----------------------------------------------------------
    # 6. 流式输出方法
    # ----------------------------------------------------------

    async def preside_opening_stream(self, plaintiff_claim: str, defendant_response: str = ""):
        prompt = f"""请作为法官主持本次庭审的开庭阶段。

原告诉求：
{plaintiff_claim}

被告回应：
{defendant_response or "（被告尚未回应）"}

请完成以下工作：
1. 法官开庭致辞
2. 归纳本案的核心争议焦点（2-4个）
3. 确定辩论顺序和需要查明的事实
4. 提示双方围绕焦点展开辩论"""
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
        plaintiff_summary = "\n---\n".join(plaintiff_args[-3:]) if plaintiff_args else "（无）"
        defendant_summary = "\n---\n".join(defendant_args[-3:]) if defendant_args else "（无）"

        prompt = f"""请作为法官，在辩论结束后作出最终裁决意见。

争议焦点：
{focus_points}

关键法律事实（KFE）：
{json.dumps(kfe, ensure_ascii=False, indent=2)}

原告主要陈述：
{plaintiff_summary}

被告主要陈述：
{defendant_summary}

请按 IRAC 框架输出：
1. 【争议问题】需要裁决的核心法律问题
2. 【法律规则】适用的具体法条
3. 【法律适用】将法律规则适用于认定事实
4. 【裁判结论】明确的判决结果"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content

    # ----------------------------------------------------------
    # 工具方法
    # ----------------------------------------------------------

    @staticmethod
    def _extract_json_or_text(text: str) -> str:
        """从 LLM 输出中提取 JSON，失败则返回原文"""
        text = text.strip()
        # 尝试提取 JSON 块
        if "```json" in text:
            json_block = text.split("```json", 1)[-1].split("```", 1)[0].strip()
            try:
                json.loads(json_block)
                return json_block
            except json.JSONDecodeError:
                pass
        elif "```" in text:
            json_block = text.split("```", 1)[-1].split("```", 1)[0].strip()
            try:
                json.loads(json_block)
                return json_block
            except json.JSONDecodeError:
                pass
        # 尝试直接解析
        import re
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            try:
                json.loads(json_match.group())
                return json_match.group()
            except json.JSONDecodeError:
                pass
        # 都失败则返回原文
        return text

    @staticmethod
    def parse_json_output(text: str) -> dict:
        """将法官输出解析为字典，失败返回空字典"""
        json_str = JudgeSkill._extract_json_or_text(text)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("法官输出 JSON 解析失败，返回空字典")
            return {}
