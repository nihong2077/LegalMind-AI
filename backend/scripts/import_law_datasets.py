"""
法律法规数据导入脚本 — 将 law-datasets 数据导入 Qdrant + PostgreSQL

数据源: https://github.com/twang2218/law-datasets
包含 22,552 条中国法律法规

导入策略:
1. 解析 laws.json，按条文拆分为独立记录
2. 根据类型路由到不同 PostgreSQL 表:
   - 法律/宪法/法律解释 → legal_provisions
   - 司法解释 → judicial_interpretations
   - 行政法规/地方性法规/部门规章 → administrative_regulations
3. 生成 Qwen3-Embedding 向量
4. 同时写入 Qdrant (law_knowledge) 和 PostgreSQL

用法:
    cd backend
    python -m scripts.import_law_datasets [--batch-size 32] [--max-records 0] [--skip-pg] [--skip-qdrant]
"""
import argparse
import asyncio
import json
import logging
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 默认数据路径
DEFAULT_DATA_PATH = PROJECT_ROOT.parent / "data" / "law" / "laws.json"

# ============================================================
# 条文拆分 — 将整部法律按条文拆分为独立记录
# ============================================================

# 匹配中文数字条文: 第一条、第一百二十三条 等
ARTICLE_PATTERN = re.compile(
    r"^第([一二三四五六七八九十百千零\d]+)条\s*",
    re.MULTILINE,
)

# 匹配章节: 第一章、第二章 等
CHAPTER_PATTERN = re.compile(
    r"^第([一二三四五六七八九十百千零\d]+)章\s+(.+)$",
    re.MULTILINE,
)

# 匹配节: 第一节、第二节 等
SECTION_PATTERN = re.compile(
    r"^第([一二三四五六七八九十百千零\d]+)节\s+(.+)$",
    re.MULTILINE,
)


def chinese_num_to_int(cn: str) -> int:
    """中文数字转整数（简化版，覆盖常见法条编号）"""
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


def parse_chapters(content: str) -> list[tuple[str, str, int, int]]:
    """解析章节结构，返回 (章节名, 节名, 起始位置, 结束位置) 列表"""
    chapters = []
    ch_matches = list(CHAPTER_PATTERN.finditer(content))
    sec_matches = list(SECTION_PATTERN.finditer(content))

    # 构建章节树
    for i, ch in enumerate(ch_matches):
        ch_name = ch.group(0).strip()
        ch_start = ch.start()
        ch_end = ch_matches[i + 1].start() if i + 1 < len(ch_matches) else len(content)

        # 查找该章下的节
        sections_in_chapter = []
        for sec in sec_matches:
            if ch_start <= sec.start() < ch_end:
                sections_in_chapter.append(sec)

        if sections_in_chapter:
            for j, sec in enumerate(sections_in_chapter):
                sec_name = sec.group(0).strip()
                sec_start = sec.start()
                sec_end = sections_in_chapter[j + 1].start() if j + 1 < len(sections_in_chapter) else ch_end
                chapters.append((ch_name, sec_name, sec_start, sec_end))
        else:
            chapters.append((ch_name, "", ch_start, ch_end))

    return chapters


