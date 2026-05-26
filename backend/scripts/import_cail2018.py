"""
CAIL2018 数据集清洗与导入脚本 — 将刑事法律文书导入 Qdrant + PostgreSQL

数据源: data/lawyer/CAIL2018_ALL_DATA.zip (268万条刑事法律文书)
目标:
  - judge_db.judge_cases: 裁判文书（案件事实+罪名+刑期）
  - judge_db.sentencing_guidelines: 量刑标准（按罪名聚合）
  - lawyer_db.defense_strategies: 辩护策略（从案件事实中提取）

数据格式 (每行一条 JSON):
{
  "fact": "案情描述...",
  "meta": {
    "relevant_articles": [234],
    "accusation": ["故意伤害"],
    "punish_of_money": 0,
    "criminals": ["段某"],
    "term_of_imprisonment": {
      "death_penalty": false,
      "imprisonment": 12,
      "life_imprisonment": false
    }
  }
}

用法:
    cd backend
    python3 -m scripts.import_cail2018 [--max-records 50000] [--skip-pg] [--skip-qdrant] [--skip-unzip]
"""
import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
import zipfile
from collections import Counter, defaultdict
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

DEFAULT_ZIP_PATH = PROJECT_ROOT.parent / "data" / "lawyer" / "CAIL2018_ALL_DATA.zip"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT.parent / "data" / "lawyer" / "cleaned"

# 刑法条文号 → 条文名称映射（常用）
ARTICLE_NAMES = {
    232: "故意杀人罪", 233: "过失致人死亡罪", 234: "故意伤害罪",
    235: "过失致人重伤罪", 236: "强奸罪", 237: "强制猥亵罪",
    238: "非法拘禁罪", 239: "绑架罪", 240: "拐卖妇女、儿童罪",
    241: "收买被拐卖的妇女、儿童罪", 243: "诬告陷害罪",
    246: "侮辱罪、诽谤罪", 253: "侵犯公民个人信息罪",
    263: "抢劫罪", 264: "盗窃罪", 266: "诈骗罪",
    267: "抢夺罪", 268: "聚众哄抢罪", 270: "侵占罪",
    271: "职务侵占罪", 272: "挪用资金罪", 274: "敲诈勒索罪",
    275: "故意毁坏财物罪", 277: "妨害公务罪",
    291: "聚众扰乱社会秩序罪", 292: "聚众斗殴罪",
    293: "寻衅滋事罪", 300: "组织、利用会道门、邪教组织、利用迷信破坏法律实施罪",
    301: "聚众淫乱罪", 302: "盗窃、侮辱、故意毁坏尸体罪",
    303: "赌博罪、开设赌场罪", 310: "窝藏、包庇罪",
    312: "掩饰、隐瞒犯罪所得罪", 313: "拒不执行判决、裁定罪",
    317: "组织越狱罪", 320: "运送他人偷越国(边)境罪",
    347: "走私、贩卖、运输、制造毒品罪", 348: "非法持有毒品罪",
    358: "组织卖淫罪、强迫卖淫罪", 359: "引诱、容留、介绍卖淫罪",
    363: "制作、贩卖、传播淫秽物品罪", 382: "贪污罪",
    383: "贪污罪量刑", 384: "挪用公款罪", 385: "受贿罪",
    386: "受贿罪量刑", 388: "受贿罪", 389: "行贿罪",
    390: "行贿罪量刑", 392: "介绍贿赂罪", 395: "巨额财产来源不明罪",
    397: "滥用职权罪、玩忽职守罪", 402: "徇私舞弊不移交刑事案件罪",
    133: "交通肇事罪", 133_1: "危险驾驶罪",
    114: "放火罪、决水罪、爆炸罪", 115: "放火罪等量刑",
    140: "生产、销售伪劣产品罪", 141: "生产、销售假药罪",
    144: "生产、销售有毒、有害食品罪", 151: "走私贵重金属罪",
    170: "伪造货币罪", 176: "非法吸收公众存款罪",
    192: "集资诈骗罪", 196: "信用卡诈骗罪",
    205: "虚开增值税专用发票罪", 217: "侵犯著作权罪",
    224: "合同诈骗罪", 225: "非法经营罪",
    229: "提供虚假证明文件罪", 231: "单位犯罪",
}


