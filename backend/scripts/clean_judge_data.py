"""
裁判文书数据清洗脚本 — 将原始判决文本书写为结构化数据，适配向量存储

数据源: data/judge/ 目录下的裁判文书文本文件
目标: 解析为 judge_cases 表结构，并生成向量嵌入

解析策略:
1. 使用正则表达式提取关键信息（案号、法院、当事人、案由等）
2. 识别判决书中的各个部分（案件事实、本院认为、判决结果、法律依据）
3. 清洗文本，去除多余格式符
4. 生成适合向量检索的内容

用法:
    cd backend
    python -m scripts.clean_judge_data [--input-dir ../data/judge] [--output-dir ../data/judge/cleaned]
"""
import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime
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

# ============================================================
# 正则表达式模式定义
# ============================================================

# 案号模式：(2025)最高法知民终820号、(2025)吉01知民初64号
CASE_NUMBER_PATTERN = re.compile(
    r"（(\d{4})）([^\s]+?)终?第?(\d+)号",
    re.DOTALL,
)

# 法院层级映射
COURT_LEVEL_MAP = {
    "最高人民法院": "最高",
    "高级人民法院": "高级",
    "中级人民法院": "中级",
    "基层人民法院": "基层",
}

# 案件类型关键字
CASE_TYPE_KEYWORDS = {
    "民事": ["民事", "借款", "合同", "侵权", "婚姻", "继承", "劳动"],
    "刑事": ["刑事", "盗窃", "诈骗", "贪污", "受贿", "故意伤害"],
    "行政": ["行政", "复议", "处罚", "许可"],
    "知识产权": ["专利", "商标", "著作权", "知产", "技术秘密"],
}

# ============================================================
# 数据清洗函数
# ============================================================


def clean_text(text: str) -> str:
    """清洗文本，去除多余格式符和空白"""
    if not text:
        return ""

    # 去除特殊字符
    text = text.replace("\u3000", " ").replace("\xa0", " ")

    # 去除多余空白
    text = re.sub(r"\s+", " ", text)

    # 去除首尾空白
    text = text.strip()

    return text


def extract_case_number(text: str) -> str:
    """提取案号"""
    match = CASE_NUMBER_PATTERN.search(text)
    if match:
        year = match.group(1)
        court_code = match.group(2)
        case_num = match.group(3)
        return f"({year}){court_code}第{case_num}号"
    return ""