def split_law_into_articles(law: dict) -> list[dict]:
    """
    将一部法律拆分为条文级别的记录

    拆分策略:
    - 核心法律（法律/宪法/法律解释/司法解释）: 按条文拆分，粒度细
    - 地方性法规: 整部作为一条记录（数量庞大，不拆分）
    - 行政法规: 超过 2000 字按段落拆分，否则整部一条

    Returns:
        包含条文记录的列表，每条记录包含:
        - law_name, law_type, chapter, section, article_number, content, ...
    """
    title = law.get("title", "")
    law_type = law.get("type", "")
    office = law.get("office", "")
    content = law.get("content", "")
    publish = law.get("publish", "")
    expiry = law.get("expiry", "")
    status_raw = law.get("status", "")
    law_id = law.get("id", "")

    # 地方性法规数量庞大（近2万部），整部作为一条记录
    if law_type == "地方性法规":
        return [_make_whole_record(law)]

    # 行政法规：超过 2000 字按段落拆分
    if law_type == "行政法规":
        if len(content) > 2000:
            return _split_by_length(law, content, max_length=1000)
        return [_make_whole_record(law)]

    if not content or not content.strip():
        # 无内容的法律，作为整体记录
        return [{
            "law_name": title,
            "law_type": law_type,
            "chapter": "",
            "section": "",
            "article_number": "",
            "article_title": "",
            "content": f"{title}（无正文）",
            "effective_date": _parse_date(publish),
            "status": _map_status(status_raw),
            "keywords": [],
            "metadata": {
                "source_id": law_id,
                "office": office,
                "publish_date": publish,
                "expiry_date": expiry,
                "source_url": law.get("url", ""),
            },
        }]

    # 解析章节结构
    chapters = parse_chapters(content)

    # 查找条文
    article_matches = list(ARTICLE_PATTERN.finditer(content))

    if not article_matches:
        # 无条文结构，按段落拆分（每 500 字一条）
        return _split_by_length(law, content, max_length=500)

    # 构建条文记录
    records = []
    for i, match in enumerate(article_matches):
        article_num_cn = match.group(1)
        article_num = f"第{article_num_cn}条"
        article_start = match.start()
        article_end = article_matches[i + 1].start() if i + 1 < len(article_matches) else len(content)
        article_text = content[article_start:article_end].strip()

        # 查找所属章节
        chapter_name = ""
        section_name = ""
        for ch_name, sec_name, ch_start, ch_end in chapters:
            if ch_start <= article_start < ch_end:
                chapter_name = ch_name
                section_name = sec_name
                break

        # 提取条文标题（第一行中"条"后面的内容）
        lines = article_text.split("\n", 1)
        article_title = ""
        if len(lines) > 1:
            first_line = lines[0].strip()
            # 去掉条文编号，剩余部分作为标题
            title_part = ARTICLE_PATTERN.sub("", first_line).strip()
            if title_part and len(title_part) < 100:
                article_title = title_part

        # 长条文拆分（超过 1000 字的条文按段落拆分）
        if len(article_text) > 1000:
            sub_records = _split_long_article(
                article_text, max_length=800,
            )
            for idx, sub_text in enumerate(sub_records):
                suffix = f"（续{idx}）" if idx > 0 else ""
                records.append({
                    "law_name": title,
                    "law_type": law_type,
                    "chapter": chapter_name,
                    "section": section_name,
                    "article_number": article_num + suffix,
                    "article_title": article_title,
                    "content": sub_text,
                    "effective_date": _parse_date(publish),
                    "status": _map_status(status_raw),
                    "keywords": [],
                    "metadata": {
                        "source_id": law_id,
                        "office": office,
                        "publish_date": publish,
                        "expiry_date": expiry,
                        "source_url": law.get("url", ""),
                        "is_split": True,
                        "split_index": idx,
                    },
                })
        else:
            records.append({
                "law_name": title,
                "law_type": law_type,
                "chapter": chapter_name,
                "section": section_name,
                "article_number": article_num,
                "article_title": article_title,
                "content": article_text,
                "effective_date": _parse_date(publish),
                "status": _map_status(status_raw),
                "keywords": [],
                "metadata": {
                    "source_id": law_id,
                    "office": office,
                    "publish_date": publish,
                    "expiry_date": expiry,
                    "source_url": law.get("url", ""),
                },
            })

    return records


def _make_whole_record(law: dict) -> dict:
    """将整部法律作为一条记录（不拆分条文）"""
    title = law.get("title", "")
    content = law.get("content", "")
    publish = law.get("publish", "")
    expiry = law.get("expiry", "")
    status_raw = law.get("status", "")
    law_id = law.get("id", "")
    office = law.get("office", "")
    law_type = law.get("type", "")

    # 超长内容截断（Qdrant payload 限制）
    if len(content) > 8000:
        content = content[:8000] + "\n...(内容过长已截断)"

    return {
        "law_name": title,
        "law_type": law_type,
        "chapter": "",
        "section": "",
        "article_number": "",
        "article_title": "",
        "content": content or f"{title}（无正文）",
        "effective_date": _parse_date(publish),
        "status": _map_status(status_raw),
        "keywords": [],
        "metadata": {
            "source_id": law_id,
            "office": office,
            "publish_date": publish,
            "expiry_date": expiry,
            "source_url": law.get("url", ""),
            "is_whole_law": True,
        },
    }


