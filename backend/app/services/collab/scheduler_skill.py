"""SchedulerSkill（T1.4）——隐藏「演讲排序智能体」

对齐计划 §1 **D14** 与 [规格 §2.4/§3.4](../../../../docs/collab-supervisor-checkpoint_spec.md)（F13）：

- **对用户完全隐藏**：无角色人设、不发言、**不产生任何气泡**、不进 `agent_registry`；
  唯一职责是决定 `next_speaker` + `continue_round`（发言顺序与续轮权，D14）。
- **无裁决权**：`verdict/conclude/ask_user` 一律归 host；本 Skill 只输出排序。
- 用 **flash** 模型（低成本、低时延，A4）；输出严格 JSON。
- **白名单护栏 + 一次反馈修复**：`next_speaker` 必须在候选名单内，越权 → 带反馈重调一次；
  **连续两次非法 → 收敛本轮（continue_round=false）**，全程无异常栈（F13）。
- **失败降级兜底（D15③）**：本 Skill 的调用异常由**图节点**捕获并回退「模板默认顺序」，
  整轮不中断；本 Skill 自身不吞异常。

输出契约（供图节点消费）::

    {"next_speaker": <agent_id>|None, "continue_round": bool, "reason": str,
     "raw_output": str, "latency_ms": int, "repaired": bool, "parse_failed": bool?}
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from ...core.llm_client import LLMClient, get_llm_client
from .prompts import (
    SCHEDULER_SYSTEM_PROMPT,
    build_scheduler_repair_prompt,
    build_scheduler_user_prompt,
    extract_json_object,
)
from .registry import RegistryService, get_registry

logger = logging.getLogger(__name__)

SCHEDULER_MODEL = "deepseek-flash"


class SchedulerSkill:
    """星型图的隐藏排序节点能力（图内 ``scheduler`` 注入点）。"""

    def __init__(
        self,
        *,
        llm: Optional[LLMClient] = None,
        registry: Optional[RegistryService] = None,
        model: str = SCHEDULER_MODEL,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    @property
    def llm(self) -> LLMClient:
        return self._llm or get_llm_client()

    async def decide(self, state: dict[str, Any], candidates: list[str]) -> dict[str, Any]:
        """决定下一位发言者与是否续轮。

        Args:
            candidates: 白名单候选（**有序**，顺序即模板默认顺序，D15① 保序依据）。
        """
        reg = self._registry or await get_registry()
        names = {a["agent_id"]: a["name"] for a in await reg.all_agents()}
        messages = [
            {"role": "system", "content": SCHEDULER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_scheduler_user_prompt(state, candidates, names),
            },
        ]

        raw, latency = await self._call(messages)
        decision, error = _validate(raw, candidates)
        if decision is not None:
            return {**decision, "repaired": False, "parse_failed": False,
                    "raw_output": raw, "latency_ms": latency}

        logger.info("[collab] 排序输出校验失败，尝试一次反馈修复：%s", error)
        repair_messages = [
            *messages,
            {"role": "assistant", "content": raw},
            {"role": "user", "content": build_scheduler_repair_prompt(raw, error, candidates)},
        ]
        raw2, latency2 = await self._call(repair_messages)
        decision2, error2 = _validate(raw2, candidates)
        total_latency = latency + latency2
        if decision2 is not None:
            return {**decision2, "repaired": True, "parse_failed": False,
                    "raw_output": raw2, "latency_ms": total_latency}

        # F13：连续两次非法 → 收敛本轮（不抛异常、不跳人）
        logger.warning("[collab] 排序输出连续两次非法，收敛本轮：%s", error2)
        return {
            "next_speaker": None,
            "continue_round": False,
            "reason": "排序输出连续两次非法，按护栏收敛本轮",
            "parse_failed": True,
            "repaired": True,
            "raw_output": raw2,
            "latency_ms": total_latency,
        }

    async def _call(self, messages: list[dict[str, Any]]) -> tuple[str, int]:
        started = time.perf_counter()
        result = await self.llm.chat(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        latency = int((time.perf_counter() - started) * 1000)
        choices = result.get("choices") or [{}]
        content = (choices[0].get("message") or {}).get("content") or ""
        return content, latency


def _validate(raw: str, candidates: list[str]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """白名单校验（护栏①）：返回（决策, 错误原因），二者仅有一个非空。"""
    obj = extract_json_object(raw)
    if obj is None:
        return None, "未在输出中找到合法 JSON 排序指令"

    raw_next = obj.get("next_speaker")
    next_speaker: Optional[str] = None
    if raw_next is not None and str(raw_next).strip().lower() not in ("", "null", "none"):
        next_speaker = str(raw_next).strip()
        if next_speaker not in candidates:
            return None, f"next_speaker 非法（{next_speaker}）不在候选名单内"

    raw_continue = obj.get("continue_round")
    continue_round = bool(raw_continue) if raw_continue is not None else bool(next_speaker)
    if continue_round and not next_speaker:
        return None, "continue_round=true 但未给出合法的 next_speaker"

    return {
        "next_speaker": next_speaker,
        "continue_round": continue_round,
        "reason": str(obj.get("reason") or ""),
        "round_summary": obj.get("round_summary") or "",
    }, None