def get_article_name(article_num: int) -> str:
    """获取刑法条文名称"""
    return ARTICLE_NAMES.get(article_num, f"刑法第{article_num}条")


def format_term_of_imprisonment(term: dict) -> str:
    """格式化刑期信息"""
    if not term:
        return "未知"

    parts = []
    if term.get("death_penalty"):
        parts.append("死刑")
    if term.get("life_imprisonment"):
        parts.append("无期徒刑")
    imprisonment = term.get("imprisonment", 0)
    if imprisonment > 0:
        if imprisonment >= 12:
            years = imprisonment // 12
            months = imprisonment % 12
            if months > 0:
                parts.append(f"有期徒刑{years}年{months}个月")
            else:
                parts.append(f"有期徒刑{years}年")
        else:
            parts.append(f"有期徒刑{imprisonment}个月")

    return "，".join(parts) if parts else "未知"


def classify_term_range(term: dict) -> str:
    """刑期分类（用于量刑标准聚合）"""
    if not term:
        return "未知"
    if term.get("death_penalty"):
        return "死刑"
    if term.get("life_imprisonment"):
        return "无期徒刑"
    imprisonment = term.get("imprisonment", 0)
    if imprisonment <= 0:
        return "免予刑事处罚"
    elif imprisonment <= 6:
        return "6个月以下"
    elif imprisonment <= 12:
        return "6个月-1年"
    elif imprisonment <= 36:
        return "1-3年"
    elif imprisonment <= 60:
        return "3-5年"
    elif imprisonment <= 120:
        return "5-10年"
    elif imprisonment <= 180:
        return "10-15年"
    else:
        return "15年以上"


# ============================================================
# 数据读取（支持流式读取大文件）
# ============================================================

def read_cail_from_zip(
    zip_path: str,
    max_records: int = 0,
    files_to_read: Optional[list[str]] = None,
) -> list[dict]:
    """从 zip 文件中流式读取 CAIL2018 数据"""
    records = []
    if files_to_read is None:
        # 优先使用 exercise_contest 数据（较小，约 15 万条）
        files_to_read = [
            "final_all_data/exercise_contest/data_train.json",
            "final_all_data/exercise_contest/data_valid.json",
            "final_all_data/exercise_contest/data_test.json",
        ]

    with zipfile.ZipFile(zip_path, "r") as z:
        available_files = z.namelist()
        for file_name in files_to_read:
            if file_name not in available_files:
                logger.warning(f"文件不存在: {file_name}")
                continue

            logger.info(f"读取: {file_name}")
            with z.open(file_name) as f:
                count = 0
                for line in f:
                    line = line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        records.append(data)
                        count += 1
                        if max_records > 0 and count >= max_records:
                            logger.info(f"  达到最大记录数 {max_records}，停止读取")
                            return records
                    except json.JSONDecodeError:
                        continue

            logger.info(f"  读取 {count} 条")

    return records


# ============================================================
# 数据清洗 — 转换为 judge_cases 格式
# ============================================================

def clean_to_judge_cases(records: list[dict]) -> list[dict]:
    """将 CAIL2018 数据转换为 judge_cases 格式"""
    cases = []
    for idx, r in enumerate(records):
        fact = r.get("fact", "")
        meta = r.get("meta", {})
        if not fact or not fact.strip():
            continue

        accusation_list = meta.get("accusation", [])
        accusation = accusation_list[0] if accusation_list else "未知"
        relevant_articles = meta.get("relevant_articles", [])
        criminals = meta.get("criminals", [])
        punish_of_money = meta.get("punish_of_money", 0)
        term = meta.get("term_of_imprisonment", {})

        # 生成案号（CAIL2018 无案号，生成唯一标识）
        case_number = f"CAIL2018-{idx:07d}"

        # 生成案件名称
        criminal_name = criminals[0] if criminals else "某"
        case_name = f"{criminal_name}{accusation}案"

        # 适用法律条文
        applicable_laws = "；".join(
            f"《刑法》第{a}条（{get_article_name(a)}）"
            for a in relevant_articles
        )

        case = {
            "case_number": case_number,
            "case_name": case_name,
            "court_level": "基层",  # CAIL2018 多为基层/中级
            "court_name": "",
            "case_type": "刑事",
            "cause_of_action": accusation,
            "judgment_date": "",
            "plaintiff_claim": "",  # 刑事案件无原告
            "defendant_defense": "、".join(criminals) if criminals else "",
            "facts_summary": fact[:2000],
            "judgment_reasoning": "",
            "judgment_result": format_term_of_imprisonment(term),
            "applicable_laws": applicable_laws,
            "keywords": accusation_list + [get_article_name(a) for a in relevant_articles[:3]],
            "metadata": {
                "source": "CAIL2018",
                "accusation": accusation_list,
                "relevant_articles": relevant_articles,
                "punish_of_money": punish_of_money,
                "term_of_imprisonment": term,
                "term_range": classify_term_range(term),
            },
        }
        cases.append(case)

    return cases


