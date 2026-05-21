import json
import logging
import re
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

CONTRACT_REVIEW_SYSTEM_PROMPT = """你是一位资深合同审查律师，专注于中文商业合同的审查与起草。你的工作遵循"三层四步"审查框架，融合了 contract-copilot 和 Clause-Ease-AI 的最佳实践。

## 核心理念
1. **促进交易**：审查目标是帮助交易安全落地，不是机械否定交易
2. **全面思考**：同时考虑我方、对方、履行人员与第三方影响；同时考虑法律后果、商业后果、执行成本
3. **理性决策**：按风险等级和业务影响给建议；高风险给明确方案，中低风险给可选方案
4. **条款可读**：识别模糊、歧义、过于复杂的表述，提出简化建议

## 三层分析框架
1. **宏观层（交易结构）**：合同类型是否匹配交易实质；主体是否适格；标的是否合法可履行；关键程序是否完备
2. **中观层（文本与形式）**：合同形式是否匹配业务阶段；格式条款是否合规；主合同与附件是否一致；条款可读性与清晰度
3. **微观层（条款与语言）**：核心条款是否齐全；权利义务是否清晰对等可执行；违约解除赔偿机制是否闭环；模糊条款与漏洞识别

## 风险等级
- **P0（严重）**：可能影响合同效力、导致重大损失或重大争议，签署前必须处理
- **P1（重要）**：会显著增加争议和履约成本，建议优先谈判修改
- **P2（建议）**：表述或流程优化项，可结合时间窗口处理

## 12 类合同覆盖
买卖合同、租赁合同、服务类合同、知识产权类合同、担保类合同、借贷与赠与合同、
互联网协议、婚姻家事类合同、劳动用工类合同、房地产类合同、建设工程类合同、公司投资类合同

## 条款漏洞识别要点（融合 LLM-Powered-Contract-Analysis 方法论）
- 模糊条款：含"合理"、"适当"、"及时"等不确定表述
- 缺失惩罚：违约条款缺少具体惩罚措施
- 合规风险：违反法律法规强制性规定
- 不对等条款：权利义务明显不对等
- 循环引用：条款间相互引用但无实质内容
- 不可执行条款：无法实际履行或验证的承诺

## 输出格式
审查结论包含：
1. 能否签：可签 / 有条件可签 / 不建议签
2. 先决事项：签署前必须完成的前置动作
3. 谈判优先级：P0 → P1 → P2
4. 每个风险点包含：风险名称、风险等级、风险后果、判别标准、推荐措辞、法律依据、整改建议、相关条款

引用法律时标注全称和条号（如《中华人民共和国民法典》第XXX条）。"""


