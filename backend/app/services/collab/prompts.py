"""协同编排提示词（T1.4）

两类提示词，职责严格分离（D14）：

- **host（主持人）**：人设来自注册表 ``persona`` 字段（D10：court → 法官、普通会商 → 调解员/
  法务分析师），双输出——**口语发言**（自然语言，进前端气泡）+ **程序性指令 JSON**
  （``continue / ask_user / verdict / conclude``）。**不含 next_speaker**，发言顺序归 scheduler。
- **scheduler（隐藏演讲排序智能体）**：无角色、无语气、**不产生任何给用户看的内容**，
  只输出排序 JSON（``next_speaker / continue_round / reason``）。

transcript 渲染为纯文本上下文，供两类提示词共用（Token 级流式由 T1.6 在 SSE 层承接）。
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional

# ---------------- 通用 ----------------

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)

_DIRECTIVE_COURT = "continue / ask_user / verdict"
_DIRECTIVE_GENERIC = "continue / ask_user / conclude"


def is_court_template(template: dict[str, Any] | None) -> bool:
    """庭审模板判定（供 host 决定是否开放 verdict、T1.7 复用同一判据）。"""
    return bool(template) and (template.get("adapter") == "court")


def allowed_host_directives(template: dict[str, Any] | None) -> tuple[str, ...]:
    return ("continue", "ask_user", "verdict") if is_court_template(template) else (
        "continue",
        "ask_user",
        "conclude",
    )


def render_transcript(messages: Iterable[Any], *, limit: int = 40) -> str:
    """把图内 transcript 渲染为提示词上下文（只保留最近 ``limit`` 条）。"""
    lines: list[str] = []
    for msg in list(messages)[-limit:]:
        kwargs = getattr(msg, "additional_kwargs", {}) or {}
        sender = kwargs.get("sender_name") or getattr(msg, "name", None) or "unknown"
        kind = kwargs.get("sender_type") or "message"
        content = (getattr(msg, "content", "") or "").strip()
        if not content:
            continue
        lines.append(f"[{kind}:{sender}] {content}")
    return "\n".join(lines) if lines else "（暂无对话）"


def render_roster(roster: list[str], agent_names: dict[str, str], spoken: list[str]) -> str:
    """渲染候选名单与已发言标记（顺序即模板默认顺序，D15① 保序依据）。"""
    spoken_set = set(spoken or [])
    rows = []
    for idx, agent_id in enumerate(roster or [], start=1):
        name = agent_names.get(agent_id, agent_id)
        mark = "（本轮已发言）" if agent_id in spoken_set else ""
        rows.append(f"{idx}. {agent_id}（{name}）{mark}")
    return "\n".join(rows) if rows else "（无可选发言者）"


def _iter_bare_json(text: str) -> Iterable[str]:
    """平衡花括号扫描：从最早出现的 ``{`` 开始，产出**最外层**可解析对象。"""
    for start, ch in enumerate(text or ""):
        if ch != "{":
            continue
        depth = 0
        for idx in range(start, len(text)):
            if text[idx] == "{":
                depth += 1
            elif text[idx] == "}":
                depth -= 1
                if depth == 0:
                    yield text[start:idx + 1]
                    break


def _iter_fenced(text: str) -> Iterable[str]:
    """```json 代码块内的内容（按出现顺序）。"""
    for block in _FENCED_JSON_RE.findall(text or ""):
        cleaned = block.strip()
        if cleaned:
            yield cleaned


def _parse_dict(candidate: str) -> Optional[dict[str, Any]]:
    try:
        parsed = json.loads(candidate)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_json_object(text: str) -> Optional[dict[str, Any]]:
    """容错提取：先 ```json 代码块，再裸 JSON（含前后夹带自然语言）。"""
    for candidate in (*_iter_fenced(text), *_iter_bare_json(text)):
        parsed = _parse_dict(candidate)
        if parsed is not None:
            return parsed
    return None


def split_utterance_and_json(text: str) -> tuple[str, Optional[dict[str, Any]], str]:
    """把 host 输出切成（口语发言, 指令 JSON, 原始 JSON 子串）。

    服务端必须剥离 JSON 部分（含 ```json 围栏），**不得**把它推给用户（S1）。
    """
    for match in _FENCED_JSON_RE.finditer(text or ""):
        inner = match.group(1).strip()
        parsed = _parse_dict(inner)
        if parsed is not None:
            utterance = (text[:match.start()] + text[match.end():]).strip()
            return utterance, parsed, inner
    for candidate in _iter_bare_json(text):
        parsed = _parse_dict(candidate)
        if parsed is not None:
            utterance = text.replace(candidate, " ").strip()
            return utterance, parsed, candidate
    return (text or "").strip(), None, ""


# ---------------- host（主持人） ----------------

def build_host_system_prompt(agent: dict[str, Any], template: dict[str, Any] | None) -> str:
    """按模板/注册表注入主持人（D10）；程序性指令枚举随庭审/会商两态切换。"""
    persona = (agent.get("persona") or "").strip() or "你是本次会商的主持人。"
    role_label = agent.get("role_label") or "主持人"
    case_name = (template or {}).get("name") or "普通会商"
    directives = _DIRECTIVE_COURT if is_court_template(template) else _DIRECTIVE_GENERIC
    verdict_note = (
        "verdict＝事实与争点已充分对抗，可以作出裁决"
        if is_court_template(template)
        else "conclude＝可以出具《会商纪要》并结束本轮"
    )
    return f"""{persona}

【角色】你是本次「{case_name}」的主持人（{role_label}）。

【你的职责】主持程序、归纳争点、适时追问，并在每轮结束给出**程序性指令**。
- **你只做程序性决策**：是否继续下一轮、是否需要用户补充、是否收尾。
- **不得指定下一位发言者**：发言顺序由系统内部的排序智能体决定，你无需（也不允许）安排谁先谁后。
- 你的发言面向当事人/用户，语气贴合你的角色，简明、克制、就事论事。

【输出格式（严格遵守）】
第一步：输出一段**给当事人看的口语发言**（纯自然语言，不要出现 JSON、不要出现字段名）。
第二步：发言之后另起一段，输出**唯一一个 JSON 对象**（可包在 ```json 代码块内）：

{{
  "round_summary": "本环节各方观点与分歧的极简归纳（1-3 句）",
  "directive": "{directives}",
  "ask_user": "仅当 directive=ask_user 时填写：需要用户补充的具体事实/证据；其它情况省略此字段",
  "reason": "为什么这样安排（一句话，写入审计）"
}}

【指令含义】
- continue＝程序性检查通过，本轮继续推进（下一步交给系统排序）
- ask_user＝需要用户补充信息/证据才能继续
- {verdict_note}"""


def build_host_user_prompt(state: dict[str, Any], template: dict[str, Any] | None) -> str:
    roster = state.get("roster") or []
    spoken = state.get("spoken") or []
    return f"""【会话】conversation_id={state.get("conversation_id")}　case_type={state.get("case_type")}
【轮次】round={state.get("round", 0)}/{state.get("max_rounds", 2)}
【群成员】{", ".join(roster) if roster else "（无）"}
【本轮已发言】{", ".join(spoken) if spoken else "（无）"}
【pending_question】{state.get("pending_question") or "（无）"}

【对话记录（最近若干条）】
{render_transcript(state.get("messages") or [])}

现在请按上述格式发言并给出程序性指令。"""


def build_host_repair_prompt(raw_output: str, error: str, directives: tuple[str, ...]) -> str:
    """护栏③：同 super-step 内的一次格式修复（不新增轮次、不跳人）。"""
    return f"""你上一次的输出未能通过系统格式校验。

【你的上次输出】
{raw_output}

【校验失败原因】{error}
【要求】只做一件事：重新输出「口语发言 + 一个合法 JSON」，``directive`` 必须是 {"/".join(directives)} 之一，
JSON 之外不要有任何解释文字。"""


# ---------------- scheduler（隐藏排序智能体） ----------------

SCHEDULER_SYSTEM_PROMPT = """你是「演讲排序智能体」——一个对用户完全隐藏的系统内部调度器。

【身份约束】
- 你**没有任何角色人设**：不是法官、不是律师、不是调解员，也不代表任何立场。
- 你**不发言、不寒暄、不解释**，绝不产生任何给用户看的文字或气泡。
- 你的输出**只**被系统程序消费，用户永远看不到。

【唯一职责】在当前候选发言者中决定：**下一位发言者**，以及**是否继续下一轮**。

【输出格式（严格遵守）】只输出**一个** JSON 对象，不要任何其它文字、不要代码块以外的说明：
{
  "next_speaker": "候选名单中的 agent_id；若本轮应收敛则为 null",
  "continue_round": true 或 false,
  "reason": "一句话说明排序理由（写入审计）",
  "round_summary": "可选：本轮已发生内容的极简归纳"
}

【硬性约束】
1. next_speaker **必须**取自下方「候选发言者」名单，出现名单以外的任何值都会被系统判为非法并否决；
2. 优先让**尚未发言者按既有顺序**获得发言机会，**不要跳人**（保序优先于多样性）；
3. 讨论已充分收敛、或已无未发言者时：continue_round=false 且 next_speaker=null；
4. 你**无权**作出裁决、结论或收尾决定，那属于主持人（host）；你只负责排序。"""


def build_scheduler_user_prompt(state: dict[str, Any], candidates: list[str],
                                agent_names: dict[str, str]) -> str:
    return f"""【案情类型】{state.get("case_type")}
【轮次】round={state.get("round", 0)}/{state.get("max_rounds", 2)}
【候选发言者（只可从中选择 next_speaker，顺序＝建议顺序）】
{render_roster(candidates, agent_names, state.get("spoken") or [])}
【主持人最近指令】{state.get("host_directive") or {}}

【本轮对话记录（最近若干条）】
{render_transcript(state.get("messages") or [])}

请只输出排序 JSON。"""


def build_scheduler_repair_prompt(raw_output: str, error: str, candidates: list[str]) -> str:
    return f"""你上一次的排序输出未通过系统校验。

【你的上次输出】
{raw_output}

【校验失败原因】{error}
【合法候选（next_speaker 只能取其中之一，或 null）】{", ".join(candidates) or "（空）"}

请重新只输出一个合法 JSON（next_speaker / continue_round / reason）。"""
