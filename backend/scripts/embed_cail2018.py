"""
CAIL2018 嵌入生成 + Qdrant 写入（纯同步、离线、断点续传）

用法: python -m scripts.embed_cail2018 [--batch-size 64] [--resume]
  --resume: 跳过已写入的记录（基于 collection 现有 point 数量）
"""

import gc
import json
import logging
import os
import time
import uuid
from pathlib import Path

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 路径
BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
QDRANT_PATH = str(DATA_DIR / "qdrant_data")
CLEANED_DIR = DATA_DIR / "lawyer" / "cleaned"
PROGRESS_FILE = CLEANED_DIR / "embed_progress.json"

BATCH_SIZE = 64


def load_model() -> SentenceTransformer:
    """离线加载嵌入模型"""
    logger.info("加载嵌入模型 Qwen/Qwen3-Embedding-0.6B (CPU, 离线)...")
    t0 = time.time()
    model = SentenceTransformer(
        "Qwen/Qwen3-Embedding-0.6B",
        device="cpu",
        trust_remote_code=True,
        local_files_only=True,
    )
    logger.info("模型加载完成, 耗时 %.1fs, 维度=%d", time.time() - t0, model.get_embedding_dimension())
    return model


def init_qdrant() -> QdrantClient:
    """初始化 Qdrant 本地客户端"""
    os.makedirs(QDRANT_PATH, exist_ok=True)
    client = QdrantClient(path=QDRANT_PATH)
    for name, dim in [("judge_knowledge", 1024), ("lawyer_knowledge", 1024)]:
        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            logger.info("创建 collection: %s", name)
    return client


def load_progress() -> dict:
    """加载断点续传进度"""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}


def save_progress(progress: dict):
    """保存进度"""
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)


