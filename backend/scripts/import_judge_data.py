"""
裁判文书数据导入脚本 — 将清洗后的裁判文书数据导入 Qdrant + PostgreSQL

数据源: data/judge/cleaned/judge_cases_cleaned.json
目标表: judge_cases
目标 Qdrant Collection: judge_knowledge

用法:
    cd backend
    python3 -m scripts.import_judge_data [--input-file ../data/judge/cleaned/judge_cases_cleaned.json] [--skip-pg] [--skip-qdrant]
"""
import argparse
import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 默认输入文件路径
DEFAULT_INPUT_FILE = PROJECT_ROOT.parent / "data" / "judge" / "cleaned" / "judge_cases_cleaned.json"


# ============================================================
# PostgreSQL 写入
# ============================================================

async def write_to_pg(cases: list[dict]):
    """将案件数据写入 PostgreSQL"""
    try:
        from app.core.pg_client import JudgeCase, AsyncSession, law_engine, init_pg
        await init_pg()

        async with AsyncSession(law_engine) as session:
            for case in cases:
                row = JudgeCase(
                    case_number=case["case_number"],
                    case_name=case["case_name"],
                    court_level=case["court_level"],
                    court_name=case["court_name"],
                    case_type=case["case_type"],
                    cause_of_action=case["cause_of_action"],
                    judgment_date=case["judgment_date"],
                    plaintiff_claim=case["plaintiff_claim"],
                    defendant_defense=case["defendant_defense"],
                    facts_summary=case["facts_summary"],
                    judgment_reasoning=case["judgment_reasoning"],
                    judgment_result=case["judgment_result"],
                    applicable_laws=case["applicable_laws"],
                    keywords=case["keywords"],
                    embedding=case.get("embedding"),
                    source_file=case.get("source_file", ""),
                )
                session.add(row)
            await session.commit()
        logger.info(f"PostgreSQL: 写入 judge_cases {len(cases)} 条")
    except Exception as e:
        logger.error(f"PostgreSQL 写入失败: {e}")
        raise


# ============================================================
# Qdrant 写入
# ============================================================

async def write_to_qdrant(cases: list[dict]):
    """将案件数据写入 Qdrant judge_knowledge collection"""
    try:
        from app.core.qdrant_client import init_qdrant, upsert_vectors

        await init_qdrant()

        # 批量写入
        batch_size = 50
        total = len(cases)
        for i in range(0, total, batch_size):
            batch = cases[i:i + batch_size]
            vectors = [c["embedding"] for c in batch]
            payloads = []
            ids = []
            for c in batch:
                payload = {
                    "case_number": c["case_number"],
                    "case_name": c["case_name"],
                    "court_level": c["court_level"],
                    "court_name": c["court_name"],
                    "case_type": c["case_type"],
                    "cause_of_action": c["cause_of_action"],
                    "judgment_date": c["judgment_date"],
                    "plaintiff_claim": c["plaintiff_claim"],
                    "defendant_defense": c["defendant_defense"],
                    "facts_summary": c["facts_summary"],
                    "judgment_reasoning": c["judgment_reasoning"],
                    "judgment_result": c["judgment_result"],
                    "applicable_laws": c["applicable_laws"],
                    "keywords": c["keywords"],
                    "doc_type": "judge_case",
                }
                payloads.append(payload)
                # 生成确定性 ID（基于案号或内容哈希）
                content_hash = str(uuid.uuid5(uuid.NAMESPACE_URL, c["case_number"] or c["case_name"][:100]))
                ids.append(content_hash)

            await upsert_vectors(
                collection_name="judge_knowledge",
                vectors=vectors,
                payloads=payloads,
                ids=ids,
            )
            logger.info(
                "Qdrant: 写入 judge_knowledge %d/%d (batch %d)",
                min(i + batch_size, total), total, i // batch_size + 1,
            )
        logger.info(f"Qdrant: 写入 judge_knowledge 完成")
    except Exception as e:
        logger.error(f"Qdrant 写入失败: {e}")
        raise


# ============================================================
# 嵌入生成
# ============================================================

async def generate_embeddings(cases: list[dict], batch_size: int = 32):
    """为案件数据生成向量嵌入"""
    try:
        from app.core.embedding import embed_texts

        # 构建用于生成嵌入的文本（组合关键字段）
        texts = []
        for case in cases:
            text_parts = [
                case["case_name"],
                case["cause_of_action"],
                case["facts_summary"],
                case["judgment_reasoning"],
                case["applicable_laws"],
            ]
            combined_text = " ".join([t for t in text_parts if t])
            texts.append(combined_text)

        # 生成嵌入
        total = len(cases)
        for i in range(0, total, batch_size):
            batch_texts = texts[i:i + batch_size]
            batch_cases = cases[i:i + batch_size]
            try:
                embeddings = await embed_texts(batch_texts, batch_size=batch_size)
                for j, emb in enumerate(embeddings):
                    batch_cases[j]["embedding"] = emb
            except Exception as e:
                logger.error(f"嵌入生成失败 (batch {i // batch_size + 1}): {e}")
                for c in batch_cases:
                    c["embedding"] = None

        # 统计成功/失败数量
        success_count = sum(1 for c in cases if c.get("embedding") is not None)
        logger.info(f"嵌入生成完成: {success_count}/{len(cases)} 条成功")
        return [c for c in cases if c.get("embedding") is not None]
    except Exception as e:
        logger.error(f"嵌入生成失败: {e}")
        return cases


# ============================================================
# 主流程
# ============================================================

async def main(
    input_file: str = str(DEFAULT_INPUT_FILE),
    skip_pg: bool = False,
    skip_qdrant: bool = False,
):
    """主导入流程"""
    logger.info("=" * 60)
    logger.info("裁判文书数据导入开始")
    logger.info("输入文件: %s", input_file)
    logger.info("=" * 60)

    # 1. 加载数据
    logger.info("步骤 1/4: 加载清洗后的数据...")
    with open(input_file, "r", encoding="utf-8") as f:
        cases = json.load(f)
    logger.info(f"加载完成: {len(cases)} 个案件")

    # 2. 生成嵌入
    logger.info("步骤 2/4: 生成向量嵌入...")
    valid_cases = await generate_embeddings(cases)

    # 3. 写入 PostgreSQL
    if not skip_pg:
        logger.info("步骤 3/4: 写入 PostgreSQL...")
        await write_to_pg(valid_cases)
    else:
        logger.info("步骤 3/4: 跳过 PostgreSQL 写入")

    # 4. 写入 Qdrant
    if not skip_qdrant:
        logger.info("步骤 4/4: 写入 Qdrant...")
        await write_to_qdrant(valid_cases)
    else:
        logger.info("步骤 4/4: 跳过 Qdrant 写入")

    logger.info("=" * 60)
    logger.info(f"导入完成! 共处理 {len(valid_cases)} 条记录")
    logger.info("=" * 60)

    # 关闭连接
    try:
        from app.core.pg_client import close_pg
        await close_pg()
    except Exception:
        pass
    try:
        from app.core.qdrant_client import close_qdrant
        await close_qdrant()
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导入裁判文书数据到知识库")
    parser.add_argument("--input-file", default=str(DEFAULT_INPUT_FILE), help="清洗后的数据文件路径")
    parser.add_argument("--skip-pg", action="store_true", help="跳过 PostgreSQL 写入")
    parser.add_argument("--skip-qdrant", action="store_true", help="跳过 Qdrant 写入")
    args = parser.parse_args()

    asyncio.run(main(
        input_file=args.input_file,
        skip_pg=args.skip_pg,
        skip_qdrant=args.skip_qdrant,
    ))
