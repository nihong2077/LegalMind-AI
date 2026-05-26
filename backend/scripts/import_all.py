#!/usr/bin/env python3
"""
LegalMind AI — 统一向量知识库导入脚本（优化版）

核心优化:
1. 分片导入: batch_size 降至 16，embedding batch 降至 8，防止 OOM
2. 断点续传: 基于 JSON 进度文件记录每个 collection 的已导入 offset
3. 详细日志: 每个分片记录状态/进度/耗时/错误，支持文件日志
4. 速率限制: 分片间 sleep，避免 CPU/内存/IO 瞬时压力

数据源 → Collection 映射:
  data/law/laws.json                        → law_knowledge
  data/judge/cleaned/judge_cases_cleaned.json → judge_knowledge
  data/lawyer/cleaned/judge_cases_full.json   → judge_knowledge
  data/lawyer/cleaned/sentencing_guidelines.json → judge_knowledge
  data/lawyer/cleaned/defense_strategies.json    → lawyer_knowledge

用法:
  cd backend
  python -m scripts.import_all [--skip-law] [--skip-judge] [--skip-lawyer] [--resume] [--dry-run]
"""

import argparse
import gc
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

# 项目路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT.parent / "data"
QDRANT_LOCAL_PATH = DATA_DIR / "qdrant_data"
PROGRESS_DIR = PROJECT_ROOT / "scripts" / ".import_progress"
LOG_DIR = PROJECT_ROOT / "scripts" / ".import_logs"

sys.path.insert(0, str(PROJECT_ROOT))

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

# ====================================================================
# 配置参数
# ====================================================================

EMBEDDING_MODEL = str(PROJECT_ROOT / "models" / "Qwen" / "Qwen3-Embedding-0.6B")
EMBEDDING_DIM = 1024

# 自动检测 GPU
def _detect_device() -> str:
    """检测可用设备：优先 CUDA，其次 MPS，最后 CPU"""
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            print(f"[device] 检测到 CUDA GPU: {name}")
            return "cuda"
    except Exception:
        pass
    try:
        import torch
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            print("[device] 检测到 Apple MPS")
            return "mps"
    except Exception:
        pass
    print("[device] 未检测到 GPU，使用 CPU 模式（速度较慢）")
    return "cpu"

DEVICE = _detect_device()

# 根据设备类型动态调整参数
if DEVICE == "cuda":
    EMBED_BATCH_SIZE = 64
    UPSERT_BATCH_SIZE = 100
    SHARD_SIZE = 1000
    SHARD_SLEEP_SEC = 0.1
elif DEVICE == "mps":
    EMBED_BATCH_SIZE = 32
    UPSERT_BATCH_SIZE = 64
    SHARD_SIZE = 500
    SHARD_SLEEP_SEC = 0.2
else:  # cpu
    EMBED_BATCH_SIZE = 8       # CPU 上小批次更稳定
    UPSERT_BATCH_SIZE = 16     # 小批次写入，避免长耗时阻塞
    SHARD_SIZE = 200           # 更频繁的断点保存
    SHARD_SLEEP_SEC = 0.3      # 稍长休眠，避免 CPU 满载

BATCH_SLEEP_SEC = 0.0      # 嵌入批次间休眠（秒），0=不休眠
MAX_RETRIES = 3            # 写入失败重试次数
RETRY_DELAY_SEC = 5        # 重试间隔

# ====================================================================
# 日志配置
# ====================================================================


