"""
记忆抽取器（P2 T2.2）

把「一轮对话 transcript」喂给轻量模型（Flash），抽取出**关于该用户**的结构化候选记忆。
输出严格 JSON（``{"memories": [...]}``）；解析失败/越界字段一律丢弃而不抛异常，
保证抽取器的失败不会污染写入管线（重试与 DLQ 由 consumer 负责）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from ...core.config import settings
from ...core.llm_client import get_llm_client

logger = logging.getLogger(__name__)

# 允许的记忆类型（与前端分类 Tab 对齐）
MEMORY_TYPES = ("fact", "preference", "background", "demand", "timeline")
SCOPES = ("user", "case")
MAX_CANDIDATES = 8

EXTRACT_SYSTEM_PROMPT = """你是法律 AI 系统的「长期记忆抽取器」。
从给定的一轮用户-AI 对话中，抽取**值得长期记住的、关于这位用户本人**的信息，输出 JSON。

只抽取以下五类：
- fact：客观事实（如"用户在杭州经营一家贸易公司"）
- preference：偏好（如"用户偏好中文答复、要求结论先行"）
- background：背景（如"用户是执业律师，主要做劳动争议"）
- demand：诉求（如"用户希望尽快拿到可提交仲裁的证据清单"）
- timeline：时间节点（如"用户的仲裁开庭在 2026 年 11 月"）

硬性规则：
1. 只记录用户明确表达或可可靠推断的信息；**不要**记录 AI 的话、不要记录寒暄、不要记录通用法律常识。
2. 每条记忆必须自足：脱离本轮对话也能读懂，主语统一用「用户」，第三人称陈述。
3. 严禁编造；不确定就不抽取。没有任何值得记住的信息时返回空数组。
4. importance 取 1-5（默认 3；关键诉求、硬性偏好给 4-5）。
5. scope 取 user（跨会话长期有效，默认）或 case（仅与当前案件相关）。

只输出如下 JSON，不要任何解释或代码块围栏：
{"memories": [{"memory_type": "preference", "content": "用户偏好中文答复并要求结论先行", "summary": "中文/结论先行", "importance": 4, "scope": "user"}]}"""


def build_extract_messages(transcript: list[dict[str, Any]]) -> list[dict[str, str]]:
    """transcript（消息行）→ LLM messages。"""
    lines: list[str] = []
    for m in transcript:
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        st = m.get("sender_type") or "agent"
        name = m.get("sender_name") or m.get("sender_id") or st
        lines.append(f"[{st}:{name}] {content}")
    body = "\n".join(lines) if lines else "（本轮无可用文本）"
    return [
        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": f"以下是本轮对话：\n{body}\n\n请只输出 JSON。"},
    ]


_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_candidates(raw: str) -> list[dict[str, Any]]:
    """从模型输出中稳健解析候选记忆；非法整体以空列表降级（由调用方决定是否重试）。"""
    if not raw:
        return []
    text = raw.strip()
    # 去掉 ```json ... ``` 围栏
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
    match = _JSON_OBJ_RE.search(text)
    if not match:
        logger.warning("[memory] 抽取输出未包含 JSON 对象，丢弃：%s", raw[:200])
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        logger.warning("[memory] 抽取 JSON 解析失败：%s（原文 %s）", e, raw[:200])
        return []

    items = data.get("memories") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content or content in seen:
            continue
        mtype = str(item.get("memory_type") or "fact").strip()
        if mtype not in MEMORY_TYPES:
            mtype = "fact"
        scope = str(item.get("scope") or "user").strip()
        if scope not in SCOPES:
            scope = "user"
        try:
            importance = int(item.get("importance") or 3)
        except (TypeError, ValueError):
            importance = 3
        importance = max(1, min(5, importance))
        seen.add(content)
        out.append(
            {
                "memory_type": mtype,
                "content": content,
                "summary": (str(item["summary"]).strip() or None)
                if item.get("summary")
                else None,
                "importance": importance,
                "scope": scope,
            }
        )
        if len(out) >= MAX_CANDIDATES:
            break
    return out


async def extract_candidates(
    transcript: list[dict[str, Any]],
    *,
    model: Optional[str] = None,
    llm: Any = None,
) -> list[dict[str, Any]]:
    """调用 Flash 模型抽取候选记忆。失败向上抛（由 consumer 重试/DLQ）。"""
    client = llm or get_llm_client()
    result = await client.chat(
        model or settings.MEMORY_EXTRACT_MODEL,
        build_extract_messages(transcript),
        temperature=0.2,
        max_tokens=1024,
    )
    choices = result.get("choices") or []
    if not choices:
        return []
    raw = (choices[0].get("message") or {}).get("content") or ""
    return parse_candidates(raw)