# ============================================================
# 数据清洗 — 聚合为量刑标准
# ============================================================

def aggregate_sentencing_guidelines(cases: list[dict]) -> list[dict]:
    """按罪名聚合案件，生成量刑标准"""
    # 按罪名分组
    accusation_groups = defaultdict(list)
    for case in cases:
        accusation = case["cause_of_action"]
        accusation_groups[accusation].append(case)

    guidelines = []
    for accusation, group in accusation_groups.items():
        if not group:
            continue

        # 统计刑期分布
        term_ranges = Counter()
        for case in group:
            term_range = case["metadata"].get("term_range", "未知")
            term_ranges[term_range] += 1

        # 统计相关法条
        article_counter = Counter()
        for case in group:
            for article in case["metadata"].get("relevant_articles", []):
                article_counter[article] += 1

        top_articles = article_counter.most_common(5)
        legal_basis = "；".join(
            f"《刑法》第{a}条（{get_article_name(a)}）"
            for a, _ in top_articles
        )

        # 量刑范围
        total = len(group)
        sentencing_parts = []
        for term_range, count in term_ranges.most_common():
            pct = count / total * 100
            if pct >= 5:
                sentencing_parts.append(f"{term_range}({pct:.1f}%)")
        sentencing_range = "，".join(sentencing_parts)

        # 加重/减轻情节（从事实描述中提取关键词）
        aggravating = []
        mitigating = []
        for case in group[:50]:
            fact = case["facts_summary"]
            if any(kw in fact for kw in ["累犯", "前科", "多次", "数额巨大", "情节恶劣"]):
                aggravating.append("具有加重情节")
            if any(kw in fact for kw in ["自首", "坦白", "赔偿", "谅解", "初犯", "偶犯"]):
                mitigating.append("具有减轻情节")

        guideline = {
            "crime_category": accusation,
            "crime_subcategory": "",
            "sentencing_range": sentencing_range,
            "aggravating_factors": "；".join(set(aggravating)) if aggravating else "暂无数据",
            "mitigating_factors": "；".join(set(mitigating)) if mitigating else "暂无数据",
            "typical_penalty": term_ranges.most_common(1)[0][0] if term_ranges else "未知",
            "legal_basis": legal_basis,
            "source_document": f"CAIL2018 数据集（{total}个样本）",
            "metadata": {
                "source": "CAIL2018",
                "sample_count": total,
                "term_distribution": dict(term_ranges.most_common(10)),
            },
        }
        guidelines.append(guideline)

    return guidelines


# ============================================================
# 数据清洗 — 提取辩护策略
# ============================================================

