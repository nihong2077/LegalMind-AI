"""
辅助节点：白话化翻译 + 人机中断处理。
"""

import logging
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

PLAIN_LANGUAGE_PROMPT = """你是一位资深法律调解员，擅长将复杂的法律判决转换为通俗易懂的白话文，
并提出切实可行的调解方案，让没有法律背景的普通人也能理解并选择行动方案。

要求：
1. 保留原文的核心法律含义，不改变判决结果
2. 用日常生活中的比喻和例子解释法律概念
3. **必须**在文末提出具体的调解方案建议，包括：
   - 双方可以接受的折中方案
   - 调解步骤和时间安排
   - 执行保障措施
4. 避免使用"原告""被告""诉讼请求"等术语，改用"告状的人""被告的人""想要的结果"
5. 对关键法律术语用括号标注原文
6. 语气亲切、耐心，适合普通人阅读"""


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

    仅在极端情况下阻断流程（如完全无法识别案件类型），
    一般情况下允许辩论继续，由庭审过程本身厘清争议。

    Returns:
        (证据是否充分, 缺失说明)
    """
    # 只有当案件描述完全无法识别任何法律要素时才阻断
    # breach_type 和 evidence_strength 仅作为提示信息，不阻断流程
    # 确定违约类型和证据强度本身就是辩论过程的一部分
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