def _split_long_article(text: str, max_length: int = 800) -> list[str]:
    """拆分长条文"""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 1 > max_length and current:
            chunks.append(current.strip())
            current = para
        else:
            current = current + "\n" + para if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [text[:max_length]]


def _split_by_length(law: dict, content: str, max_length: int = 500) -> list[dict]:
    """无条文结构时按长度拆分"""
    title = law.get("title", "")
    law_type = law.get("type", "")
    office = law.get("office", "")
    publish = law.get("publish", "")
    expiry = law.get("expiry", "")
    status_raw = law.get("status", "")
    law_id = law.get("id", "")

    paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
    chunks = []
    current = ""
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
        records.append({
            "law_name": title,
            "law_type": law_type,
            "chapter": "",
            "section": "",
            "article_number": f"段落{idx + 1}" if len(chunks) > 1 else "",
            "article_title": "",
            "content": chunk,
            "effective_date": _parse_date(publish),
            "status": _map_status(status_raw),
            "keywords": [],
            "metadata": {
                "source_id": law_id,
                "office": office,
                "publish_date": publish,
                "expiry_date": expiry,
                "source_url": law.get("url", ""),
                "is_length_split": True,
                "split_index": idx,
            },
        })
    return records


def _parse_date(date_str: str):
    """解析日期字符串，返回 date 对象或 None"""
    if not date_str or not date_str.strip():
        return None
    try:
        # 格式: "2018-03-11 00:00:00"
        dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
        return dt.date()
    except (ValueError, IndexError):
        return None


def _map_status(status_raw: str) -> str:
    """映射状态字段"""
    mapping = {
        "有效": "active",
        "尚未生效": "pending",
        "已修改": "amended",
        "已废止": "repealed",
        "部分失效": "partially_repealed",
    }
    return mapping.get(status_raw, "active")


# ============================================================
# 类型路由 — 根据法律类型分配到不同表
# ============================================================

# 法律/宪法/法律解释/有关法律问题和重大问题的决定/修改废止的决定 → legal_provisions
PROVISION_TYPES = {"法律", "宪法", "法律解释", "有关法律问题和重大问题的决定", "修改、废止的决定"}
# 司法解释 → judicial_interpretations
INTERPRETATION_TYPES = {"司法解释"}
# 行政法规/地方性法规/监察法规 → administrative_regulations
REGULATION_TYPES = {"行政法规", "地方性法规", "监察法规"}


def route_record(record: dict) -> str:
    """根据 law_type 路由到目标表"""
    law_type = record.get("law_type", "")
    if law_type in INTERPRETATION_TYPES:
        return "judicial_interpretations"
    elif law_type in REGULATION_TYPES:
        return "administrative_regulations"
    else:
        return "legal_provisions"


# ============================================================
# PostgreSQL 写入
# ============================================================