def extract_defense_strategies(cases: list[dict]) -> list[dict]:
    """从案件事实中提取常见辩护策略"""
    # 按罪名分组
    accusation_groups = defaultdict(list)
    for case in cases:
        accusation = case["cause_of_action"]
        accusation_groups[accusation].append(case)

    strategies = []
    # 辩护策略模板（基于常见刑事辩护方向）
    DEFENSE_TEMPLATES = {
        "故意伤害": [
            {
                "strategy_name": "故意伤害 — 正当防卫抗辩",
                "applicable_scenario": "被告人在遭受不法侵害时进行反击致人受伤",
                "argument_template": "根据《刑法》第二十条，为了使国家、公共利益、本人或者他人的人身、财产和其他权利免受正在进行的不法侵害，而采取的制止不法侵害的行为，对不法侵害人造成损害的，属于正当防卫，不负刑事责任。",
                "evidence_requirements": "需提供证明存在不法侵害、反击行为与侵害行为具有同时性、反击手段与侵害程度相当等证据",
            },
            {
                "strategy_name": "故意伤害 — 轻伤鉴定异议",
                "applicable_scenario": "被害人的伤情鉴定结论存在争议",
                "argument_template": "对被害人的伤情鉴定结论提出异议，申请重新鉴定。根据《刑事诉讼法》第一百四十六条，侦查机关应当将用作证据的鉴定意见告知犯罪嫌疑人、被害人，如果犯罪嫌疑人、被害人提出申请，可以补充鉴定或者重新鉴定。",
                "evidence_requirements": "需提供鉴定程序违法、鉴定依据不足、鉴定结论与病历不符等相关证据",
            },
            {
                "strategy_name": "故意伤害 — 赔偿谅解从轻",
                "applicable_scenario": "被告人愿意赔偿被害人并取得谅解",
                "argument_template": "被告人已积极赔偿被害人经济损失并取得谅解，根据《刑法》第六十七条及最高人民法院相关司法解释，可以酌定从轻处罚。",
                "evidence_requirements": "赔偿协议、谅解书、收据等",
            },
        ],
        "盗窃": [
            {
                "strategy_name": "盗窃 — 数额认定抗辩",
                "applicable_scenario": "盗窃数额的认定存在争议",
                "argument_template": "对盗窃数额的认定提出异议，认为原认定数额过高。根据《最高人民法院、最高人民检察院关于办理盗窃刑事案件适用法律若干问题的解释》，盗窃数额应当以实际损失为准。",
                "evidence_requirements": "物价鉴定报告、购买凭证、折旧计算等",
            },
            {
                "strategy_name": "盗窃 — 退赃退赔从轻",
                "applicable_scenario": "被告人已退还赃物或赔偿损失",
                "argument_template": "被告人已主动退赃退赔，挽回了被害人的经济损失，根据《刑法》第六十七条及相关司法解释，可以酌定从轻处罚。",
                "evidence_requirements": "退赃凭证、被害人收条、谅解书等",
            },
        ],
        "诈骗": [
            {
                "strategy_name": "诈骗 — 主观故意抗辩",
                "applicable_scenario": "被告人的主观故意不明确",
                "argument_template": "被告人不具有非法占有的主观故意，其行为属于民事纠纷而非诈骗。根据《刑法》第二百六十六条，诈骗罪要求行为人具有非法占有目的，若仅为经济纠纷则不构成诈骗罪。",
                "evidence_requirements": "合同、交易记录、还款计划等证明无非法占有目的的证据",
            },
        ],
        "交通肇事": [
            {
                "strategy_name": "交通肇事 — 自首从轻",
                "applicable_scenario": "肇事后主动报警并在现场等候处理",
                "argument_template": "被告人在交通肇事后主动报警并在现场等候处理，属于自首。根据《刑法》第六十七条，犯罪以后自动投案，如实供述自己的罪行的，是自首，对于自首的犯罪分子，可以从轻或者减轻处罚。",
                "evidence_requirements": "报警记录、到案经过说明、现场证人证言等",
            },
        ],
        "危险驾驶": [
            {
                "strategy_name": "危险驾驶 — 醉酒驾驶情节轻微",
                "applicable_scenario": "醉酒驾驶但未造成实际危害后果",
                "argument_template": "被告人虽醉酒驾驶，但行驶距离短、未造成任何交通事故或人员伤亡，情节显著轻微。根据《刑法》第十三条，情节显著轻微危害不大的，不认为是犯罪。",
                "evidence_requirements": "酒精含量检测报告、行驶距离证明、无事故证明等",
            },
        ],
    }

    # 通用辩护策略
    COMMON_STRATEGIES = [
        {
            "strategy_name": "自首从轻辩护",
            "case_type": "刑事",
            "applicable_scenario": "被告人主动投案或被采取强制措施后如实供述",
            "argument_template": "根据《刑法》第六十七条，犯罪以后自动投案，如实供述自己的罪行的，是自首。对于自首的犯罪分子，可以从轻或者减轻处罚。其中，犯罪较轻的，可以免除处罚。",
            "evidence_requirements": "到案经过说明、自首认定书、供述笔录等",
            "success_rate": "较高",
        },
        {
            "strategy_name": "坦白从轻辩护",
            "case_type": "刑事",
            "applicable_scenario": "被告人到案后如实供述自己罪行",
            "argument_template": "根据《刑法》第六十七条第三款，犯罪嫌疑人虽不具有前两款规定的自首情节，但是如实供述自己罪行的，可以从轻处罚；因其如实供述自己罪行，避免特别严重后果发生的，可以减轻处罚。",
            "evidence_requirements": "供述笔录、认罪认罚具结书等",
            "success_rate": "较高",
        },
        {
            "strategy_name": "初犯偶犯从轻辩护",
            "case_type": "刑事",
            "applicable_scenario": "被告人系初犯、偶犯",
            "argument_template": "被告人系初犯、偶犯，主观恶性较小，社会危害性不大，请求酌定从轻处罚。",
            "evidence_requirements": "无犯罪记录证明、社区评价等",
            "success_rate": "一般",
        },
        {
            "strategy_name": "认罪认罚从宽辩护",
            "case_type": "刑事",
            "applicable_scenario": "被告人自愿认罪认罚",
            "argument_template": "根据《刑事诉讼法》第十五条，犯罪嫌疑人、被告人自愿如实供述自己的罪行，承认指控的犯罪事实，愿意接受处罚的，可以依法从宽处理。",
            "evidence_requirements": "认罪认罚具结书、值班律师见证材料等",
            "success_rate": "较高",
        },
    ]

    # 添加罪名专属策略
    for accusation, templates in DEFENSE_TEMPLATES.items():
        count = len(accusation_groups.get(accusation, []))
        for tmpl in templates:
            strategy = {
                "strategy_name": tmpl["strategy_name"],
                "case_type": "刑事",
                "applicable_scenario": tmpl["applicable_scenario"],
                "argument_template": tmpl["argument_template"],
                "evidence_requirements": tmpl.get("evidence_requirements", ""),
                "success_rate": "一般",
                "reference_cases": f"基于CAIL2018数据集{count}个{accusation}案例",
            }
            strategies.append(strategy)

    # 添加通用策略
    strategies.extend(COMMON_STRATEGIES)

    return strategies


