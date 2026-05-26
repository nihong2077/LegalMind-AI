#!/usr/bin/env python3
"""调试脚本：打印 LangGraph astream_events 的真实事件结构"""
import asyncio
import json
import sys
sys.path.insert(0, "/home/jing/Documents/trae_projects/LegalMind AI/backend")

from app.services.workflows import build_debate_workflow
from app.core.llm_client import get_llm_client


async def main():
    llm_client = get_llm_client()
    heavy_llm = llm_client.get_chat_model(model="deepseek-flash", temperature=0.7, max_tokens=256, streaming=True)
    workflow = build_debate_workflow(heavy_llm=heavy_llm)

    count = 0
    async for event in workflow.astream_events(
        {
            "messages": [],
            "case_description": "张三借给李四5万元，李四逾期不还",
            "evidence_summary": "借条一份",
            "task_type": "debate",
            "kfe": {},
            "evidence_sufficient": True,
            "interrupt_reason": "",
            "focus_points": "",
            "plaintiff_opening": "",
            "defendant_opening": "",
            "court_investigation": "",
            "current_round": 0,
            "plaintiff_args": [],
            "defendant_args": [],
            "judge_comments": [],
            "converged": False,
            "convergence_reason": "",
            "verdict": "",
            "judgment_report": "",
            "plain_language_version": "",
            "legal_knowledge": "",
            "final_result": "",
            "structured_summary": {},
        },
        version="v2",
    ):
        kind = event.get("event", "")
        metadata = event.get("metadata", {})
        node = metadata.get("langgraph_node", "")

        if kind == "on_chain_end" and node:
            output = event.get("data", {}).get("output", {})
            # 只打印关键节点的 output
            if node in ("extract_kfe", "retrieve_knowledge", "finalize",
                        "judge_opening", "plaintiff_opening", "defendant_opening"):
                # 截断长字符串
                out_preview = {}
                for k, v in output.items():
                    if isinstance(v, str) and len(v) > 100:
                        out_preview[k] = v[:100] + "..."
                    elif isinstance(v, list) and len(v) > 2:
                        out_preview[k] = f"[{len(v)} items]"
                    else:
                        out_preview[k] = v
                print(f"[on_chain_end] node={node} | output_keys={list(output.keys())} | preview={json.dumps(out_preview, ensure_ascii=False, default=str)[:300]}")

        count += 1
        if count >= 500:
            print("... 已收集 500 个事件，停止")
            break


if __name__ == "__main__":
    asyncio.run(main())