class ContractReviewSkill:
    """合同审查技能 — 融合 contract-copilot 三层四步框架 + Clause-Ease-AI 条款分析 + LLM-Powered-Contract-Analysis 漏洞检测"""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.system_prompt = CONTRACT_REVIEW_SYSTEM_PROMPT

    @staticmethod
    def extract_clauses(contract_text: str) -> list[dict]:
        """基于规则的条款提取（Clause-Ease-AI 方法的简化版，无需外部NLP模型）"""
        clauses = []
        patterns = [
            r'第[一二三四五六七八九十百千\d]+条[：:\s]',
            r'第\d+[条款项][：:\s]',
            r'[一二三四五六七八九十]+[、.]\s',
            r'\d+[、.]\s',
            r'（[一二三四五六七八九十\d]+）',
            r'\([一二三四五六七八九十\d]+\)',
        ]
        combined = '|'.join(f'({p})' for p in patterns)
        matches = list(re.finditer(combined, contract_text))

        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(contract_text)
            clause_text = contract_text[start:end].strip()
            if len(clause_text) > 10:
                clauses.append({
                    "index": i + 1,
                    "title": match.group(0).strip(),
                    "content": clause_text[:500],
                    "start_pos": start,
                })

        if not clauses:
            sentences = re.split(r'[。！？\n]', contract_text)
            chunk_size = max(1, len(sentences) // 5)
            for i in range(0, len(sentences), chunk_size):
                chunk = ''.join(sentences[i:i + chunk_size]).strip()
                if chunk:
                    clauses.append({
                        "index": len(clauses) + 1,
                        "title": f"段落{len(clauses) + 1}",
                        "content": chunk[:500],
                        "start_pos": 0,
                    })

        return clauses

    @staticmethod
    def analyze_readability(contract_text: str) -> dict:
        """可读性分析（Clause-Ease-AI 方法的简化版）"""
        sentences = re.split(r'[。！？]', contract_text)
        sentences = [s.strip() for s in sentences if s.strip()]
        avg_len = sum(len(s) for s in sentences) / max(len(sentences), 1)

        long_sentences = [s for s in sentences if len(s) > 100]
        vague_words = re.findall(r'合理|适当|及时|尽快|相关|必要|妥善|重大|严重', contract_text)

        return {
            "total_sentences": len(sentences),
            "avg_sentence_length": round(avg_len, 1),
            "long_sentences_count": len(long_sentences),
            "vague_expressions": vague_words[:20],
            "vague_count": len(vague_words),
            "readability_score": max(0, min(100, 100 - len(long_sentences) * 5 - len(vague_words) * 3)),
        }

    async def extract_and_classify(self, contract_text: str) -> dict:
        """条款提取 + 合同分类（融合 Clause-Ease-AI 提取方法）"""
        clauses = self.extract_clauses(contract_text)
        readability = self.analyze_readability(contract_text)

        clauses_summary = "\n".join(
            f"- {c['title']}: {c['content'][:100]}..." if len(c['content']) > 100 else f"- {c['title']}: {c['content']}"
            for c in clauses[:20]
        )

        prompt = f"""请分析以下合同，完成条款提取验证和合同类型识别。

已自动提取 {len(clauses)} 个条款，可读性评分 {readability['readability_score']}/100。

提取的条款概要：
{clauses_summary}

可读性分析：
- 平均句长：{readability['avg_sentence_length']} 字
- 长句数量（>100字）：{readability['long_sentences_count']}
- 模糊表述数量：{readability['vague_count']}
- 模糊表述示例：{', '.join(readability['vague_expressions'][:5])}

合同文本：
{contract_text[:8000]}

请输出 JSON 格式：
{{
    "contract_type": "合同类型（从12类中选择）",
    "contract_subtype": "具体子类型",
    "parties": ["甲方（全称+角色）", "乙方（全称+角色）"],
    "transaction_essence": "交易实质描述（一句话）",
    "clause_count": 提取到的条款总数,
    "key_clauses": ["关键条款名称列表"],
    "macro_issues": [
        {{"issue": "宏观层问题", "severity": "P0/P1/P2", "detail": "详细说明"}}
    ],
    "missing_elements": ["缺失的关键要素"],
    "readability_warnings": ["可读性问题列表"]
}}"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        result = self._parse_json(response.content)
        result["auto_clauses"] = clauses
        result["readability"] = readability
        return result

    async def classify_contract(self, contract_text: str) -> dict:
        """第一步：识别合同类型和交易结构"""
        return await self.extract_and_classify(contract_text)

    async def scan_risks(
        self,
        contract_text: str,
        user_position: str = "乙方",
        review_stance: str = "常规",
        classification: Optional[dict] = None,
    ) -> dict:
        """第二步：分层扫描风险（中观+微观层），融合漏洞检测方法"""
        clauses_info = ""
        if classification and classification.get("auto_clauses"):
            clauses = classification["auto_clauses"]
            clauses_info = f"\n已提取 {len(clauses)} 个条款，请逐条审查。\n"
            for c in clauses[:15]:
                clauses_info += f"\n【{c['title']}】{c['content'][:200]}\n"

        readability_info = ""
        if classification and classification.get("readability"):
            r = classification["readability"]
            readability_info = f"""
可读性分析：
- 评分：{r['readability_score']}/100
- 模糊表述：{r['vague_count']} 处（{', '.join(r['vague_expressions'][:5])}）
- 长句：{r['long_sentences_count']} 处
"""

        prompt = f"""请对以下合同进行中观层和微观层风险扫描，特别关注条款漏洞和模糊表述。

审查立场：{user_position}（代表{user_position}方利益）
审查口径：{review_stance}（克制/常规/强势）
{clauses_info}{readability_info}
合同文本：
{contract_text[:12000]}

请按以下结构输出 JSON，每个风险点包含完整字段：
{{
    "meso_issues": [
        {{
            "risk_name": "风险名称",
            "risk_level": "P0/P1/P2",
            "risk_consequence": "风险后果",
            "criteria": "判别标准",
            "recommended_wording": "推荐措辞",
            "legal_basis": "法律依据（含具体法条）",
            "fix_suggestion": "整改建议",
            "related_clauses": "相关条款位置"
        }}
    ],
    "micro_issues": [上述同样结构],
    "loopholes": [
        {{
            "type": "模糊条款/缺失惩罚/合规风险/不对等条款/不可执行",
            "description": "漏洞描述",
            "risk_level": "P0/P1/P2",
            "fix_suggestion": "修复建议"
        }}
    ],
    "missing_clauses": ["缺失的关键条款"],
    "inconsistencies": ["内部矛盾/不一致之处"],
    "vague_expressions": ["需要明确的模糊表述及建议修改"]
}}"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_json(response.content)

    async def generate_report(
        self,
        contract_text: str,
        classification: dict,
        risks: dict,
        user_position: str = "乙方",
        review_stance: str = "常规",
    ) -> str:
        """第三步：生成正式审查意见书"""
        readability_section = ""
        if classification.get("readability"):
            r = classification["readability"]
            readability_section = f"""
## 可读性分析
- 可读性评分：{r['readability_score']}/100
- 平均句长：{r['avg_sentence_length']} 字
- 长句数量：{r['long_sentences_count']} 处
- 模糊表述：{r['vague_count']} 处
"""

        loopholes_section = ""
        if risks.get("loopholes"):
            loopholes_section = f"""
## 条款漏洞检测
{json.dumps(risks.get('loopholes', []), ensure_ascii=False, indent=2)}
"""

        prompt = f"""请基于以下分析结果，生成一份正式的合同审查意见书。

## 合同概况
- 合同类型：{classification.get('contract_type', '未识别')}
- 审查立场：{user_position}
- 审查口径：{review_stance}
- 条款数量：{classification.get('clause_count', '未知')}
{readability_section}
## 宏观层问题
{json.dumps(classification.get('macro_issues', []), ensure_ascii=False, indent=2)}

## 中观层风险
{json.dumps(risks.get('meso_issues', []), ensure_ascii=False, indent=2)}

## 微观层风险
{json.dumps(risks.get('micro_issues', []), ensure_ascii=False, indent=2)}
{loopholes_section}
## 缺失条款
{json.dumps(risks.get('missing_clauses', []), ensure_ascii=False, indent=2)}

## 内部矛盾
{json.dumps(risks.get('inconsistencies', []), ensure_ascii=False, indent=2)}

## 模糊表述
{json.dumps(risks.get('vague_expressions', []), ensure_ascii=False, indent=2)}

请按以下结构生成审查意见书：

---
# 合同审查意见书

**合同名称**：[从合同文本提取]
**审查立场**：{user_position}
**审查口径**：{review_stance}
**审查日期**：[当前日期]

## 一、合同概况
（简要描述合同基本情况和交易结构）

## 二、综合审查意见
（能否签的结论 + 总体评价）

## 三、重要风险提示
（P0 级风险汇总，按优先级排列）

## 四、详细审查意见
### 4.1 交易结构层面（宏观层）
（逐项分析宏观层问题）

### 4.2 合同形式层面（中观层）
（逐项分析中观层问题）

### 4.3 条款内容层面（微观层）
（逐项分析微观层问题）

### 4.4 条款漏洞检测
（模糊条款、缺失惩罚、合规风险、不对等条款等）

## 五、缺失条款与补充建议
（列出缺失条款及推荐措辞）

## 六、谈判优先级建议
| 优先级 | 问题 | 建议方案 | 谈判弹性 |
|--------|------|----------|----------|

## 七、声明
本审查意见仅供委托方内部参考，不构成正式法律意见书。重大交易建议由执业律师最终审定。
---

请确保引用《中华人民共和国民法典》等具体法条，语言专业、准确、可执行。"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def draft_clause(
        self,
        clause_type: str,
        context: str,
        user_position: str = "乙方",
    ) -> str:
        """起草/补充特定合同条款"""
        prompt = f"""请为以下场景起草合同条款。

条款类型：{clause_type}
立场：{user_position}
背景信息：{context}

请输出：
1. 推荐条款全文（可直接使用）
2. 备选方案（如有）
3. 使用说明（适用场景、注意事项）
4. 法律依据"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def full_review(
        self,
        contract_text: str,
        user_position: str = "乙方",
        review_stance: str = "常规",
    ) -> dict:
        """完整审查流程：提取分类 → 风险扫描 → 报告生成"""
        logger.info("开始合同审查: position=%s, stance=%s", user_position, review_stance)

        classification = await self.extract_and_classify(contract_text)
        logger.info("合同分类完成: %s", classification.get("contract_type", "未知"))

        risks = await self.scan_risks(contract_text, user_position, review_stance, classification)
        p0_count = len([r for r in risks.get("meso_issues", []) + risks.get("micro_issues", []) + risks.get("loopholes", []) if r.get("risk_level") == "P0"])
        p1_count = len([r for r in risks.get("meso_issues", []) + risks.get("micro_issues", []) + risks.get("loopholes", []) if r.get("risk_level") == "P1"])
        logger.info("风险扫描完成: P0=%d, P1=%d", p0_count, p1_count)

        report = await self.generate_report(contract_text, classification, risks, user_position, review_stance)

        return {
            "classification": classification,
            "risks": risks,
            "report": report,
            "summary": {
                "contract_type": classification.get("contract_type", "未识别"),
                "can_sign": self._extract_can_sign(report),
                "p0_count": p0_count,
                "p1_count": p1_count,
                "total_risks": p0_count + p1_count + len([
                    r for r in risks.get("meso_issues", []) + risks.get("micro_issues", [])
                    if r.get("risk_level") == "P2"
                ]),
                "clause_count": classification.get("clause_count", 0),
                "readability_score": classification.get("readability", {}).get("readability_score", 0),
            },
        }

    def _parse_json(self, content: str) -> dict:
        """从 LLM 响应中解析 JSON"""
        try:
            if "```json" in content:
                start = content.index("```json") + 7
                end = content.index("```", start)
                content = content[start:end]
            elif "```" in content:
                start = content.index("```") + 3
                end = content.index("```", start)
                content = content[start:end]
            return json.loads(content)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("JSON 解析失败: %s，原始输出前200字: %s", e, content[:200])
            return {}

    def _extract_can_sign(self, report: str) -> str:
        """从报告中提取能否签的结论"""
        if "不建议签" in report:
            return "不建议签"
        if "有条件可签" in report:
            return "有条件可签"
        if "可签" in report:
            return "可签"
        return "待评估"