# ============================================================
# PostgreSQL 写入
# ============================================================

async def write_judge_cases_to_pg(cases: list[dict]):
    """写入 judge_cases 表"""
    from app.core.pg_client import JudgeCase, AsyncSession, judge_engine, init_pg
    await init_pg()

    batch_size = 500
    total = len(cases)
    for i in range(0, total, batch_size):
        batch = cases[i:i + batch_size]
        async with AsyncSession(judge_engine) as session:
            for case in batch:
                row = JudgeCase(
                    case_number=case["case_number"],
                    case_name=case["case_name"],
                    court_level=case["court_level"],
                    court_name=case["court_name"],
                    case_type=case["case_type"],
                    cause_of_action=case["cause_of_action"],
                    judgment_date=None,
                    plaintiff_claim=case["plaintiff_claim"],
                    defendant_defense=case["defendant_defense"],
                    facts_summary=case["facts_summary"],
                    judgment_reasoning=case["judgment_reasoning"],
                    judgment_result=case["judgment_result"],
                    applicable_laws=case["applicable_laws"],
                    keywords=case["keywords"],
                    embedding=case.get("embedding"),
                    source_metadata=case.get("metadata", {}),
                )
                session.add(row)
            await session.commit()
        logger.info(f"PostgreSQL judge_cases: {min(i + batch_size, total)}/{total}")


async def write_sentencing_to_pg(guidelines: list[dict]):
    """写入 sentencing_guidelines 表"""
    from app.core.pg_client import SentencingGuideline, AsyncSession, judge_engine, init_pg
    await init_pg()

    async with AsyncSession(judge_engine) as session:
        for g in guidelines:
            row = SentencingGuideline(
                crime_category=g["crime_category"],
                crime_subcategory=g["crime_subcategory"],
                sentencing_range=g["sentencing_range"],
                aggravating_factors=g["aggravating_factors"],
                mitigating_factors=g["mitigating_factors"],
                typical_penalty=g["typical_penalty"],
                legal_basis=g["legal_basis"],
                source_document=g["source_document"],
                embedding=g.get("embedding"),
                source_metadata=g.get("metadata", {}),
            )
            session.add(row)
        await session.commit()
    logger.info(f"PostgreSQL sentencing_guidelines: {len(guidelines)} 条")