def embed_and_upsert(
    model: SentenceTransformer,
    qdrant: QdrantClient,
    collection: str,
    records: list[dict],
    text_field: str,
    doc_type: str,
    resume_offset: int = 0,
):
    """同步嵌入 + 写入 Qdrant，支持断点续传"""
    total = len(records)
    if total == 0:
        logger.info("  [%s] 无数据，跳过", doc_type)
        return

    start = resume_offset
    if start >= total:
        logger.info("  [%s] 已完成 (%d/%d)，跳过", doc_type, start, total)
        return

    logger.info("  [%s] 开始嵌入: %d → %d (共 %d 条)", doc_type, start, total, total)
    t_start = time.time()

    for i in range(start, total, BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        texts = [
            r.get(text_field, "") or r.get("content", "") or r.get("argument_template", "")
            for r in batch
        ]

        # 过滤空文本
        valid_indices = [j for j, t in enumerate(texts) if t.strip()]
        if not valid_indices:
            continue

        valid_texts = [texts[j] for j in valid_indices]
        valid_records = [batch[j] for j in valid_indices]

        # 生成嵌入
        try:
            embeddings = model.encode(
                valid_texts,
                batch_size=BATCH_SIZE,
                show_progress_bar=False,
                normalize_embeddings=True,
            )
        except Exception as e:
            logger.error("  嵌入失败 (batch %d): %s", i // BATCH_SIZE + 1, e)
            continue

        # 构建 Qdrant points
        points = []
        for j, emb in enumerate(embeddings):
            rec = valid_records[j]
            payload = {
                "case_number": rec.get("case_number", ""),
                "case_name": rec.get("case_name", rec.get("strategy_name", rec.get("crime_category", ""))),
                "case_type": rec.get("case_type", ""),
                "doc_type": doc_type,
            }
            # 截断超长 payload 值
            for k, v in payload.items():
                if isinstance(v, str) and len(v) > 500:
                    payload[k] = v[:500]

            pid = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{doc_type}:{rec.get('case_number', str(i + valid_indices[j]))}",
            ))
            points.append(PointStruct(id=pid, vector=emb.tolist(), payload=payload))

        # 写入 Qdrant
        try:
            qdrant.upsert(collection_name=collection, points=points)
        except Exception as e:
            logger.error("  Qdrant 写入失败 (batch %d): %s", i // BATCH_SIZE + 1, e)
            continue

        # 进度日志（每 10 个 batch 或最后一批）
        batch_num = i // BATCH_SIZE + 1
        done = min(i + BATCH_SIZE, total)
        if batch_num % 10 == 0 or done >= total:
            elapsed = time.time() - t_start
            rate = done / elapsed if elapsed > 0 else 0
            eta = (total - done) / rate if rate > 0 else 0
            logger.info("  [%s] %d/%d (%.1f 条/s, ETA %.0fs)", doc_type, done, total, rate, eta)

        # 保存断点
        progress = load_progress()
        progress[f"{collection}_{doc_type}"] = done
        save_progress(progress)

        # 定期 GC
        if batch_num % 100 == 0:
            gc.collect()

    elapsed = time.time() - t_start
    logger.info("  [%s] 完成: %d 条, 耗时 %.1fs (%.1f 条/s)",
                doc_type, total, elapsed, total / elapsed if elapsed > 0 else 0)


def main():
    logger.info("=" * 60)
    logger.info("CAIL2018 嵌入生成 & Qdrant 写入 (离线同步版)")
    logger.info("Qdrant 路径: %s", QDRANT_PATH)
    logger.info("=" * 60)

    # 1. 加载清洗数据
    judge_json = CLEANED_DIR / "judge_cases_full.json"
    sentencing_json = CLEANED_DIR / "sentencing_guidelines.json"
    defense_json = CLEANED_DIR / "defense_strategies.json"

    if not judge_json.exists():
        logger.error("清洗数据不存在: %s，请先运行 import_cail2018", judge_json)
        return

    logger.info("加载清洗数据...")
    t0 = time.time()
    with open(judge_json, encoding="utf-8") as f:
        judge_cases = json.load(f)
    with open(sentencing_json, encoding="utf-8") as f:
        sentencing_guidelines = json.load(f)
    with open(defense_json, encoding="utf-8") as f:
        defense_strategies = json.load(f)
    logger.info("加载完成 (%.1fs): judge=%d, sentencing=%d, defense=%d",
                time.time() - t0, len(judge_cases), len(sentencing_guidelines), len(defense_strategies))

    # 2. 加载模型
    model = load_model()

    # 3. 初始化 Qdrant
    qdrant = init_qdrant()

    # 4. 读取断点
    progress = load_progress()
    logger.info("断点进度: %s", progress)

    # 5. 生成嵌入 + 写入
    logger.info("=" * 60)
    logger.info("1/3: judge_cases → judge_knowledge (%d 条)", len(judge_cases))
    embed_and_upsert(
        model, qdrant, "judge_knowledge", judge_cases,
        text_field="facts_summary", doc_type="judge_case",
        resume_offset=progress.get("judge_knowledge_judge_case", 0),
    )

    logger.info("=" * 60)
    logger.info("2/3: sentencing → judge_knowledge (%d 条)", len(sentencing_guidelines))
    embed_and_upsert(
        model, qdrant, "judge_knowledge", sentencing_guidelines,
        text_field="crime_category", doc_type="sentencing_guideline",
        resume_offset=progress.get("judge_knowledge_sentencing_guideline", 0),
    )

    logger.info("=" * 60)
    logger.info("3/3: defense → lawyer_knowledge (%d 条)", len(defense_strategies))
    embed_and_upsert(
        model, qdrant, "lawyer_knowledge", defense_strategies,
        text_field="argument_template", doc_type="defense_strategy",
        resume_offset=progress.get("lawyer_knowledge_defense_strategy", 0),
    )

    # 6. 最终统计
    logger.info("=" * 60)
    logger.info("最终统计:")
    for name in ["judge_knowledge", "lawyer_knowledge", "law_knowledge"]:
        if qdrant.collection_exists(name):
            info = qdrant.get_collection(name)
            logger.info("  %s: %d 条向量", name, info.points_count)

    qdrant.close()
    logger.info("全部完成!")


if __name__ == "__main__":
    main()