def setup_logging(log_name: str) -> logging.Logger:
    """配置双输出日志：控制台 + 文件"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"{log_name}_{timestamp}.log"

    logger = logging.getLogger("import_all")
    logger.setLevel(logging.DEBUG)

    # 控制台 — INFO 级别
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    ))

    # 文件 — DEBUG 级别（记录每个分片的详细信息）
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(funcName)s:%(lineno)d %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    logger.addHandler(ch)
    logger.addHandler(fh)
    logger.info("日志文件: %s", log_file)
    return logger


# ====================================================================
# 断点续传
# ====================================================================


def load_progress(collection: str, source_tag: str) -> int:
    """加载已导入的 offset（断点续传）"""
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    progress_file = PROGRESS_DIR / f"{collection}_{source_tag}.json"
    if progress_file.exists():
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            offset = data.get("offset", 0)
            total = data.get("total", 0)
            ts = data.get("last_updated", "")
            return offset
        except Exception:
            return 0
    return 0


def save_progress(collection: str, source_tag: str, offset: int, total: int, logger: logging.Logger):
    """保存导入进度"""
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    progress_file = PROGRESS_DIR / f"{collection}_{source_tag}.json"
    data = {
        "collection": collection,
        "source_tag": source_tag,
        "offset": offset,
        "total": total,
        "last_updated": datetime.now().isoformat(),
        "status": "in_progress" if offset < total else "completed",
    }
    with open(progress_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.debug("进度已保存: %s offset=%d/%d", source_tag, offset, total)


def reset_progress(collection: str, source_tag: str):
    """重置进度（用于全量重新导入）"""
    progress_file = PROGRESS_DIR / f"{collection}_{source_tag}.json"
    if progress_file.exists():
        progress_file.unlink()


# ====================================================================
# Embedding 引擎（单例，带速率限制）
# ====================================================================

_model: Optional[SentenceTransformer] = None


def get_model(logger: logging.Logger) -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("加载嵌入模型 %s (device=%s) ...", EMBEDDING_MODEL, DEVICE)
        t0 = time.time()
        try:
            _model = SentenceTransformer(
                EMBEDDING_MODEL, device=DEVICE,
                trust_remote_code=True, local_files_only=True,
            )
        except Exception:
            logger.warning("离线加载失败，尝试在线加载...")
            _model = SentenceTransformer(
                EMBEDDING_MODEL, device=DEVICE, trust_remote_code=True,
            )
        logger.info("模型加载完成, 耗时=%.1fs, 维度=%d",
                     time.time() - t0, _model.get_embedding_dimension())
    return _model


def embed_batch(texts: list[str], logger: logging.Logger) -> list[list[float]]:
    """批量编码，带速率限制"""
    model = get_model(logger)
    embeddings = model.encode(
        texts,
        batch_size=EMBED_BATCH_SIZE,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    # 批次间休眠，降低 CPU 峰值
    time.sleep(BATCH_SLEEP_SEC)
    return embeddings.tolist()


# ====================================================================
# Qdrant 管理
# ====================================================================


def get_qdrant_client() -> QdrantClient:
    os.makedirs(str(QDRANT_LOCAL_PATH), exist_ok=True)
    return QdrantClient(path=str(QDRANT_LOCAL_PATH))


def ensure_collection(client: QdrantClient, name: str, dim: int, logger: logging.Logger):
    """确保 collection 存在（不重建，保留已有数据以支持断点续传）"""
    if client.collection_exists(name):
        info = client.get_collection(name)
        logger.info("collection '%s' 已存在, 当前 %d 条向量", name, info.points_count)
    else:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        logger.info("创建 collection '%s' (dim=%d)", name, dim)


# ====================================================================
# 条文拆分（法律法规专用）
# ====================================================================

ARTICLE_PATTERN = re.compile(r"^第([一二三四五六七八九十百千零\d]+)条\s*", re.MULTILINE)


def chinese_num_to_int(cn: str) -> int:
    mapping = {
        "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
        "十": 10, "百": 100, "千": 1000,
    }
    if cn.isdigit():
        return int(cn)
    result = 0
    current = 0
    for ch in cn:
        if ch in mapping:
            val = mapping[ch]
            if val >= 10:
                if current == 0:
                    current = 1
                result += current * val
                current = 0
            else:
                current = val
    result += current
    return result


def split_law_into_articles(law: dict) -> list[dict]:
    """将一部法律拆分为条文级别记录"""
    title = law.get("title", "")
    law_type = law.get("type", "")
    office = law.get("office", "")
    content = law.get("content", "")
    publish = law.get("publish", "")
    status_raw = law.get("status", "")
    law_id = law.get("id", "")

    # 地方性法规整部一条
    if law_type == "地方性法规":
        return [_make_record(law, content[:8000] if len(content) > 8000 else content, "whole")]

    if not content or not content.strip():
        return [_make_record(law, f"{title}（无正文）", "empty")]

    # 按条文拆分
    matches = list(ARTICLE_PATTERN.finditer(content))
    if not matches:
        # 无条文结构，按段落拆分
        return _split_by_paragraphs(law, content, max_length=500)

    records = []
    for i, match in enumerate(matches):
        article_num = f"第{match.group(1)}条"
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        text = content[start:end].strip()

        # 长条文按段落拆分
        if len(text) > 1000:
            sub_texts = _split_text(text, max_length=800)
            for idx, sub in enumerate(sub_texts):
                records.append(_make_record(law, sub, "article_split",
                                            article_num=article_num + (f"（续{idx}）" if idx > 0 else "")))
        else:
            records.append(_make_record(law, text, "article", article_num=article_num))

    return records if records else [_make_record(law, content[:8000], "fallback")]


def _make_record(law: dict, content: str, split_type: str, article_num: str = "") -> dict:
    return {
        "law_name": law.get("title", ""),
        "law_type": law.get("type", ""),
        "article_number": article_num,
        "content": content,
        "office": law.get("office", ""),
        "status": law.get("status", "有效"),
        "publish_date": law.get("publish", ""),
        "law_id": law.get("id", ""),
        "split_type": split_type,
    }


def _split_by_paragraphs(law: dict, content: str, max_length: int = 500) -> list[dict]:
    paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 1 > max_length and current:
            chunks.append(current.strip())
            current = para
        else:
            current = current + "\n" + para if current else para
    if current.strip():
        chunks.append(current.strip())

    records = []
    for idx, chunk in enumerate(chunks):
        records.append(_make_record(law, chunk, "paragraph",
                                    article_num=f"段落{idx+1}" if len(chunks) > 1 else ""))
    return records if records else [_make_record(law, content[:8000], "fallback")]


def _split_text(text: str, max_length: int = 800) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 1 > max_length and current:
            chunks.append(current.strip())
            current = para
        else:
            current = current + "\n" + para if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [text[:max_length]]


# ====================================================================
# 通用分片导入引擎
# ====================================================================


def import_sharded(
    client: QdrantClient,
    collection: str,
    source_tag: str,
    items: list[tuple[str, dict]],   # [(embed_text, payload), ...]
    logger: logging.Logger,
    resume: bool = True,
    dry_run: bool = False,
):
    """
    分片导入核心引擎:
    - 按 UPSERT_BATCH_SIZE 分批嵌入 + 写入
    - 每 SHARD_SIZE 条记录保存一次断点
    - 分片间休眠 SHARD_SLEEP_SEC
    - 失败重试 MAX_RETRIES 次
    """
    total = len(items)
    if total == 0:
        logger.info("[%s] 无数据，跳过", source_tag)
        return

    # 断点续传
    start_offset = 0
    if resume:
        start_offset = load_progress(collection, source_tag)
        if start_offset >= total:
            logger.info("[%s] 已完成 (%d/%d)，跳过", source_tag, start_offset, total)
            return
        if start_offset > 0:
            logger.info("[%s] 断点续传: 从第 %d 条开始 (共 %d 条)", source_tag, start_offset, total)

    ensure_collection(client, collection, EMBEDDING_DIM, logger)

    t_start = time.time()
    shard_count = 0
    error_count = 0
    success_count = 0

    for i in range(start_offset, total, UPSERT_BATCH_SIZE):
        batch = items[i:i + UPSERT_BATCH_SIZE]
        texts = [t for t, _ in batch]
        payloads = [p for _, p in batch]

        # 1. 嵌入生成
        try:
            embeddings = embed_batch(texts, logger)
        except Exception as e:
            error_count += len(batch)
            logger.error("[%s] 嵌入失败 (offset=%d, batch=%d): %s",
                         source_tag, i, i // UPSERT_BATCH_SIZE + 1, e)
            # 嵌入失败跳过该批次，保存进度继续
            save_progress(collection, source_tag, i + UPSERT_BATCH_SIZE, total, logger)
            continue

        # 2. 构建 Qdrant points
        points = []
        for j, (emb, payload) in enumerate(zip(embeddings, payloads)):
            # 生成确定性 ID
            content_key = texts[j][:200] if texts[j] else str(i + j)
            pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{collection}:{source_tag}:{content_key}"))
            points.append(PointStruct(id=pid, vector=emb, payload=payload))

        # 3. 写入 Qdrant（带重试）
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if not dry_run:
                    client.upsert(collection_name=collection, points=points)
                success_count += len(points)
                break
            except Exception as e:
                logger.warning("[%s] 写入失败 (attempt=%d/%d, offset=%d): %s",
                               source_tag, attempt, MAX_RETRIES, i, e)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SEC)
                else:
                    error_count += len(points)
                    logger.error("[%s] 写入最终失败 (offset=%d): %s", source_tag, i, e)

        # 4. 进度日志
        done = min(i + UPSERT_BATCH_SIZE, total)
        shard_count += 1
        elapsed = time.time() - t_start
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0

        logger.info("[%s] %d/%d (%.1f%%) | 速率=%.1f条/s | ETA=%.0fs | 错误=%d",
                     source_tag, done, total, done * 100 / total, rate, eta, error_count)
        logger.debug("[%s] 分片详情: offset=%d, batch=%d, points=%d, elapsed=%.1fs",
                      source_tag, i, shard_count, len(points), elapsed)

        # 5. 保存断点（每 SHARD_SIZE 条或最后一批）
        if shard_count % (SHARD_SIZE // UPSERT_BATCH_SIZE) == 0 or done >= total:
            save_progress(collection, source_tag, done, total, logger)

        # 6. 分片间休眠
        time.sleep(SHARD_SLEEP_SEC)

        # 7. 定期 GC + 内存回收（每 20 批次，约 2000 条）
        if shard_count % 20 == 0:
            gc.collect()
            # GPU 显存回收
            if DEVICE == "cuda":
                try:
                    import torch
                    torch.cuda.empty_cache()
                except Exception:
                    pass

    elapsed = time.time() - t_start
    logger.info("[%s] 完成: %d/%d 成功, %d 错误, 耗时=%.1fs (%.1f条/s)",
                source_tag, success_count, total, error_count, elapsed,
                success_count / elapsed if elapsed > 0 else 0)

    # 最终标记完成
    if error_count == 0:
        save_progress(collection, source_tag, total, total, logger)


# ====================================================================
# 数据源加载
# ====================================================================


def load_law_items(logger: logging.Logger) -> list[tuple[str, dict]]:
    """加载法律法规数据 → law_knowledge"""
    source = DATA_DIR / "law" / "laws.json"
    if not source.exists():
        logger.warning("法律法规数据不存在: %s", source)
        return []

    logger.info("加载法律法规数据: %s", source)
    t0 = time.time()
    with open(source, "r", encoding="utf-8") as f:
        laws = json.load(f)
    logger.info("加载 %d 部法律法规 (%.1fs)", len(laws), time.time() - t0)

    # 拆分为条文
    items = []
    for law in laws:
        records = split_law_into_articles(law)
        for rec in records:
            embed_text = f"{rec['law_name']} {rec['article_number']} {rec['content'][:500]}"
            payload = {
                "law_name": rec["law_name"],
                "law_type": rec["law_type"],
                "article_number": rec.get("article_number", ""),
                "content": rec["content"][:4000],
                "office": rec.get("office", ""),
                "status": rec.get("status", "有效"),
                "publish_date": rec.get("publish_date", ""),
                "law_id": rec.get("law_id", ""),
                "source": "laws.json",
                "split_type": rec.get("split_type", ""),
                "imported_at": datetime.now().isoformat(),
            }
            items.append((embed_text, payload))

    logger.info("法律法规: %d 部 → %d 条条文记录", len(laws), len(items))
    return items


def load_judge_cleaned_items(logger: logging.Logger) -> list[tuple[str, dict]]:
    """加载裁判文书(已清洗) → judge_knowledge"""
    source = DATA_DIR / "judge" / "cleaned" / "judge_cases_cleaned.json"
    if not source.exists():
        logger.warning("裁判文书数据不存在: %s", source)
        return []

    with open(source, "r", encoding="utf-8") as f:
        cases = json.load(f)
    logger.info("加载裁判文书(已清洗): %d 条", len(cases))

    items = []
    for case in cases:
        embed_text = (
            f"案号: {case.get('case_number', '')}\n"
            f"案由: {case.get('cause_of_action', '')}\n"
            f"事实: {case.get('facts_summary', '')[:500]}\n"
            f"裁判理由: {case.get('judgment_reasoning', '')[:800]}"
        )
        if not embed_text.strip():
            continue
        payload = {
            "case_number": case.get("case_number", ""),
            "case_name": case.get("case_name", ""),
            "court_name": case.get("court_name", ""),
            "court_level": case.get("court_level", ""),
            "case_type": case.get("case_type", ""),
            "cause_of_action": case.get("cause_of_action", ""),
            "facts_summary": case.get("facts_summary", "")[:2000],
            "judgment_reasoning": case.get("judgment_reasoning", "")[:3000],
            "judgment_result": case.get("judgment_result", "")[:1000],
            "applicable_laws": case.get("applicable_laws", "")[:500],
            "keywords": case.get("keywords", []),
            "doc_type": "judge_case",
            "source": "judge_cases_cleaned.json",
            "imported_at": datetime.now().isoformat(),
        }
        items.append((embed_text, payload))

    logger.info("裁判文书(已清洗): %d 条有效", len(items))
    return items


def load_cail_judge_items(logger: logging.Logger) -> list[tuple[str, dict]]:
    """加载 CAIL2018 裁判文书 → judge_knowledge"""
    source = DATA_DIR / "lawyer" / "cleaned" / "judge_cases_full.json"
    if not source.exists():
        logger.warning("CAIL2018 裁判文书不存在: %s", source)
        return []

    logger.info("加载 CAIL2018 裁判文书: %s", source)
    t0 = time.time()
    with open(source, "r", encoding="utf-8") as f:
        cases = json.load(f)
    logger.info("加载 %d 条 CAIL2018 裁判文书 (%.1fs)", len(cases), time.time() - t0)

    items = []
    for case in cases:
        fact = case.get("facts_summary", "") or case.get("fact", "")
        if not fact or not fact.strip():
            continue
        embed_text = (
            f"案号: {case.get('case_number', '')}\n"
            f"案由: {case.get('cause_of_action', '')}\n"
            f"事实: {fact[:500]}\n"
            f"裁判结果: {case.get('judgment_result', '')[:300]}"
        )
        payload = {
            "case_number": case.get("case_number", ""),
            "case_name": case.get("case_name", ""),
            "court_level": case.get("court_level", ""),
            "case_type": case.get("case_type", "刑事"),
            "cause_of_action": case.get("cause_of_action", ""),
            "facts_summary": fact[:2000],
            "judgment_result": case.get("judgment_result", "")[:500],
            "applicable_laws": case.get("applicable_laws", "")[:500],
            "keywords": case.get("keywords", []),
            "doc_type": "cail2018_case",
            "source": "judge_cases_full.json",
            "imported_at": datetime.now().isoformat(),
        }
        items.append((embed_text, payload))

    logger.info("CAIL2018 裁判文书: %d 条有效", len(items))
    return items


def load_sentencing_items(logger: logging.Logger) -> list[tuple[str, dict]]:
    """加载量刑标准 → judge_knowledge"""
    source = DATA_DIR / "lawyer" / "cleaned" / "sentencing_guidelines.json"
    if not source.exists():
        logger.warning("量刑标准数据不存在: %s", source)
        return []

    with open(source, "r", encoding="utf-8") as f:
        guidelines = json.load(f)
    logger.info("加载量刑标准: %d 条", len(guidelines))

    items = []
    for g in guidelines:
        crime = g.get("crime_category", "")
        embed_text = (
            f"罪名: {crime}\n"
            f"量刑范围: {g.get('sentencing_range', '')}\n"
            f"加重情节: {g.get('aggravating_factors', '')}\n"
            f"减轻情节: {g.get('mitigating_factors', '')}\n"
            f"法律依据: {g.get('legal_basis', '')}"
        )
        payload = {
            "crime_category": crime,
            "sentencing_range": g.get("sentencing_range", ""),
            "aggravating_factors": g.get("aggravating_factors", "")[:1000],
            "mitigating_factors": g.get("mitigating_factors", "")[:1000],
            "typical_penalty": g.get("typical_penalty", ""),
            "legal_basis": g.get("legal_basis", "")[:1000],
            "doc_type": "sentencing_guideline",
            "source": "sentencing_guidelines.json",
            "imported_at": datetime.now().isoformat(),
        }
        items.append((embed_text, payload))

    logger.info("量刑标准: %d 条有效", len(items))
    return items


def load_defense_items(logger: logging.Logger) -> list[tuple[str, dict]]:
    """加载辩护策略 → lawyer_knowledge"""
    source = DATA_DIR / "lawyer" / "cleaned" / "defense_strategies.json"
    if not source.exists():
        logger.warning("辩护策略数据不存在: %s", source)
        return []

    with open(source, "r", encoding="utf-8") as f:
        strategies = json.load(f)
    logger.info("加载辩护策略: %d 条", len(strategies))

    items = []
    for s in strategies:
        name = s.get("strategy_name", "")
        embed_text = (
            f"策略: {name}\n"
            f"适用场景: {s.get('applicable_scenario', '')}\n"
            f"论证模板: {s.get('argument_template', '')}\n"
            f"证据要求: {s.get('evidence_requirements', '')}"
        )
        payload = {
            "strategy_name": name,
            "case_type": s.get("case_type", ""),
            "applicable_scenario": s.get("applicable_scenario", "")[:1000],
            "argument_template": s.get("argument_template", "")[:2000],
            "evidence_requirements": s.get("evidence_requirements", "")[:1000],
            "success_rate": s.get("success_rate", ""),
            "doc_type": "defense_strategy",
            "source": "defense_strategies.json",
            "imported_at": datetime.now().isoformat(),
        }
        items.append((embed_text, payload))

    logger.info("辩护策略: %d 条有效", len(items))
    return items


# ====================================================================
# 验证
# ====================================================================


def verify_import(client: QdrantClient, logger: logging.Logger):
    """验证导入结果：统计 + 简单查询测试"""
    logger.info("=" * 60)
    logger.info("验证导入结果")

    total_vectors = 0
    for name in ["law_knowledge", "judge_knowledge", "lawyer_knowledge"]:
        if client.collection_exists(name):
            info = client.get_collection(name)
            count = info.points_count
            total_vectors += count
            status = info.status
            logger.info("  %s: %d 条向量 (status=%s)", name, count, status)
        else:
            logger.warning("  %s: 未创建!", name)

    logger.info("  总计: %d 条向量", total_vectors)

    # 查询测试
    if total_vectors > 0:
        logger.info("执行查询测试...")
        try:
            model = get_model(logger)
            test_query = "借款合同纠纷"
            query_vec = model.encode([test_query], normalize_embeddings=True).tolist()[0]

            for name in ["law_knowledge", "judge_knowledge", "lawyer_knowledge"]:
                if client.collection_exists(name):
                    info = client.get_collection(name)
                    if info.points_count > 0:
                        results = client.query_points(
                            collection_name=name,
                            query=query_vec,
                            limit=3,
                        ).points
                        logger.info("  [%s] 查询'%s' → %d 条结果 (top1 score=%.3f)",
                                    name, test_query, len(results),
                                    results[0].score if results else 0)
        except Exception as e:
            logger.error("查询测试失败: %s", e)

    logger.info("=" * 60)


# ====================================================================
# Main
# ====================================================================


def main():
    parser = argparse.ArgumentParser(description="LegalMind AI 统一向量知识库导入（优化版）")
    parser.add_argument("--skip-law", action="store_true", help="跳过法律法规导入")
    parser.add_argument("--skip-judge", action="store_true", help="跳过裁判文书导入")
    parser.add_argument("--skip-lawyer", action="store_true", help="跳过律师知识导入")
    parser.add_argument("--resume", action="store_true", help="启用断点续传（默认全量重新导入）")
    parser.add_argument("--dry-run", action="store_true", help="仅模拟，不实际写入 Qdrant")
    parser.add_argument("--verify-only", action="store_true", help="仅验证已有数据")
    parser.add_argument("--reset", action="store_true", help="重置所有进度文件")
    args = parser.parse_args()

    logger = setup_logging("import_all")

    # 重置进度
    if args.reset:
        logger.info("重置所有进度文件...")
        for f in PROGRESS_DIR.glob("*.json"):
            f.unlink()
        logger.info("进度文件已清除")

    start = time.time()
    logger.info("=" * 60)
    logger.info("LegalMind AI 向量知识库统一导入")
    logger.info("Qdrant 路径: %s", QDRANT_LOCAL_PATH)
    logger.info("配置: embed_batch=%d, upsert_batch=%d, shard=%d, sleep=%.1fs",
                EMBED_BATCH_SIZE, UPSERT_BATCH_SIZE, SHARD_SIZE, SHARD_SLEEP_SEC)
    logger.info("断点续传: %s", "启用" if args.resume else "禁用（全量导入）")
    logger.info("=" * 60)

    client = get_qdrant_client()

    if args.verify_only:
        verify_import(client, logger)
        return

    # ---- 1. 法律法规 → law_knowledge ----
    if not args.skip_law:
        logger.info("\n" + "=" * 60)
        logger.info("1/5: 法律法规 → law_knowledge")
        logger.info("=" * 60)
        items = load_law_items(logger)
        import_sharded(
            client, "law_knowledge", "laws_json", items, logger,
            resume=args.resume, dry_run=args.dry_run,
        )

    # ---- 2. 裁判文书(已清洗) → judge_knowledge ----
    if not args.skip_judge:
        logger.info("\n" + "=" * 60)
        logger.info("2/5: 裁判文书(已清洗) → judge_knowledge")
        logger.info("=" * 60)
        items = load_judge_cleaned_items(logger)
        import_sharded(
            client, "judge_knowledge", "judge_cleaned", items, logger,
            resume=args.resume, dry_run=args.dry_run,
        )

    # ---- 3. CAIL2018 裁判文书 → judge_knowledge ----
    if not args.skip_judge:
        logger.info("\n" + "=" * 60)
        logger.info("3/5: CAIL2018 裁判文书 → judge_knowledge")
        logger.info("=" * 60)
        items = load_cail_judge_items(logger)
        import_sharded(
            client, "judge_knowledge", "cail2018_judge", items, logger,
            resume=args.resume, dry_run=args.dry_run,
        )

    # ---- 4. 量刑标准 → judge_knowledge ----
    if not args.skip_judge:
        logger.info("\n" + "=" * 60)
        logger.info("4/5: 量刑标准 → judge_knowledge")
        logger.info("=" * 60)
        items = load_sentencing_items(logger)
        import_sharded(
            client, "judge_knowledge", "sentencing", items, logger,
            resume=args.resume, dry_run=args.dry_run,
        )

    # ---- 5. 辩护策略 → lawyer_knowledge ----
    if not args.skip_lawyer:
        logger.info("\n" + "=" * 60)
        logger.info("5/5: 辩护策略 → lawyer_knowledge")
        logger.info("=" * 60)
        items = load_defense_items(logger)
        import_sharded(
            client, "lawyer_knowledge", "defense", items, logger,
            resume=args.resume, dry_run=args.dry_run,
        )

    # ---- 验证 ----
    verify_import(client, logger)

    elapsed = time.time() - start
    logger.info("\n总耗时: %.1fs (%.1fmin)", elapsed, elapsed / 60)
    logger.info("导入完成!")

    client.close()


if __name__ == "__main__":
    main()
