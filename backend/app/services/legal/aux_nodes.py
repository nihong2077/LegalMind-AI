"""
辅助节点：白话化翻译 + 人机中断处理。
"""

import logging
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

PLAIN_LANGUAGE_PROMPT = """你是一位法律科普作家，擅长将复杂的法律术语和判决书内容
转换为通俗易懂的白话文，让没有法律背景的普通人也能理解。

要求：
1. 保留原文的核心法律含义，不改变判决结果
2. 用日常生活中的比喻和例子解释法律概念
3. 避免使用"原告""被告""诉讼请求"等术语，改用"告状的人""被告的人""想要的结果"
4. 对关键法律术语用括号标注原文
5. 语气亲切、耐心，适合老年人阅读"""


async def translate_to_plain_language(
    legal_text: str,
    llm: BaseChatModel,
) -> str:
    """将法律文本翻译为通俗白话"""
    messages = [
        SystemMessage(content=PLAIN_LANGUAGE_PROMPT),
        HumanMessage(content=f"请将以下法律内容翻译成通俗易懂的白话：\n\n{legal_text}"),
    ]
    response = await llm.ainvoke(messages)
    return response.content


async def translate_to_plain_language_stream(
    legal_text: str,
    llm: BaseChatModel,
):
    """流式白话翻译"""
    messages = [
        SystemMessage(content=PLAIN_LANGUAGE_PROMPT),
        HumanMessage(content=f"请将以下法律内容翻译成通俗易懂的白话：\n\n{legal_text}"),
    ]
    async for chunk in llm.astream(messages):
        if chunk.content:
            yield chunk.content


EVIDENCE_INSUFFICIENT_THRESHOLD = 0.4


def check_evidence_sufficiency(kfe: dict) -> tuple[bool, str]:
    """
    检查证据是否充分，决定是否需要中断流程让用户补充。

    仅检查原告方（举证责任方）的证据充分性。
    被告方证据弱是正常的，不阻断流程。

    Returns:
        (证据是否充分, 缺失说明)
    """
    missing = []

    evidence_strength = kfe.get("evidence_strength_plaintiff", "中")
    if evidence_strength == "弱":
        missing.append("原告方证据不足，请上传相关合同、聊天记录、转账凭证等")

    if kfe.get("breach_type") == "不明确":
        missing.append("违约/侵权类型不明确，请补充更多案件细节")

    if kfe.get("damage_amount", 0) == 0:
        missing.append("损失金额未明确，请提供具体金额或计算依据")

    if missing:
        return False, "\n".join(missing)

    return True, "证据基本充分"


class InterruptRequest:
    """人机中断请求"""

    def __init__(self, reason: str, required_documents: list[str]):
        self.reason = reason
        self.required_documents = required_documents

    def to_dict(self) -> dict:
        return {
            "type": "interrupt",
            "reason": self.reason,
            "required_documents": self.required_documents,
            "message": f"需要补充以下材料才能继续：{'、'.join(self.required_documents)}",
        }
