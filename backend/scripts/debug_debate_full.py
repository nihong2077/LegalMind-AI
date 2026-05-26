#!/usr/bin/env python3
"""完整调试：运行辩论工作流并打印每个节点的执行状态"""
import asyncio
import json
import sys
sys.path.insert(0, "/home/jing/Documents/trae_projects/LegalMind AI/backend")

from app.services.workflows import build_debate_workflow
from app.core.llm_client import get_llm_client


async def main():
    llm_client = get_llm_client()
    heavy_llm = llm_client.get_chat_model(model="deepseek-flash", temperature=0.7, max_tokens=512, streaming=True)
    workflow = build_debate_workflow(heavy_llm=heavy_llm)

    seen_nodes = set()
    speech_contents = {}

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

        if kind == "on_chain_start" and node and node not in seen_nodes:
            seen_nodes.add(node)
            print(f"\n▶ 节点开始: {node}")

        if kind == "on_chain_end" and node:
            output = event.get("data", {}).get("output", {})
            # 打印辩论发言节点的输出
            speech_nodes = [
                'judge_opening', 'plaintiff_opening', 'defendant_opening',
                'court_investigation', 'plaintiff_rebuttal', 'defendant_rebuttal',
                'judge_comment', 'judge_verdict', 'judgment_report', 'plain_language',
                'finalize',
            ]
            if node in speech_nodes:
                # 提取关键输出
                for key in ['focus_points', 'plaintiff_opening', 'defendant_opening',
                            'court_investigation', 'verdict', 'judgment_report',
                            'plain_language_version', 'final_result', 'converged',
                            'convergence_reason']:
                    val = output.get(key)
                    if val:
                        if isinstance(val, str):
                            preview = val[:150] + "..." if len(val) > 150 else val
                        else:
                            preview = val
                        print(f"  ✓ {key}: {preview}")

                # 检查 messages
                msgs = output.get("messages", [])
                if msgs:
                    for m in msgs[-3:]:
                        content = m.content if hasattr(m, 'content') else str(m)
                        print(f"  ✓ message: {content[:100]}...")

    print(f"\n\n=== 执行的节点列表 ===")
    for n in sorted(seen_nodes):
        print(f"  - {n}")


if __name__ == "__main__":
    asyncio.run(main())