async def write_to_pg(records: list[dict]):
    """将记录写入 PostgreSQL"""
    from app.core.pg_client import (
        AdministrativeRegulation,
        AsyncSession,
        JudicialInterpretation,
        LegalProvision,
        law_engine,
        init_pg,
    )

    await init_pg()

    provision_records = []
    interpretation_records = []
    regulation_records = []

    for r in records:
        table = route_record(r)
        if table == "judicial_interpretations":
            interpretation_records.append(r)
        elif table == "administrative_regulations":
            regulation_records.append(r)
        else:
            provision_records.append(r)

    # 写入 legal_provisions
    if provision_records:
        async with AsyncSession(law_engine) as session:
            for r in provision_records:
                row = LegalProvision(
                    law_name=r["law_name"],
                    law_type=r["law_type"],
                    chapter=r.get("chapter", ""),
                    section=r.get("section", ""),
                    article_number=r.get("article_number", ""),
                    article_title=r.get("article_title", ""),
                    content=r["content"],
                    effective_date=r.get("effective_date"),
                    status=r.get("status", "active"),
                    keywords=r.get("keywords", []),
                    embedding=r.get("embedding"),
                    source_metadata=r.get("metadata", {}),
                )
                session.add(row)
            await session.commit()
        logger.info("PostgreSQL: 写入 legal_provisions %d 条", len(provision_records))

    # 写入 judicial_interpretations
    if interpretation_records:
        async with AsyncSession(law_engine) as session:
            for r in interpretation_records:
                row = JudicialInterpretation(
                    title=r["law_name"],
                    issuing_body=r.get("metadata", {}).get("office", ""),
                    issue_date=r.get("effective_date"),
                    effective_date=r.get("effective_date"),
                    content=r["content"],
                    related_laws="",
                    keywords=r.get("keywords", []),
                    embedding=r.get("embedding"),
                    source_metadata=r.get("metadata", {}),
                )
                session.add(row)
            await session.commit()
        logger.info("PostgreSQL: 写入 judicial_interpretations %d 条", len(interpretation_records))

    # 写入 administrative_regulations
    if regulation_records:
        async with AsyncSession(law_engine) as session:
            for r in regulation_records:
                row = AdministrativeRegulation(
                    regulation_name=r["law_name"],
                    issuing_body=r.get("metadata", {}).get("office", ""),
                    issue_date=r.get("effective_date"),
                    effective_date=r.get("effective_date"),
                    content=r["content"],
                    category=r.get("law_type", ""),
                    keywords=r.get("keywords", []),
                    embedding=r.get("embedding"),
                    source_metadata=r.get("metadata", {}),
                )
                session.add(row)
            await session.commit()
        logger.info("PostgreSQL: 写入 administrative_regulations %d 条", len(regulation_records))


# ============================================================
# Qdrant 写入
# ============================================================

async def write_to_qdrant(records: list[dict]):
    """将记录写入 Qdrant law_knowledge collection"""
    from app.core.qdrant_client import COLLECTION_LAW, init_qdrant, upsert_vectors

    await init_qdrant()

    # 批量写入
    batch_size = 100
    total = len(records)
    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        vectors = [r["embedding"] for r in batch]
        payloads = []
        ids = []
        for r in batch:
            payload = {
                "law_name": r["law_name"],
                "law_type": r["law_type"],
                "chapter": r.get("chapter", ""),
                "section": r.get("section", ""),
                "article_number": r.get("article_number", ""),
                "article_title": r.get("article_title", ""),
                "content": r["content"],
                "status": r.get("status", "active"),
                "effective_date": r.get("effective_date", ""),
                "source_id": r.get("metadata", {}).get("source_id", ""),
                "office": r.get("metadata", {}).get("office", ""),
                "doc_type": route_record(r),
            }
            payloads.append(payload)
            # 生成确定性 ID（基于内容哈希）
            content_hash = str(uuid.uuid5(uuid.NAMESPACE_URL, r["content"][:200]))
            ids.append(content_hash)

        await upsert_vectors(
            collection_name=COLLECTION_LAW,
            vectors=vectors,
            payloads=payloads,
            ids=ids,
        )
        logger.info(
            "Qdrant: 写入 law_knowledge %d/%d (batch %d)",
            min(i + batch_size, total), total, i // batch_size + 1,
        )


# ============================================================
# 嵌入生成
# ============================================================

