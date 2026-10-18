"""HostSkill（T1.4）——主持人：人设发言 + 程序性指令

对齐 [docs/collab-supervisor-checkpoint_spec.md](../../../../docs/collab-supervisor-checkpoint_spec.md)
§2.3/§2.4③④ 与计划 §1 **D13/D14**：

- 主持人**只做程序性决策**（`continue / ask_user / verdict / conclude`）+ 口语发言；
  **不指定 next_speaker**（发言顺序归隐藏 scheduler）。
- 双输出：口语发言（进气泡）+ 末尾指令 JSON；**JSON 在服务端缓冲剥离，不推给用户（S1）**。
- 容错提取：支持 ```json 代码块与裸 JSON；解析/枚举失败 → **同 super-step 内带反馈重调一次**
  （不移动图位置、不新增 round）；**连续两次失败 → 兜底 conclude**（无异常栈，F13）。
- 提示词人设按模板注入（D10）；`verdict` 仅庭审模板开放。

LLM 失败（重试/熔断后仍失败）直接抛出，交由 T1.6 的 super-step 恢复机制续跑，**不在节点内吞错**。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from ...core.llm_client import LLMClient, get_llm_client
from .prompts import (
    allowed_host_directives,
    build_host_repair_prompt,
    build_host_system_prompt,
    build_host_user_prompt,
    split_utterance_and_json,
)
from .registry import RegistryService, get_registry

logger = logging.getLogger(__name__)

DEFAULT_HOST_MODEL = "deepseek-v4-pro"


class HostSkill:
    """主持人节点能力（图内 ``host_advisor`` 注入点）。"""

    def __init__(
        self,
        *,
        llm: Optional[LLMClient] = None,
        registry: Optional[RegistryService] = None,
        default_model: str = DEFAULT_HOST_MODEL,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self.default_model = default_model

    @property
    def llm(self) -> LLMClient:
        return self._llm or get_llm_client()

    async def build_messages(
        self, state: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any], Optional[dict[str, Any]]]:
        """构造主持人提示词（T1.6 流式发言复用同一 prompt，保证 S1 一致）。"""
        reg = self._registry or await get_registry()
        host_id = state.get("host_agent_id") or ""
        agent = await reg.get_agent(host_id) or {
            "agent_id": host_id, "name": "主持人", "role_label": "主持人", "persona": "",
        }
        template = await reg.get_template(state.get("case_type") or "")
        return [
            {"role": "system", "content": build_host_system_prompt(agent, template)},
            {"role": "user", "content": build_host_user_prompt(state, template)},
        ], agent, template

    async def speak_and_decide(self, state: dict[str, Any]) -> dict[str, Any]:
        """产出口语发言 + 程序性指令（含一次格式修复，连续失败兜底 conclude）。"""
        messages, agent, template = await self.build_messages(state)
        directives = allowed_host_directives(template)
        model = (agent.get("model_pref") or {}).get("model") or self.default_model

        raw, latency = await self._call(model, messages, agent)
        outcome = _normalize(raw, directives)
        if outcome["parse_ok"]:
            return {**outcome, "repaired": False, "parse_failed": False,
                    "raw_output": raw, "latency_ms": latency}

        # 护栏③：同 super-step 内带格式错误反馈再调一次（不跳人、不新增 round）
        logger.info("[collab] 主持人输出校验失败，尝试一次格式修复：%s", outcome["error"])
        repair_messages = [
            *messages,
            {"role": "assistant", "content": raw},
            {"role": "user", "content": build_host_repair_prompt(raw, outcome["error"], directives)},
        ]
        raw2, latency2 = await self._call(model, repair_messages, agent)
        outcome2 = _normalize(raw2, directives)
        total_latency = latency + latency2
        if outcome2["parse_ok"]:
            return {**outcome2, "repaired": True, "parse_failed": False,
                    "raw_output": raw2, "latency_ms": total_latency}

        # 护栏④ / F13：连续两次失败 → 代码兜底收尾，全程无异常栈
        logger.warning("[collab] 主持人输出连续两次非法，按护栏兜底 conclude：%s", outcome2["error"])
        return {
            "utterance": outcome2["utterance"] or outcome["utterance"],
            "directive": "conclude",
            "ask_user": None,
            "round_summary": "",
            "reason": "主持人输出连续两次非法，按护栏兜底收尾",
            "parse_ok": False,
            "parse_failed": True,
            "repaired": True,
            "raw_output": raw2,
            "latency_ms": total_latency,
        }

    async def _call(self, model: str, messages: list[dict[str, Any]],
                    agent: dict[str, Any]) -> tuple[str, int]:
        prefs = agent.get("model_pref") or {}
        started = time.perf_counter()
        result = await self.llm.chat(
            model=model,
            messages=messages,
            temperature=float(prefs.get("temperature", 0.4)),
            max_tokens=int(prefs.get("max_tokens", 2048)),
        )
        latency = int((time.perf_counter() - started) * 1000)
        choices = result.get("choices") or [{}]
        content = (choices[0].get("message") or {}).get("content") or ""
        return content, latency


def _normalize(raw: str, directives: tuple[str, ...]) -> dict[str, Any]:
    """把模型原始输出解析为规范指令结果；失败时给出可供反馈的错误原因。"""
    utterance, obj, _raw_json = split_utterance_and_json(raw)
    if obj is None:
        return {
            "utterance": utterance, "directive": None, "parse_ok": False,
            "error": "未在输出中找到合法 JSON 指令对象",
        }
    directive = str(obj.get("directive") or "").strip().lower()
    if directive not in directives:
        return {
            "utterance": utterance, "directive": directive or None, "parse_ok": False,
            "error": f"directive 非法（{directive or '空'}），仅允许 {'/'.join(directives)}",
        }
    return {
        "utterance": utterance,
        "directive": directive,
        "ask_user": obj.get("ask_user"),
        "round_summary": obj.get("round_summary") or "",
        "reason": obj.get("reason") or "",
        "parse_ok": True,
        "error": None,
    }