async def write_defense_to_pg(strategies: list[dict]):
    """写入 defense_strategies 表"""
    from app.core.pg_client import DefenseStrategy, AsyncSession, lawyer_engine, init_pg
    await init_pg()

    async with AsyncSession(lawyer_engine) as session:
        for s in strategies:
            row = DefenseStrategy(
                strategy_name=s["strategy_name"],
                case_type=s.get("case_type", "刑事"),
                applicable_scenario=s.get("applicable_scenario", ""),
                argument_template=s.get("argument_template", ""),
                evidence_requirements=s.get("evidence_requirements", ""),
                success_rate=s.get("success_rate", ""),
                reference_cases=s.get("reference_cases", ""),
                embedding=s.get("embedding"),
                source_metadata={"source": "CAIL2018"},
            )
            session.add(row)
        await session.commit()
    logger.info(f"PostgreSQL defense_strategies: {len(strategies)} 条")


# ============================================================
# Qdrant 写入
# ============================================================

async def write_to_qdrant(collection_name: str, records: list[dict], doc_type: str):
    """写入 Qdrant"""
    from app.core.qdrant_client import init_qdrant, upsert_vectors
    await init_qdrant()

    batch_size = 100
    total = len(records)
    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        vectors = [r["embedding"] for r in batch]
        payloads = []
        ids = []
        for r in batch:
            payload = {k: v for k, v in r.items() if k != "embedding" and v is not None}
            payload["doc_type"] = doc_type
            payloads.append(payload)
            content_hash = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                r.get("case_number", "") or r.get("strategy_name", "") or r.get("crime_category", ""),
            ))
            ids.append(content_hash)

        await upsert_vectors(
            collection_name=collection_name,
            vectors=vectors,
            payloads=payloads,
            ids=ids,
        )
        logger.info(f"Qdrant {collection_name}: {min(i + batch_size, total)}/{total}")


# ============================================================
# 嵌入生成
# ============================================================