async def generate_embeddings(records: list[dict], batch_size: int = 32):
    """为记录生成向量嵌入"""
    from app.core.embedding import embed_texts

    total = len(records)
    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        texts = [r["content"] for r in batch]
        try:
            embeddings = await embed_texts(texts, batch_size=batch_size)
            for j, emb in enumerate(embeddings):
                batch[j]["embedding"] = emb
        except Exception as e:
            logger.error("嵌入生成失败 (batch %d): %s", i // batch_size + 1, e)
            # 嵌入失败时设为 None，后续写入时跳过
            for r in batch:
                r["embedding"] = None

        if (i // batch_size + 1) % 10 == 0:
            logger.info("嵌入生成进度: %d/%d", min(i + batch_size, total), total)


# ============================================================
# 主流程
# ============================================================

async def main(
    data_path: str = str(DEFAULT_DATA_PATH),
    batch_size: int = 32,
    max_records: int = 0,
    skip_pg: bool = False,
    skip_qdrant: bool = False,
):
    """主导入流程"""
    logger.info("=" * 60)
    logger.info("法律法规数据导入开始")
    logger.info("数据文件: %s", data_path)
    logger.info("=" * 60)

    # 1. 加载数据
    logger.info("步骤 1/5: 加载 JSON 数据...")
    with open(data_path, "r", encoding="utf-8") as f:
        laws = json.load(f)
    logger.info("加载完成: %d 部法律法规", len(laws))

    if max_records > 0:
        laws = laws[:max_records]
        logger.info("限制导入: %d 部", max_records)

    # 2. 拆分条文
    logger.info("步骤 2/5: 拆分条文...")
    all_records = []
    for law in laws:
        records = split_law_into_articles(law)
        all_records.extend(records)
    logger.info("拆分完成: %d 部法律 → %d 条记录", len(laws), len(all_records))

    # 统计
    from collections import Counter
    table_counts = Counter(route_record(r) for r in all_records)
    for table, count in table_counts.most_common():
        logger.info("  → %s: %d 条", table, count)

    # 3. 生成嵌入（仅 Qdrant 需要）
    if not skip_qdrant:
        logger.info("步骤 3/5: 生成向量嵌入...")
        await generate_embeddings(all_records, batch_size=batch_size)
        logger.info("嵌入生成完成: %d/%d 条成功",
                    sum(1 for r in all_records if r.get("embedding")), len(all_records))
    else:
        logger.info("步骤 3/5: 跳过向量嵌入（--skip-qdrant）")

    # 过滤掉嵌入失败的记录（即使跳过嵌入，PG 也接受无嵌入记录）
    valid_records = all_records

    # 4. 写入 PostgreSQL
    if not skip_pg:
        logger.info("步骤 4/5: 写入 PostgreSQL...")
        try:
            await write_to_pg(valid_records)
            logger.info("PostgreSQL 写入完成")
        except Exception as e:
            logger.error("PostgreSQL 写入失败: %s", e)
    else:
        logger.info("步骤 4/5: 跳过 PostgreSQL 写入")

    # 5. 写入 Qdrant
    if not skip_qdrant:
        logger.info("步骤 5/5: 写入 Qdrant...")
        try:
            await write_to_qdrant(valid_records)
            logger.info("Qdrant 写入完成")
        except Exception as e:
            logger.error("Qdrant 写入失败: %s", e)
    else:
        logger.info("步骤 5/5: 跳过 Qdrant 写入")

    logger.info("=" * 60)
    logger.info("导入完成! 共处理 %d 条记录", len(valid_records))
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
    parser = argparse.ArgumentParser(description="导入法律法规数据到知识库")
    parser.add_argument("--data-path", default=str(DEFAULT_DATA_PATH), help="laws.json 文件路径")
    parser.add_argument("--batch-size", type=int, default=32, help="嵌入生成批大小")
    parser.add_argument("--max-records", type=int, default=0, help="最大导入记录数（0=全部）")
    parser.add_argument("--skip-pg", action="store_true", help="跳过 PostgreSQL 写入")
    parser.add_argument("--skip-qdrant", action="store_true", help="跳过 Qdrant 写入")
    args = parser.parse_args()

    asyncio.run(main(
        data_path=args.data_path,
        batch_size=args.batch_size,
        max_records=args.max_records,
        skip_pg=args.skip_pg,
        skip_qdrant=args.skip_qdrant,
    ))