def extract_court_name(text: str) -> str:
    """提取法院名称"""
    patterns = [
        r"中华人民共和国最高人民法院",
        r"([^\s]+?高级人民法院)",
        r"([^\s]+?中级人民法院)",
        r"([^\s]+?人民法院)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1) if match.groups() else match.group(0)
    return ""


def extract_court_level(court_name: str) -> str:
    """从法院名称推断法院层级"""
    for full_name, level in COURT_LEVEL_MAP.items():
        if full_name in court_name:
            return level
    return "基层"


def extract_case_type(text: str) -> str:
    """推断案件类型"""
    text_lower = text.lower()
    for case_type, keywords in CASE_TYPE_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in text_lower:
                return case_type
    return "民事"


def extract_parties(text: str) -> tuple[str, str]:
    """提取原告/上诉人、被告/被上诉人信息"""
    plaintiff = ""
    defendant = ""

    # 提取上诉人
    appeal_match = re.search(r"上诉人（[^）]+）：(.+?)(?=。|\n|被告|被上诉人)", text, re.DOTALL)
    if appeal_match:
        plaintiff = appeal_match.group(1).strip()

    # 提取被上诉人
    beishang_match = re.search(r"被上诉人（[^）]+）：(.+?)(?=。|\n|上诉人|原告)", text, re.DOTALL)
    if beishang_match:
        defendant = beishang_match.group(1).strip()

    # 如果没有上诉人/被上诉人，提取原告/被告
    if not plaintiff:
        plaintiff_match = re.search(r"原告（[^）]+）：(.+?)(?=。|\n|被告)", text, re.DOTALL)
        if plaintiff_match:
            plaintiff = plaintiff_match.group(1).strip()

    if not defendant:
        defendant_match = re.search(r"被告（[^）]+）：(.+?)(?=。|\n|原告|第三人)", text, re.DOTALL)
        if defendant_match:
            defendant = defendant_match.group(1).strip()

    return (clean_text(plaintiff), clean_text(defendant))


def extract_judgment_date(text: str) -> str:
    """提取判决日期"""
    patterns = [
        r"于(\d{4})年(\d{1,2})月(\d{1,2})日作出",
        r"(\d{4})年(\d{1,2})月(\d{1,2})日立案",
        r"(\d{4})年(\d{1,2})月(\d{1,2})日",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                year, month, day = match.group(1), match.group(2), match.group(3)
                return f"{year}-{int(month):02d}-{int(day):02d}"
            except ValueError:
                continue
    return ""


def extract_facts(text: str) -> str:
    """提取案件事实部分"""
    # 匹配"本院认为"之前的事实部分
    match = re.search(r"(本院认为|本院经审理认为|本院认为，)", text)
    if match:
        facts_section = text[: match.start()]
        # 去除前面的当事人信息部分
        facts_section = re.sub(r"上诉人[^。]+。\s*", "", facts_section)
        facts_section = re.sub(r"被上诉人[^。]+。\s*", "", facts_section)
        facts_section = re.sub(r"原告[^。]+。\s*", "", facts_section)
        facts_section = re.sub(r"被告[^。]+。\s*", "", facts_section)
        return clean_text(facts_section)[:2000]
    return clean_text(text[:3000])


def extract_reasoning(text: str) -> str:
    """提取判决理由部分（本院认为）"""
    match = re.search(r"(本院认为|本院经审理认为)(.+?)(?=判决如下|依照|综上|判决：)", text, re.DOTALL)
    if match:
        return clean_text(match.group(2))[:3000]
    # 如果没有找到结束标记，取"本院认为"之后的内容
    match = re.search(r"(本院认为|本院经审理认为)(.+)", text, re.DOTALL)
    if match:
        return clean_text(match.group(2))[:3000]
    return ""


def extract_result(text: str) -> str:
    """提取判决结果部分"""
    patterns = [
        r"(判决如下|判决：)(.+?)(?=案件受理费|诉讼费用|如不服|本判决)",
        r"(一、|二、|三、)(.+?)(?=案件受理费|诉讼费用|如不服|本判决)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return clean_text(match.group(2))[:2000]
    return ""


def extract_applicable_laws(text: str) -> str:
    """提取适用法律条文"""
    patterns = [
        r"依照(.+?)(?=之规定|的规定|规定，|判决如下|判决：)",
        r"根据(.+?)(?=之规定|的规定|规定，)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            result = clean_text(match.group(1))
            # 提取法律名称
            laws = re.findall(r"《[^》]+》", result)
            if laws:
                return "; ".join(laws)[:500]
            return result[:500]
    return ""


def extract_cause_of_action(text: str) -> str:
    """提取案由"""
    patterns = [
        r"(侵害|纠纷|合同|赔偿|责任).+?(纠纷|一案)",
        r"(因).+?(纠纷|一案)",
        r"(案由：)(.+?)(?=。|\n)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return clean_text(match.group(0))[:100]
    return ""


def generate_keywords(case: dict) -> list[str]:
    """生成关键词标签"""
    keywords = []

    # 从案件类型添加关键词
    case_type = case.get("case_type", "")
    if case_type == "民事":
        keywords.extend(["民事", "民法"])
    elif case_type == "刑事":
        keywords.extend(["刑事", "刑法"])
    elif case_type == "行政":
        keywords.extend(["行政", "行政法"])
    elif case_type == "知识产权":
        keywords.extend(["知识产权", "专利", "商标"])

    # 从案由提取关键词
    cause = case.get("cause_of_action", "")
    if "合同" in cause:
        keywords.append("合同")
    if "侵权" in cause:
        keywords.append("侵权")
    if "借款" in cause:
        keywords.append("借款")
    if "专利" in cause:
        keywords.append("专利")
    if "商标" in cause:
        keywords.append("商标")

    # 从适用法律提取关键词
    laws = case.get("applicable_laws", "")
    if "民法典" in laws:
        keywords.append("民法典")
    if "专利法" in laws:
        keywords.append("专利法")
    if "商标法" in laws:
        keywords.append("商标法")

    # 去重并限制数量
    return list(set(keywords))[:10]


def parse_judgment_file(filepath: Path) -> list[dict]:
    """解析单个裁判文书文件"""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        logger.error(f"读取文件失败 {filepath}: {e}")
        return []

    # 按"中华人民共和国最高人民法院"或"民事判决书"分割多个案件
    cases_raw = re.split(r"(中华人民共和国最高人民法院|民事判决书|刑事判决书|行政判决书)", content)

    results = []
    for i in range(1, len(cases_raw), 2):
        header = cases_raw[i]
        body = cases_raw[i + 1] if i + 1 < len(cases_raw) else ""
        full_text = header + body

        if len(full_text.strip()) < 200:
            continue

        case = {
            "case_number": extract_case_number(full_text),
            "court_name": extract_court_name(full_text),
            "court_level": "",
            "case_type": extract_case_type(full_text),
            "cause_of_action": extract_cause_of_action(full_text),
            "judgment_date": extract_judgment_date(full_text),
            "plaintiff_claim": "",
            "defendant_defense": "",
            "facts_summary": extract_facts(full_text),
            "judgment_reasoning": extract_reasoning(full_text),
            "judgment_result": extract_result(full_text),
            "applicable_laws": extract_applicable_laws(full_text),
            "keywords": [],
            "source_file": filepath.name,
            "raw_content": full_text[:5000],
        }

        # 补充法院层级
        case["court_level"] = extract_court_level(case["court_name"])

        # 提取当事人
        plaintiff, defendant = extract_parties(full_text)
        case["plaintiff_claim"] = plaintiff
        case["defendant_defense"] = defendant

        # 生成案件名称
        case["case_name"] = _generate_case_name(case)

        # 生成关键词
        case["keywords"] = generate_keywords(case)

        results.append(case)

    return results


def _generate_case_name(case: dict) -> str:
    """生成案件名称"""
    plaintiff = case.get("plaintiff_claim", "")
    defendant = case.get("defendant_defense", "")
    cause = case.get("cause_of_action", "")

    # 提取公司/个人名称
    plaintiff_name = _extract_party_name(plaintiff)
    defendant_name = _extract_party_name(defendant)

    if plaintiff_name and defendant_name:
        return f"{plaintiff_name}诉{defendant_name}{cause}案"
    elif plaintiff_name:
        return f"{plaintiff_name}{cause}案"
    else:
        return f"{cause}案" if cause else "未知案件"


def _extract_party_name(party: str) -> str:
    """从当事人信息中提取名称"""
    if not party:
        return ""
    # 提取公司名称
    match = re.search(r"([^\s]+?有限公司|[^\s]+?公司|[^\s]+?集团)", party)
    if match:
        return match.group(1)[:50]
    # 提取个人名称
    match = re.search(r"(原告|被告|上诉人|被上诉人)\s*[：:]\s*([^\s]+)", party)
    if match:
        return match.group(2)[:20]
    return party[:30]


# ============================================================
# 主流程
# ============================================================


def main(input_dir: str = "../data/judge", output_dir: str = "../data/judge/cleaned"):
    """主数据清洗流程"""
    logger.info("=" * 60)
    logger.info("裁判文书数据清洗开始")
    logger.info("输入目录: %s", input_dir)
    logger.info("输出目录: %s", output_dir)
    logger.info("=" * 60)

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 获取所有 txt 文件
    txt_files = list(input_path.glob("*.txt"))
    logger.info(f"发现 {len(txt_files)} 个文本文件")

    all_cases = []
    for txt_file in txt_files:
        logger.info(f"解析文件: {txt_file.name}")
        cases = parse_judgment_file(txt_file)
        all_cases.extend(cases)
        logger.info(f"  → 提取出 {len(cases)} 个案件")

    logger.info(f"总计提取: {len(all_cases)} 个案件")

    # 保存为 JSON 格式
    output_file = output_path / "judge_cases_cleaned.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_cases, f, ensure_ascii=False, indent=2)
    logger.info(f"清洗后数据已保存到: {output_file}")

    # 统计信息
    case_type_counts = {}
    court_level_counts = {}
    for case in all_cases:
        case_type_counts[case["case_type"]] = case_type_counts.get(case["case_type"], 0) + 1
        court_level_counts[case["court_level"]] = court_level_counts.get(case["court_level"], 0) + 1

    logger.info("\n案件类型统计:")
    for case_type, count in sorted(case_type_counts.items(), key=lambda x: -x[1]):
        logger.info(f"  {case_type}: {count}")

    logger.info("\n法院层级统计:")
    for level, count in sorted(court_level_counts.items(), key=lambda x: -x[1]):
        logger.info(f"  {level}: {count}")

    # 显示一个示例
    if all_cases:
        logger.info("\n示例案件:")
        sample = all_cases[0]
        logger.info(f"  案号: {sample['case_number']}")
        logger.info(f"  案件名称: {sample['case_name']}")
        logger.info(f"  法院: {sample['court_name']}")
        logger.info(f"  案件类型: {sample['case_type']}")
        logger.info(f"  案由: {sample['cause_of_action']}")
        logger.info(f"  判决日期: {sample['judgment_date']}")
        logger.info(f"  关键词: {', '.join(sample['keywords'])}")
        logger.info(f"  事实摘要: {sample['facts_summary'][:100]}...")
        logger.info(f"  判决理由: {sample['judgment_reasoning'][:100]}...")

    logger.info("=" * 60)
    logger.info("数据清洗完成!")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清洗裁判文书数据")
    parser.add_argument("--input-dir", default="../data/judge", help="输入目录")
    parser.add_argument("--output-dir", default="../data/judge/cleaned", help="输出目录")
    args = parser.parse_args()

    main(input_dir=args.input_dir, output_dir=args.output_dir)