async def generate_embeddings(records: list[dict], text_field: str = "facts_summary", batch_size: int = 32):
    """为记录生成向量嵌入"""
    from app.core.embedding import embed_texts

    total = len(records)
    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        texts = [r.get(text_field, "") or r.get("content", "") or r.get("argument_template", "") for r in batch]
        try:
            embeddings = await embed_texts(texts, batch_size=batch_size)
            for j, emb in enumerate(embeddings):
                batch[j]["embedding"] = emb
        except Exception as e:
            logger.error(f"嵌入生成失败 (batch {i // batch_size + 1}): {e}")
            for r in batch:
                r["embedding"] = None

        if (i // batch_size + 1) % 50 == 0:
            logger.info(f"嵌入进度: {min(i + batch_size, total)}/{total}")


# ============================================================
# 主流程
# ============================================================

async def main(
    zip_path: str = str(DEFAULT_ZIP_PATH),
    max_records: int = 50000,
    skip_pg: bool = False,
    skip_qdrant: bool = False,
):
    """主导入流程"""
    logger.info("=" * 60)
    logger.info("CAIL2018 数据集导入开始")
    logger.info("数据文件: %s", zip_path)
    logger.info("最大记录数: %d", max_records)
    logger.info("=" * 60)

    # 1. 读取数据
    logger.info("步骤 1/7: 从 ZIP 中读取数据...")
    records = read_cail_from_zip(zip_path, max_records=max_records)
    logger.info(f"读取完成: {len(records)} 条原始记录")

    # 统计原始数据
    accusation_counter = Counter(r.get("meta", {}).get("accusation", ["未知"])[0] for r in records)
    logger.info(f"罪名分布 (Top 10):")
    for acc, count in accusation_counter.most_common(10):
        logger.info(f"  {acc}: {count}")

    # 2. 清洗为 judge_cases 格式
    logger.info("步骤 2/7: 清洗为 judge_cases 格式...")
    judge_cases = clean_to_judge_cases(records)
    logger.info(f"清洗完成: {len(judge_cases)} 条裁判文书")

    # 3. 聚合量刑标准
    logger.info("步骤 3/7: 聚合量刑标准...")
    sentencing_guidelines = aggregate_sentencing_guidelines(judge_cases)
    logger.info(f"生成 {len(sentencing_guidelines)} 条量刑标准")

    # 4. 提取辩护策略
    logger.info("步骤 4/7: 提取辩护策略...")
    defense_strategies = extract_defense_strategies(judge_cases)
    logger.info(f"生成 {len(defense_strategies)} 条辩护策略")

    # 保存清洗后的数据
    output_dir = Path(DEFAULT_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_dir / "judge_cases.json", "w", encoding="utf-8") as f:
        json.dump(judge_cases[:1000], f, ensure_ascii=False, indent=2)  # 只保存样本
    with open(output_dir / "sentencing_guidelines.json", "w", encoding="utf-8") as f:
        json.dump(sentencing_guidelines, f, ensure_ascii=False, indent=2)
    with open(output_dir / "defense_strategies.json", "w", encoding="utf-8") as f:
        json.dump(defense_strategies, f, ensure_ascii=False, indent=2)
    logger.info(f"清洗后数据已保存到: {output_dir}")

    # 5. 生成嵌入（仅 Qdrant 需要）
    if not skip_qdrant:
        logger.info("步骤 5/7: 生成向量嵌入...")
        logger.info("  生成 judge_cases 嵌入...")
        await generate_embeddings(judge_cases, text_field="facts_summary")
        logger.info("  生成 sentencing_guidelines 嵌入...")
        await generate_embeddings(sentencing_guidelines, text_field="crime_category")
        logger.info("  生成 defense_strategies 嵌入...")
        await generate_embeddings(defense_strategies, text_field="argument_template")

        valid_judge = [c for c in judge_cases if c.get("embedding") is not None]
        valid_sentencing = [g for g in sentencing_guidelines if g.get("embedding") is not None]
        valid_defense = [s for s in defense_strategies if s.get("embedding") is not None]
        logger.info(f"嵌入完成: judge={len(valid_judge)}, sentencing={len(valid_sentencing)}, defense={len(valid_defense)}")
    else:
        logger.info("步骤 5/7: 跳过向量嵌入（--skip-qdrant）")
        valid_judge = judge_cases
        valid_sentencing = sentencing_guidelines
        valid_defense = defense_strategies

    # 6. 写入 PostgreSQL
    if not skip_pg:
        logger.info("步骤 6/7: 写入 PostgreSQL...")
        try:
            await write_judge_cases_to_pg(valid_judge)
            await write_sentencing_to_pg(valid_sentencing)
            await write_defense_to_pg(valid_defense)
            logger.info("PostgreSQL 写入完成")
        except Exception as e:
            logger.error(f"PostgreSQL 写入失败: {e}")
    else:
        logger.info("步骤 6/7: 跳过 PostgreSQL 写入")

    # 7. 写入 Qdrant
    if not skip_qdrant:
        logger.info("步骤 7/7: 写入 Qdrant...")
        try:
            await write_to_qdrant("judge_knowledge", valid_judge, "judge_case")
            await write_to_qdrant("judge_knowledge", valid_sentencing, "sentencing_guideline")
            await write_to_qdrant("lawyer_knowledge", valid_defense, "defense_strategy")
            logger.info("Qdrant 写入完成")
        except Exception as e:
            logger.error(f"Qdrant 写入失败: {e}")
    else:
        logger.info("步骤 7/7: 跳过 Qdrant 写入")

    logger.info("=" * 60)
    logger.info(f"导入完成! judge={len(valid_judge)}, sentencing={len(valid_sentencing)}, defense={len(valid_defense)}")
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
    parser = argparse.ArgumentParser(description="导入 CAIL2018 数据集到知识库")
    parser.add_argument("--zip-path", default=str(DEFAULT_ZIP_PATH), help="CAIL2018 ZIP 文件路径")
    parser.add_argument("--max-records", type=int, default=50000, help="最大导入记录数（0=全部）")
    parser.add_argument("--skip-pg", action="store_true", help="跳过 PostgreSQL 写入")
    parser.add_argument("--skip-qdrant", action="store_true", help="跳过 Qdrant 写入")
    args = parser.parse_args()

    asyncio.run(main(
        zip_path=args.zip_path,
        max_records=args.max_records,
        skip_pg=args.skip_pg,
        skip_qdrant=args.skip_qdrant,
    ))
