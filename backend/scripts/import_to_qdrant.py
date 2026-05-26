#!/usr/bin/env python3
"""
LegalMind AI — 向量知识库统一导入脚本

将法律数据集导入 Qdrant 本地向量库（local mode，无需服务器）：
1. 法律法规 metadata (laws.json) → law_knowledge
2. 裁判文书 (judge_cases_cleaned.json) → judge_knowledge

使用 Qwen3-Embedding-0.6B 生成 1024 维向量。

用法: python import_to_qdrant.py [--skip-laws] [--skip-judge] [--batch-size 32]
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# 项目路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT.parent / "data"
QDRANT_LOCAL_PATH = PROJECT_ROOT.parent / "data" / "qdrant_data"

# 添加 backend 到 Python Path
sys.path.insert(0, str(PROJECT_ROOT))

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

# ====================================================================
# 配置
# ====================================================================

COLLECTIONS = {
    "law_knowledge": {
        "dim": 1024,
        "desc": "法律法规知识库",
        "source": DATA_DIR / "law" / "laws.json",
        "count": 22552,
    },
    "judge_knowledge": {
        "dim": 1024,
        "desc": "裁判文书案例库",
        "source": DATA_DIR / "judge" / "cleaned" / "judge_cases_cleaned.json",
        "count": 109,
    },
}

EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
BATCH_SIZE = 32
_batch_config = {"size": BATCH_SIZE}  # 可变容器，main 中覆盖

...
DEVICE = "cpu"  # cpu 模式兼容性最好

# ====================================================================
# Embedding 引擎
# ====================================================================

_model: Optional[SentenceTransformer] = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"[embed] 加载模型 {EMBEDDING_MODEL} (device={DEVICE}) ...")
        _model = SentenceTransformer(EMBEDDING_MODEL, device=DEVICE, trust_remote_code=True)
        dim = _model.get_embedding_dimension()
        print(f"[embed] 模型加载完成, 向量维度={dim}")
    return _model


def embed_batch(texts: list[str], show_progress: bool = True) -> list[list[float]]:
    """批量编码为向量"""
    model = get_model()
    embeddings = model.encode(
        texts,
        batch_size=_batch_config["size"],
        show_progress_bar=show_progress,
        normalize_embeddings=True,
    )
    return embeddings.tolist()


# ====================================================================
# Qdrant 管理
# ====================================================================

def get_qdrant_client() -> QdrantClient:
    os.makedirs(str(QDRANT_LOCAL_PATH), exist_ok=True)
    return QdrantClient(path=str(QDRANT_LOCAL_PATH))


def ensure_collection(client: QdrantClient, name: str, dim: int):
    existing = {c.name for c in client.get_collections().collections}
    if name in existing:
        print(f"[qdrant] collection '{name}' 已存在, 将重建 (recreate)")
        client.delete_collection(name)

    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )
    print(f"[qdrant] 创建 collection '{name}' (dim={dim})")


# ====================================================================
# Laws 导入
# ====================================================================

def import_laws(client: QdrantClient):
    """导入法律法规 metadata 到 legal_knowledge"""
    source = COLLECTIONS["law_knowledge"]["source"]
    print(f"\n{'='*60}")
    print(f"[import] 法律法规 → law_knowledge")
    print(f"[import] 源文件: {source}")

    if not source.exists():
        print("[import] 源文件不存在, 跳过")
        return

    with open(source, "r", encoding="utf-8") as f:
        laws = json.load(f)
    print(f"[import] 共 {len(laws)} 条法律法规")

    ensure_collection(client, "law_knowledge", 1024)

    total, points = len(laws), []
    for i, law in enumerate(laws):
        title = law.get("title", "").strip()
        law_type = law.get("type", "")
        office = law.get("office", "")
        status = law.get("status", "有效")
        publish = law.get("publish", "")

        if not title:
            continue

        # 用于 embedding 的文本：标题 + 类型 + 发布机构
        embed_text = f"{title} [{law_type}] 发布机构: {office}"
        payload = {
            "law_id": law.get("id", ""),
            "title": title,
            "type": law_type,
            "office": office,
            "status": status,
            "publish_date": publish,
            "source": "laws.json",
            "imported_at": datetime.now().isoformat(),
        }
        points.append((embed_text, payload))

        # 每 1000 条报告进度
        if (i + 1) % 5000 == 0:
            print(f"[import] 已准备 {i+1}/{total} 条...")

    print(f"[import] 有效条目: {len(points)}")

    # 批量编码并写入
    upload_points(client, "law_knowledge", points, "法律法规")


def upload_points(client: QdrantClient, collection: str, items: list[tuple[str, dict]], label: str):
    """批量编码并上传到 Qdrant"""
    total = len(items)
    bs = _batch_config["size"]
    if total == 0:
        return

    print(f"[embed] {label}: 生成向量... ({total} 条, batch_size={bs})")

    point_id = 0
    for i in range(0, total, bs):
        batch = items[i:i + bs]
        texts = [t for t, _ in batch]
        embeddings = embed_batch(texts, show_progress=False)

        points = []
        for j, (_, payload) in enumerate(batch):
            points.append(PointStruct(
                id=point_id,
                vector=embeddings[j],
                payload=payload,
            ))
            point_id += 1

        client.upsert(collection_name=collection, points=points)

        if (i + bs) % 320 == 0 or i + bs >= total:
            pct = min(100, (i + bs) * 100 // total)
            print(f"[import] {label}: {min(i + bs, total)}/{total} ({pct}%)")

    print(f"[import] {label}: 完成! 共导入 {total} 条")


# ====================================================================
# Judge Cases 导入
# ====================================================================

def import_judge_cases(client: QdrantClient):
    """导入裁判文书到 judge_cases"""
    source = COLLECTIONS["judge_knowledge"]["source"]
    print(f"\n{'='*60}")
    print(f"[import] 裁判文书 → judge_knowledge")
    print(f"[import] 源文件: {source}")

    if not source.exists():
        print("[import] 源文件不存在, 跳过")
        return

    with open(source, "r", encoding="utf-8") as f:
        cases = json.load(f)
    print(f"[import] 共 {len(cases)} 条裁判文书")

    ensure_collection(client, "judge_knowledge", 1024)

    items = []
    for case in cases:
        case_number = case.get("case_number", "")
        court_name = case.get("court_name", "")
        case_type = case.get("case_type", "")
        cause_of_action = case.get("cause_of_action", "")
        facts = case.get("facts_summary", "")
        reasoning = case.get("judgment_reasoning", "")
        plaintiff = case.get("plaintiff_claim", "")
        defendant = case.get("defendant_defense", "")
        judgment_date = case.get("judgment_date", "")

        # 组合裁判理由 + 事实摘要 作为 embedding 文本
        embed_text = f"案号: {case_number}\n案由: {cause_of_action}\n事实: {facts[:500]}\n裁判理由: {reasoning[:800]}"
        if not embed_text.strip():
            continue

        payload = {
            "case_number": case_number,
            "court_name": court_name,
            "court_level": case.get("court_level", ""),
            "case_type": case_type,
            "cause_of_action": cause_of_action,
            "judgment_date": judgment_date,
            "facts_summary": facts[:2000],
            "judgment_reasoning": reasoning[:3000],
            "plaintiff_claim": plaintiff[:1000],
            "defendant_defense": defendant[:1000],
            "source": "judge_cases_cleaned.json",
            "imported_at": datetime.now().isoformat(),
        }
        items.append((embed_text, payload))

    print(f"[import] 有效条目: {len(items)}")
    upload_points(client, "judge_knowledge", items, "裁判文书")


# ====================================================================
# 验证
# ====================================================================

def verify_import(client: QdrantClient):
    """验证导入结果"""
    print(f"\n{'='*60}")
    print("[verify] 验证导入结果")
    for name, cfg in COLLECTIONS.items():
        try:
            info = client.get_collection(name)
            count = info.points_count if info else 0
            print(f"  {name}: {count} 条向量 ({cfg['desc']})")
        except Exception:
            print(f"  {name}: 未创建")


# ====================================================================
# Main
# ====================================================================

def main():
    parser = argparse.ArgumentParser(description="LegalMind AI 向量知识库导入")
    parser.add_argument("--skip-laws", action="store_true", help="跳过低条导入")
    parser.add_argument("--skip-judge", action="store_true", help="跳过裁判文书导入")
    parser.add_argument("--batch-size", type=int, default=_batch_config["size"], help="批处理大小")
    parser.add_argument("--verify-only", action="store_true", help="仅验证已有数据")
    args = parser.parse_args()

    _batch_config["size"] = args.batch_size

    start = time.time()
    print(f"[init] Qdrant 本地路径: {QDRANT_LOCAL_PATH}")

    client = get_qdrant_client()

    if args.verify_only:
        verify_import(client)
        return

    if not args.skip_laws:
        import_laws(client)

    if not args.skip_judge:
        import_judge_cases(client)

    verify_import(client)

    elapsed = time.time() - start
    print(f"\n[完成] 总耗时: {elapsed:.1f}s ({elapsed/60:.1f}min)")


if __name__ == "__main__":
    main()