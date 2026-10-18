"""court（模拟庭审）适配配置（T1.7）

对齐 [docs/collab-implementation_plan.md](../../../../../docs/collab-implementation_plan.md) §3 T1.7 行与
[docs/collab-supervisor-checkpoint_spec.md](../../../../../docs/collab-supervisor-checkpoint_spec.md) §2.5/§6：

- **host = 法官（JudgeSkill collab_mode）**：口语主持发言 + 程序性指令（``continue / ask_user / verdict``）；
- **scheduler = 打散串行、庭审用语中性**：优先让尚未陈述的原/被告交替发言（不跳人），
  双方陈述完毕后传唤书记员；roster 均已陈述则收敛交由主持人裁决；
- **补证卡片群内化**：``ask_user`` 中断时把中断 payload 包装成庭审补证卡片；
- **verdict → 判决书**：``force_stop_reason == "verdict"`` 时由 ``JudgmentReportSkill`` 产出判决书气泡。

本模块全部为**纯函数 / 可注入工厂**（不读库、不建图、无固定边），便于单测与集成期组装；
旧 ``debate_workflow`` / ``/debate/stream`` 不受任何影响（A3 红线）。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Awaitable, Callable, Optional

from langchain_core.messages import AIMessage

from ....core.llm_client import LLMClient, get_llm_client
from ...agents.judge_skill import build_collab_system_prompt
from ...agents.judgment_report_skill import JudgmentReportSkill
from ..graph import _template_order_decision
from ..prompts import build_host_repair_prompt, build_host_user_prompt, split_utterance_and_json
from ..registry import RegistryService, get_registry

logger = logging.getLogger(__name__)

COURT_ADAPTER = "court"
COURT_LITIGANTS = ("plaintiff_lawyer", "defense_lawyer")
COURT_CLERK = "clerk"
DEFAULT_COURT_MODEL = "deepseek-v4-pro"

# 庭审主持人程序性指令枚举（D14：不含 next，spec §6 适配版）
COURT_DIRECTIVES = ("continue", "ask_user", "verdict")

HostAdvisor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
SchedulerDecider = Callable[[dict[str, Any], list[str]], Awaitable[dict[str, Any]]]
ConcludeProducer = Callable[[dict[str, Any]], Awaitable[list[AIMessage]]]
VerdictRunner = Callable[[dict[str, Any]], Awaitable[str]]


# ============================================================
# 1. scheduler —— 打散串行、庭审用语中性（D14/D15①）
# ============================================================

async def court_scheduler(state: dict[str, Any], candidates: list[str]) -> dict[str, Any]:
    """庭审排序（纯函数，async 以适配图 ``SchedulerDecider`` 契约）：原/被告交替、不跳人、
    中性程序用语；双方陈述后传唤书记员。

    退化：roster 无原/被告时回退**模板默认顺序**（保持与通用模板一致，不自造业务）。
    ``candidates`` 为有序白名单（顺序即模板默认顺序，D15①）；工具辐条不由顺序自动派发。
    """
    roster = list(state.get("roster") or [])
    spoken = list(state.get("spoken") or [])
    spoken_set = set(spoken)
    candidate_set = set(candidates)

    litigants = [c for c in COURT_LITIGANTS if c in roster and c in candidate_set]
    if not litigants:  # 非庭审阵容 → 模板默认顺序兜底
        return _template_order_decision(state, candidates)

    # ① 优先尚未陈述的一方（原告优先）——原/被告交替，不跳人
    for agent_id in litigants:
        if agent_id not in spoken_set:
            return {
                "next_speaker": agent_id,
                "continue_round": True,
                "reason": "按庭审程序传唤尚未陈述的一方，保持对抗均衡",
            }

    # ② 双方均已陈述 → 传唤书记员记录笔录（如未发言且在白名单内）
    if COURT_CLERK in roster and COURT_CLERK not in spoken_set and COURT_CLERK in candidate_set:
        return {
            "next_speaker": COURT_CLERK,
            "continue_round": True,
            "reason": "双方陈述完毕，交由书记员记录并整理庭审笔录",
        }

    # ③ 各方已陈述且仍有轮次额度 → 回到陈述较少的一方继续对辩（打散固定串行）
    if int(state.get("round", 0)) < int(state.get("max_rounds", 2)):
        counts = {c: spoken.count(c) for c in litigants}
        target = min(litigants, key=lambda c: counts[c])
        return {
            "next_speaker": target,
            "continue_round": True,
            "reason": "庭审对抗尚未充分，传唤陈述较少的一方继续对辩",
        }

    # ④ 收敛：交由主持人裁量是否裁决
    return {
        "next_speaker": None,
        "continue_round": False,
        "reason": "庭审各方均已陈述，交由主持人裁量裁决",
    }


# ============================================================
# 2. host_advisor —— 法官（JudgeSkill collab_mode 提示词）
# ============================================================

def build_court_host_advisor(
    *,
    llm: Optional[LLMClient] = None,
    registry: Optional[RegistryService] = None,
    model: str = DEFAULT_COURT_MODEL,
) -> HostAdvisor:
    """构造庭审主持人（口语发言 + 程序指令）回调；提示词走 JudgeSkill collab_mode 分支。"""
    system_prompt = build_collab_system_prompt()

    async def advisor(state: dict[str, Any]) -> dict[str, Any]:
        reg = registry or await get_registry()
        template = await reg.get_template(str(state.get("case_type") or ""))
        client = llm or get_llm_client()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_host_user_prompt(state, template)},
        ]

        raw, latency = await _chat(client, model, messages)
        outcome = _normalize_court(raw, COURT_DIRECTIVES)
        if outcome["parse_ok"]:
            return {**outcome, "repaired": False, "parse_failed": False,
                    "raw_output": raw, "latency_ms": latency}

        # 护栏③：同 super-step 内带格式错误反馈再调一次（不跳人、不新增 round）
        logger.info("[collab] 法官输出校验失败，尝试一次格式修复：%s", outcome["error"])
        repair_messages = [
            *messages,
            {"role": "assistant", "content": raw},
            {"role": "user", "content": build_host_repair_prompt(raw, outcome["error"], COURT_DIRECTIVES)},
        ]
        raw2, latency2 = await _chat(client, model, repair_messages)
        outcome2 = _normalize_court(raw2, COURT_DIRECTIVES)
        total = latency + latency2
        if outcome2["parse_ok"]:
            return {**outcome2, "repaired": True, "parse_failed": False,
                    "raw_output": raw2, "latency_ms": total}

        # 护栏④ / F13：连续两次非法 → 兜底收尾（不误判为 verdict、无异常栈）
        logger.warning("[collab] 法官输出连续两次非法，按护栏兜底 conclude：%s", outcome2["error"])
        return {
            "utterance": outcome2["utterance"] or outcome["utterance"],
            "directive": "conclude",
            "ask_user": None,
            "round_summary": "",
            "reason": "法官输出连续两次非法，按护栏兜底收尾",
            "parse_ok": False,
            "parse_failed": True,
            "repaired": True,
            "raw_output": raw2,
            "latency_ms": total,
        }

    return advisor


def _normalize_court(raw: str, directives: tuple[str, ...]) -> dict[str, Any]:
    """把法官原始输出切成（口语发言, 程序指令）；失败给出可反馈的错误原因。"""
    utterance, obj, _raw_json = split_utterance_and_json(raw)
    if obj is None:
        return {"utterance": utterance, "directive": None, "parse_ok": False,
                "error": "未在输出中找到合法 JSON 指令对象"}
    directive = str(obj.get("directive") or "").strip().lower()
    if directive not in directives:
        return {"utterance": utterance, "directive": directive or None, "parse_ok": False,
                "error": f"directive 非法（{directive or '空'}），仅允许 {'/'.join(directives)}"}
    return {
        "utterance": utterance,
        "directive": directive,
        "ask_user": obj.get("ask_user"),
        "round_summary": obj.get("round_summary") or "",
        "reason": obj.get("reason") or "",
        "parse_ok": True,
        "error": None,
    }


async def _chat(
    client: LLMClient, model: str, messages: list[dict[str, Any]],
    *, temperature: float = 0.4, max_tokens: int = 2048,
) -> tuple[str, int]:
    started = time.perf_counter()
    result = await client.chat(
        model=model, messages=messages, temperature=temperature, max_tokens=max_tokens
    )
    latency = int((time.perf_counter() - started) * 1000)
    choices = result.get("choices") or [{}]
    content = (choices[0].get("message") or {}).get("content") or ""
    return content, latency


# ============================================================
# 3. 补证卡片群内化（ask_user 中断 payload）
# ============================================================

def build_court_interaction_card(state: dict[str, Any]) -> dict[str, Any]:
    """庭审补证卡片（并入 ``interrupt(...)`` payload，群内展示待办）。"""
    question = str(state.get("pending_question") or "").strip() or "请补充本案所需证据材料"
    return {
        "card_type": "evidence_supplement",
        "title": "补证通知",
        "hint": "请在本群补充证据材料（如合同、付款凭证、鉴定意见等），法官将继续审理。",
        "question": question,
    }


# ============================================================
# 4. verdict → 判决书（conclude 追加气泡）
# ============================================================

def make_court_verdict_runner(
    *, llm: Optional[LLMClient] = None, model: str = DEFAULT_COURT_MODEL
) -> VerdictRunner:
    """默认裁决产出器：``verdict`` → ``JudgmentReportSkill`` 生成判决书正文。"""
    client = llm

    async def runner(state: dict[str, Any]) -> str:
        chat = (client or get_llm_client()).get_chat_model(
            model=model, temperature=0.3, max_tokens=4096
        )
        return await JudgmentReportSkill(chat).generate_judgment(
            verdict=_verdict_basis(state),
            case_info={"case_type": str(state.get("case_type") or "")},
            plaintiff_args=_speeches(state, COURT_LITIGANTS[0]),
            defendant_args=_speeches(state, COURT_LITIGANTS[1]),
        )

    return runner


def make_court_conclude_producer(
    *, verdict_runner: Optional[VerdictRunner] = None,
    clerk_id: str = COURT_CLERK, clerk_name: str = "书记员",
) -> ConcludeProducer:
    """构造 conclude 追加产出器：仅 ``verdict`` 时追加判决书气泡，其余返回空。"""

    async def producer(state: dict[str, Any]) -> list[AIMessage]:
        if str(state.get("force_stop_reason") or "") != "verdict":
            return []
        runner = verdict_runner or make_court_verdict_runner()
        text = str(await runner(state) or "").strip()
        if not text:
            return []
        return [
            AIMessage(
                content=text,
                name=clerk_name,
                additional_kwargs={
                    "sender_type": "agent",
                    "agent_id": clerk_id,
                    "sender_name": clerk_name,
                    "phase": "verdict",
                },
            )
        ]

    return producer


def _verdict_basis(state: dict[str, Any]) -> str:
    """裁决依据：主持人最近口语裁量 + 指令归纳（供判决书撰写）。"""
    directive = state.get("host_directive") or {}
    parts: list[str] = []
    last_host = _last_content(state, sender_type="host")
    if last_host:
        parts.append(last_host)
    summary = str(directive.get("round_summary") or "").strip()
    if summary:
        parts.append(f"庭审归纳：{summary}")
    if not parts:
        parts.append(json.dumps(directive, ensure_ascii=False))
    return "\n".join(parts)


def _speeches(state: dict[str, Any], speaker_id: str) -> list[str]:
    out: list[str] = []
    for msg in state.get("messages") or []:
        kwargs = getattr(msg, "additional_kwargs", None) or {}
        sid = kwargs.get("agent_id") or kwargs.get("sender_id") or kwargs.get("actor_agent_id")
        content = str(getattr(msg, "content", "") or "").strip()
        if content and sid == speaker_id:
            out.append(content)
    return out


def _last_content(state: dict[str, Any], *, sender_type: str) -> str:
    for msg in reversed(state.get("messages") or []):
        kwargs = getattr(msg, "additional_kwargs", None) or {}
        if kwargs.get("sender_type") == sender_type:
            text = str(getattr(msg, "content", "") or "").strip()
            if text:
                return text
    return ""


# ============================================================
# 5. 组装便捷入口（集成期按模板 adapter 取用）
# ============================================================

def build_court_wiring(
    *,
    llm: Optional[LLMClient] = None,
    registry: Optional[RegistryService] = None,
    model: str = DEFAULT_COURT_MODEL,
    verdict_runner: Optional[VerdictRunner] = None,
) -> dict[str, Any]:
    """返回 court 模板的一组图可注入件（host_advisor/scheduler/interaction_card/conclude_producer）。"""
    return {
        "host_advisor": build_court_host_advisor(llm=llm, registry=registry, model=model),
        "scheduler": court_scheduler,
        "interaction_card": build_court_interaction_card,
        "conclude_producer": make_court_conclude_producer(verdict_runner=verdict_runner),
    }
