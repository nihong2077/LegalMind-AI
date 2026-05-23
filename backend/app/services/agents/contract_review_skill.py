"""
合同审查技能 — 融合 GitHub 开源项目最佳实践

参考项目:
- ContractIQ: Playbook 规则体系、5级双维度风险评级、Redline 修订
- Ally Legal (Azure): 条款交叉引用检测、Guardrails 输出校验
- Legal_Assistant (RAG+KG+CP): 约束解析器、合规性验证
- ContractClarity: 用户视角陷阱识别、谈判策略生成
- Lexi-Guide: 基于角色的个性化审查
"""
import json
import logging
import re
from datetime import datetime
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 1. Playbook 规则体系（参考 ContractIQ）
# ──────────────────────────────────────────────

CONTRACT_PLAYBOOKS: dict[str, dict] = {
    "买卖合同": {
        "must_have": ["标的物描述", "数量与质量", "价款与支付", "交付方式与期限", "验收标准", "风险转移", "违约责任", "争议解决"],
        "common_risks": ["质量标准模糊", "验收期限缺失", "风险转移时点不清", "付款条件与交付不对等"],
        "key_laws": ["《民法典》第五百九十五条-第六百四十七条", "《产品质量法》"],
    },
    "租赁合同": {
        "must_have": ["租赁物描述", "租赁期限", "租金及支付", "维修义务", "转租约定", "优先购买权", "违约责任"],
        "common_risks": ["维修责任不清", "押金退还条件模糊", "拆迁补偿未约定", "续租条件缺失"],
        "key_laws": ["《民法典》第七百零三条-第七百三十四条"],
    },
    "借贷与赠与合同": {
        "must_have": ["借款金额", "借款期限", "利率约定", "还款方式", "担保条款", "违约责任", "提前还款"],
        "common_risks": ["利率超LPR四倍", "担保条款不完善", "逾期利息过高", "加速到期条件苛刻"],
        "key_laws": ["《民法典》第六百六十七条-第六百八十条", "《最高人民法院关于审理民间借贷案件适用法律若干问题的规定》"],
    },
    "劳动合同": {
        "must_have": ["工作岗位", "工作地点", "合同期限", "薪资福利", "工作时间", "社会保险", "解除条件", "竞业限制"],
        "common_risks": ["试用期超法定上限", "竞业限制补偿不足", "单方调岗条款", "违约金条款违法"],
        "key_laws": ["《劳动合同法》", "《劳动法》"],
    },
    "服务类合同": {
        "must_have": ["服务内容与范围", "服务标准", "服务期限", "费用与支付", "验收标准", "知识产权", "保密条款", "违约责任"],
        "common_risks": ["服务标准不可量化", "验收条件模糊", "知识产权归属不清", "单方解约权不对等"],
        "key_laws": ["《民法典》第八百七十条-第八百八十七条"],
    },
    "担保类合同": {
        "must_have": ["担保方式", "担保范围", "担保期限", "担保物描述", "登记约定", "实现条件", "反担保"],
        "common_risks": ["担保范围过宽", "担保期限不明", "抵押登记缺失", "连带责任约定不清"],
        "key_laws": ["《民法典》第三百八十六条-第四百零二条"],
    },
    "知识产权类合同": {
        "must_have": ["权利归属", "许可范围", "许可方式", "使用限制", "侵权责任", "保密条款", "改进成果归属"],
        "common_risks": ["权利归属约定不清", "许可范围过宽/过窄", "改进成果归属不明", "侵权救济缺失"],
        "key_laws": ["《著作权法》", "《专利法》", "《商标法》"],
    },
    "互联网协议": {
        "must_have": ["服务内容", "用户数据", "隐私政策", "知识产权", "免责条款", "争议解决", "协议变更"],
        "common_risks": ["单方修改权过大", "数据使用范围过宽", "免责条款不合理", "管辖约定不利"],
        "key_laws": ["《个人信息保护法》", "《网络安全法》", "《电子商务法》"],
    },
    "婚姻家事类合同": {
        "must_have": ["财产范围", "归属约定", "债务承担", "子女抚养", "变更条件", "公证条款"],
        "common_risks": ["财产范围不完整", "隐匿财产条款缺失", "债务承担不明", "变更条件苛刻"],
        "key_laws": ["《民法典》第一千零六十二条-第一千零六十五条"],
    },
    "房地产类合同": {
        "must_have": ["房屋信息", "价格与付款", "交付条件", "产权登记", "面积差异处理", "质量保证", "违约责任"],
        "common_risks": ["交付条件模糊", "面积差异处理不公", "产权登记期限缺失", "质量保修范围不清"],
        "key_laws": ["《民法典》", "《城市房地产管理法》", "《商品房销售管理办法》"],
    },
    "建设工程类合同": {
        "must_have": ["工程范围", "工期", "质量标准", "价款与支付", "竣工验收", "保修责任", "变更签证"],
        "common_risks": ["工期延误责任不对等", "变更计价规则缺失", "付款节点不合理", "质保金比例超标"],
        "key_laws": ["《民法典》第七百八十八条-第八百零八条", "《建筑法》"],
    },
    "公司投资类合同": {
        "must_have": ["投资金额与方式", "股权/份额", "公司治理", "利润分配", "退出机制", "竞业禁止", "知情权"],
        "common_risks": ["估值调整条款苛刻", "一票否决权过宽", "退出机制不完善", "对赌条款不可执行"],
        "key_laws": ["《公司法》", "《合伙企业法》"],
    },
}

# ──────────────────────────────────────────────
# 2. 系统提示词（融合多项目精华）
# ──────────────────────────────────────────────

CONTRACT_REVIEW_SYSTEM_PROMPT = """你是一位资深合同审查律师，专注于中文商业合同的审查与起草。你的工作遵循"三层四步"审查框架，融合了 contract-copilot、Clause-Ease-AI、ContractIQ、Ally Legal 等开源项目最佳实践。

## 核心审查原则
1. **促进交易**：审查目标是帮助交易安全落地，不是机械否定交易
2. **全面思考**：同时考虑我方、对方、履行人员与第三方影响；同时考虑法律后果、商业后果、执行成本
3. **理性决策**：按风险等级和业务影响给建议；高风险给明确方案，中低风险给可选方案
4. **条款可读**：识别模糊、歧义、过于复杂的表述，提出简化建议
5. **用户视角**：站在委托方立场识别陷阱和不公平条款，提供针对性谈判策略

## 三层分析框架
1. **宏观层（交易结构）**：合同类型是否匹配交易实质；主体是否适格；标的是否合法可履行；关键程序是否完备
2. **中观层（文本与形式）**：合同形式是否匹配业务阶段；格式条款是否合规；主合同与附件是否一致；条款可读性与清晰度
3. **微观层（条款与语言）**：核心条款是否齐全；权利义务是否清晰对等可执行；违约解除赔偿机制是否闭环；模糊条款与漏洞识别

## 双维度风险评级（参考 ContractIQ 5级体系）
每个风险点需同时评估两个维度：
- **严重性(Severity)**：S1致命/S2严重/S3中等/S4轻微/S5提示
- **可能性(Likelihood)**：L1极高/L2高/L3中/L4低/L5极低
- **综合等级**：P0(致命) = S1+L1~L3 或 S2+L1; P1(严重) = S2+L2~L3 或 S3+L1~L2; P2(中等) = S3+L3~L4 或 S4+L1~L2; P3(轻微) = S4+L3~L5 或 S5+L1~L3; P4(提示) = S5+L4~L5

## 条款漏洞识别要点（融合 LLM-Powered-Contract-Analysis + Ally Legal）
- 模糊条款：含"合理"、"适当"、"及时"等不确定表述
- 缺失惩罚：违约条款缺少具体惩罚措施
- 合规风险：违反法律法规强制性规定
- 不对等条款：权利义务明显不对等
- 循环引用：条款间相互引用但无实质内容
- 不可执行条款：无法实际履行或验证的承诺
- 交叉冲突：不同条款间存在矛盾或冲突
- 隐性义务：未明确表述但法律推定的义务

## 输出格式
审查结论包含：
1. 能否签：可签 / 有条件可签 / 不建议签
2. 先决事项：签署前必须完成的前置动作
3. 谈判优先级：P0 → P1 → P2
4. 每个风险点包含：风险名称、双维度评级、风险后果、推荐措辞、法律依据、整改建议、相关条款、原文→建议文(Redline)

引用法律时标注全称和条号（如《中华人民共和国民法典》第XXX条）。"""


class ContractReviewSkill:
    """合同审查技能 — 融合多开源项目最佳实践"""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.system_prompt = CONTRACT_REVIEW_SYSTEM_PROMPT

    # ──────────────────────────────────────────
    # 条款提取（增强版，参考 Clause-Ease-AI）
    # ──────────────────────────────────────────

    @staticmethod
    def extract_clauses(contract_text: str) -> list[dict]:
        """基于规则的条款提取，支持多种中文合同编号格式"""
        clauses = []
        # 主模式：第X条、1.、（一）等
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

        # 兜底：按段落分块
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

    # ──────────────────────────────────────────
    # 可读性分析（增强版）
    # ──────────────────────────────────────────

    @staticmethod
    def analyze_readability(contract_text: str) -> dict:
        """可读性分析，识别模糊表述和长句"""
        sentences = re.split(r'[。！？]', contract_text)
        sentences = [s.strip() for s in sentences if s.strip()]
        avg_len = sum(len(s) for s in sentences) / max(len(sentences), 1)

        long_sentences = [s for s in sentences if len(s) > 100]
        # 扩展模糊词库（参考 Ally Legal）
        vague_words = re.findall(
            r'合理|适当|及时|尽快|相关|必要|妥善|重大|严重|'
            r'相应|一定|适当条件|其他情形|特殊情况|'
            r'视情况|根据实际情况|按约定|另行通知|'
            r'不可抗力因素|客观原因|合理期限|合理费用',
            contract_text,
        )

        return {
            "total_sentences": len(sentences),
            "avg_sentence_length": round(avg_len, 1),
            "long_sentences_count": len(long_sentences),
            "vague_expressions": vague_words[:30],
            "vague_count": len(vague_words),
            "readability_score": max(0, min(100, 100 - len(long_sentences) * 5 - len(vague_words) * 3)),
        }

    # ──────────────────────────────────────────
    # 交叉引用检测（参考 Ally Legal）
    # ──────────────────────────────────────────

    @staticmethod
    def detect_cross_references(clauses: list[dict]) -> list[dict]:
        """检测条款间的交叉引用和潜在冲突"""
        cross_refs = []
        ref_patterns = [
            r'第[一二三四五六七八九十百千\d]+条',
            r'见本合同第\d+[条款项]',
            r'按照.*约定',
            r'依据.*规定',
            r'另行约定',
        ]

        for clause in clauses:
            content = clause.get("content", "")
            for pattern in ref_patterns:
                refs = re.findall(pattern, content)
                for ref in refs:
                    cross_refs.append({
                        "source_clause": clause.get("title", ""),
                        "reference": ref,
                        "type": "交叉引用",
                    })

        return cross_refs

    # ──────────────────────────────────────────
    # Playbook 合规检查（参考 ContractIQ）
    # ──────────────────────────────────────────

    @staticmethod
    def check_playbook_compliance(contract_type: str, clauses: list[dict]) -> dict:
        """根据合同类型 Playbook 检查必备条款"""
        # 模糊匹配合同类型到 playbook
        matched_type = None
        for pb_type in CONTRACT_PLAYBOOKS:
            if pb_type in contract_type or contract_type in pb_type:
                matched_type = pb_type
                break
        if not matched_type:
            # 关键词匹配
            type_keywords = {
                "买卖合同": ["买卖", "购销", "采购", "销售"],
                "租赁合同": ["租赁", "出租", "承租"],
                "借贷与赠与合同": ["借款", "借贷", "贷款", "赠与"],
                "劳动合同": ["劳动", "用工", "聘用", "雇佣"],
                "服务类合同": ["服务", "咨询", "委托", "代理"],
                "担保类合同": ["担保", "保证", "抵押", "质押"],
                "知识产权类合同": ["知识产权", "许可", "转让", "专利", "商标", "著作权"],
                "互联网协议": ["互联网", "平台", "APP", "用户协议", "隐私"],
                "婚姻家事类合同": ["婚姻", "离婚", "财产约定", "抚养"],
                "房地产类合同": ["房地产", "商品房", "房屋买卖"],
                "建设工程类合同": ["建设", "工程", "施工", "承包"],
                "公司投资类合同": ["投资", "股权", "合伙", "增资"],
            }
            for pb_type, keywords in type_keywords.items():
                if any(kw in contract_type for kw in keywords):
                    matched_type = pb_type
                    break

        if not matched_type:
            return {"matched": False, "contract_type": contract_type, "missing": [], "common_risks": [], "key_laws": []}

        playbook = CONTRACT_PLAYBOOKS[matched_type]
        clause_titles = " ".join(c.get("title", "") + " " + c.get("content", "")[:100] for c in clauses)

        missing = []
        for required in playbook["must_have"]:
            # 简单关键词匹配
            keywords = required.replace("与", "").replace("及", "").replace("的", "")
            if not any(kw in clause_titles for kw in [required, keywords] if len(kw) > 1):
                missing.append(required)

        return {
            "matched": True,
            "contract_type": matched_type,
            "missing": missing,
            "common_risks": playbook["common_risks"],
            "key_laws": playbook["key_laws"],
        }

    # ──────────────────────────────────────────
    # 步骤1：条款提取 + 合同分类
    # ──────────────────────────────────────────

    async def extract_and_classify(self, contract_text: str) -> dict:
        """条款提取 + 合同分类 + Playbook 合规初检"""
        clauses = self.extract_clauses(contract_text)
        readability = self.analyze_readability(contract_text)
        cross_refs = self.detect_cross_references(clauses)

        clauses_summary = "\n".join(
            f"- {c['title']}: {c['content'][:100]}..." if len(c['content']) > 100 else f"- {c['title']}: {c['content']}"
            for c in clauses[:20]
        )

        prompt = f"""请分析以下合同，完成条款提取验证和合同类型识别。

已自动提取 {len(clauses)} 个条款，可读性评分 {readability['readability_score']}/100。
检测到 {len(cross_refs)} 处交叉引用。

提取的条款概要：
{clauses_summary}

可读性分析：
- 平均句长：{readability['avg_sentence_length']} 字
- 长句数量（>100字）：{readability['long_sentences_count']}
- 模糊表述数量：{readability['vague_count']}
- 模糊表述示例：{', '.join(readability['vague_expressions'][:8])}

合同文本：
{contract_text[:8000]}

请输出 JSON 格式：
{{
    "contract_type": "合同类型（从12类中选择：买卖合同/租赁合同/借贷与赠与合同/劳动合同/服务类合同/担保类合同/知识产权类合同/互联网协议/婚姻家事类合同/房地产类合同/建设工程类合同/公司投资类合同）",
    "contract_subtype": "具体子类型",
    "parties": ["甲方（全称+角色）", "乙方（全称+角色）"],
    "transaction_essence": "交易实质描述（一句话）",
    "clause_count": 提取到的条款总数,
    "key_clauses": ["关键条款名称列表"],
    "macro_issues": [
        {{"issue": "宏观层问题", "severity": "S1/S2/S3/S4/S5", "likelihood": "L1/L2/L3/L4/L5", "detail": "详细说明"}}
    ],
    "missing_elements": ["缺失的关键要素"],
    "readability_warnings": ["可读性问题列表"],
    "cross_reference_issues": ["交叉引用问题列表"]
}}"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        result = self._parse_json(response.content)
        result["auto_clauses"] = clauses
        result["readability"] = readability
        result["cross_references"] = cross_refs

        # Playbook 合规初检
        contract_type = result.get("contract_type", "")
        playbook_result = self.check_playbook_compliance(contract_type, clauses)
        result["playbook"] = playbook_result
        if playbook_result.get("missing"):
            existing_missing = result.get("missing_elements", [])
            for m in playbook_result["missing"]:
                if m not in existing_missing:
                    existing_missing.append(m)
            result["missing_elements"] = existing_missing

        return result

    async def classify_contract(self, contract_text: str) -> dict:
        """第一步：识别合同类型和交易结构"""
        return await self.extract_and_classify(contract_text)

    # ──────────────────────────────────────────
    # 步骤2：分层风险扫描（增强版）
    # ──────────────────────────────────────────

    async def scan_risks(
        self,
        contract_text: str,
        user_position: str = "乙方",
        review_stance: str = "常规",
        classification: Optional[dict] = None,
    ) -> dict:
        """分层扫描风险，含双维度评级、Redline 修订、合规验证"""

        # 构建条款信息
        clauses_info = ""
        if classification and classification.get("auto_clauses"):
            clauses = classification["auto_clauses"]
            clauses_info = f"\n已提取 {len(clauses)} 个条款，请逐条审查。\n"
            for c in clauses[:15]:
                clauses_info += f"\n【{c['title']}】{c['content'][:200]}\n"

        # 可读性信息
        readability_info = ""
        if classification and classification.get("readability"):
            r = classification["readability"]
            readability_info = f"""
可读性分析：
- 评分：{r['readability_score']}/100
- 模糊表述：{r['vague_count']} 处（{', '.join(r['vague_expressions'][:5])}）
- 长句：{r['long_sentences_count']} 处
"""

        # Playbook 信息（参考 ContractIQ）
        playbook_info = ""
        if classification and classification.get("playbook"):
            pb = classification["playbook"]
            if pb.get("matched"):
                playbook_info = f"""
合同类型 Playbook：{pb['contract_type']}
常见风险：{', '.join(pb.get('common_risks', []))}
关键法律：{', '.join(pb.get('key_laws', []))}
Playbook 缺失条款：{', '.join(pb.get('missing', []))}
"""

        # 交叉引用信息
        cross_ref_info = ""
        if classification and classification.get("cross_references"):
            refs = classification["cross_references"]
            if refs:
                cross_ref_info = f"\n检测到 {len(refs)} 处交叉引用，请检查是否存在冲突或循环引用。\n"

        prompt = f"""请对以下合同进行全面风险扫描，使用双维度评级体系，并为每个风险提供 Redline 修订建议。

审查立场：{user_position}（代表{user_position}方利益）
审查口径：{review_stance}（克制=尽量促成交易/常规=平衡保护/强势=最大化保护我方）
{clauses_info}{readability_info}{playbook_info}{cross_ref_info}
合同文本：
{contract_text[:12000]}

请按以下结构输出 JSON：
{{
    "meso_issues": [
        {{
            "risk_name": "风险名称",
            "severity": "S1/S2/S3/S4/S5",
            "likelihood": "L1/L2/L3/L4/L5",
            "risk_level": "P0/P1/P2/P3/P4",
            "risk_consequence": "风险后果（法律后果+商业后果）",
            "criteria": "判别标准",
            "recommended_wording": "推荐措辞",
            "legal_basis": "法律依据（含具体法条全称和条号）",
            "fix_suggestion": "整改建议",
            "related_clauses": "相关条款位置",
            "original_text": "原文关键表述（摘录）",
            "suggested_text": "建议修改后的文本（Redline）",
            "negotiation_strategy": "谈判策略（如何与对方沟通此问题）"
        }}
    ],
    "micro_issues": [上述同样结构],
    "loopholes": [
        {{
            "type": "模糊条款/缺失惩罚/合规风险/不对等条款/不可执行/交叉冲突/隐性义务",
            "description": "漏洞描述",
            "severity": "S1-S5",
            "likelihood": "L1-L5",
            "risk_level": "P0-P4",
            "fix_suggestion": "修复建议",
            "original_text": "原文",
            "suggested_text": "建议文本"
        }}
    ],
    "missing_clauses": ["缺失的关键条款"],
    "inconsistencies": ["内部矛盾/不一致之处"],
    "vague_expressions": ["需要明确的模糊表述及建议修改"],
    "compliance_issues": [
        {{
            "regulation": "法规名称",
            "article": "具体条号",
            "issue": "合规问题描述",
            "risk_level": "P0-P4",
            "fix_suggestion": "合规建议"
        }}
    ],
    "unfair_terms": [
        {{
            "clause": "条款位置",
            "issue": "不公平之处",
            "affected_party": "受影响方",
            "risk_level": "P0-P4",
            "fix_suggestion": "公平化建议"
        }}
    ]
}}"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        result = self._parse_json(response.content)

        # Guardrails：校验输出完整性（参考 Ally Legal）
        result = self._validate_scan_output(result)
        return result

    # ──────────────────────────────────────────
    # 步骤3：生成审查意见书
    # ──────────────────────────────────────────

    async def generate_report(
        self,
        contract_text: str,
        classification: dict,
        risks: dict,
        user_position: str = "乙方",
        review_stance: str = "常规",
    ) -> str:
        """生成正式审查意见书，含 Redline 修订对比和谈判策略"""
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

        compliance_section = ""
        if risks.get("compliance_issues"):
            compliance_section = f"""
## 合规性问题
{json.dumps(risks.get('compliance_issues', []), ensure_ascii=False, indent=2)}
"""

        unfair_section = ""
        if risks.get("unfair_terms"):
            unfair_section = f"""
## 不公平条款
{json.dumps(risks.get('unfair_terms', []), ensure_ascii=False, indent=2)}
"""

        playbook_section = ""
        if classification.get("playbook", {}).get("matched"):
            pb = classification["playbook"]
            playbook_section = f"""
## Playbook 合规检查
- 合同类型：{pb['contract_type']}
- 缺失必备条款：{', '.join(pb.get('missing', []))}
- 常见风险提示：{', '.join(pb.get('common_risks', []))}
"""

        prompt = f"""请基于以下分析结果，生成一份正式的合同审查意见书。

## 合同概况
- 合同类型：{classification.get('contract_type', '未识别')}
- 审查立场：{user_position}
- 审查口径：{review_stance}
- 条款数量：{classification.get('clause_count', '未知')}
{readability_section}{playbook_section}
## 宏观层问题
{json.dumps(classification.get('macro_issues', []), ensure_ascii=False, indent=2)}

## 中观层风险
{json.dumps(risks.get('meso_issues', []), ensure_ascii=False, indent=2)}

## 微观层风险
{json.dumps(risks.get('micro_issues', []), ensure_ascii=False, indent=2)}
{loopholes_section}{compliance_section}{unfair_section}
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
**审查日期**：{datetime.now().strftime('%Y年%m月%d日')}

## 一、合同概况
（简要描述合同基本情况和交易结构）

## 二、综合审查意见
（能否签的结论 + 总体评价 + 置信度说明）

## 三、重要风险提示
（P0 级风险汇总，按优先级排列，含双维度评级）

## 四、详细审查意见
### 4.1 交易结构层面（宏观层）
（逐项分析宏观层问题）

### 4.2 合同形式层面（中观层）
（逐项分析中观层问题）

### 4.3 条款内容层面（微观层）
（逐项分析微观层问题）

### 4.4 条款漏洞检测
（模糊条款、缺失惩罚、合规风险、不对等条款、交叉冲突等）

### 4.5 合规性审查
（法律法规合规性检查结果）

### 4.6 不公平条款识别
（从用户视角识别的陷阱和不公平条款）

## 五、Redline 修订建议
（逐条列出原文→建议文对比，标注修订理由）

## 六、缺失条款与补充建议
（列出缺失条款及推荐措辞）

## 七、谈判策略
| 优先级 | 问题 | 建议方案 | 谈判弹性 | 备选方案 |
|--------|------|----------|----------|----------|

## 八、声明
本审查意见仅供委托方内部参考，不构成正式法律意见书。重大交易建议由执业律师最终审定。
---

请确保引用《中华人民共和国民法典》等具体法条，语言专业、准确、可执行。每个风险点需包含双维度评级。"""

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    # ──────────────────────────────────────────
    # 条款起草
    # ──────────────────────────────────────────

    async def draft_clause(
        self,
        clause_type: str,
        context: str,
        user_position: str = "乙方",
    ) -> str:
        """起草/补充特定合同条款"""
        # 查找 Playbook 中的相关法律
        relevant_laws = ""
        for pb_type, pb_data in CONTRACT_PLAYBOOKS.items():
            if clause_type in pb_type or any(kw in clause_type for kw in pb_type):
                relevant_laws = f"\n相关法律：{', '.join(pb_data.get('key_laws', []))}"
                break

        prompt = f"""请为以下场景起草合同条款。

条款类型：{clause_type}
立场：{user_position}
背景信息：{context}{relevant_laws}

请输出：
1. 推荐条款全文（可直接使用）
2. 备选方案（如有）
3. 使用说明（适用场景、注意事项）
4. 法律依据（含具体法条）"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    # ──────────────────────────────────────────
    # 完整审查流程
    # ──────────────────────────────────────────

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
        all_issues = risks.get("meso_issues", []) + risks.get("micro_issues", []) + risks.get("loopholes", [])
        p0_count = len([r for r in all_issues if r.get("risk_level") == "P0"])
        p1_count = len([r for r in all_issues if r.get("risk_level") == "P1"])
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
                    r for r in all_issues if r.get("risk_level") == "P2"
                ]),
                "clause_count": classification.get("clause_count", 0),
                "readability_score": classification.get("readability", {}).get("readability_score", 0),
            },
        }

    # ──────────────────────────────────────────
    # Guardrails 输出校验（参考 Ally Legal）
    # ──────────────────────────────────────────

    @staticmethod
    def _validate_scan_output(result: dict) -> dict:
        """校验风险扫描输出的完整性和一致性"""
        defaults = {
            "meso_issues": [],
            "micro_issues": [],
            "loopholes": [],
            "missing_clauses": [],
            "inconsistencies": [],
            "vague_expressions": [],
            "compliance_issues": [],
            "unfair_terms": [],
        }
        for key, default in defaults.items():
            if key not in result or not isinstance(result[key], list):
                result[key] = default

        # 校验每个风险点的 risk_level 一致性
        for issue_list_key in ["meso_issues", "micro_issues", "loopholes"]:
            for issue in result.get(issue_list_key, []):
                if "risk_level" not in issue:
                    # 从 severity + likelihood 推算
                    sev = issue.get("severity", "S3")
                    lik = issue.get("likelihood", "L3")
                    issue["risk_level"] = ContractReviewSkill._compute_risk_level(sev, lik)

        return result

    @staticmethod
    def _compute_risk_level(severity: str, likelihood: str) -> str:
        """根据严重性和可能性计算综合风险等级"""
        sev_map = {"S1": 1, "S2": 2, "S3": 3, "S4": 4, "S5": 5}
        lik_map = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}
        s = sev_map.get(severity, 3)
        l = lik_map.get(likelihood, 3)
        score = s * 2 + l  # 严重性权重更高
        if score <= 3:
            return "P4"
        elif score <= 5:
            return "P3"
        elif score <= 8:
            return "P2"
        elif score <= 11:
            return "P1"
        else:
            return "P0"

    # ──────────────────────────────────────────
    # 工具方法
    # ──────────────────────────────────────────

    @staticmethod
    def _parse_json(content: str) -> dict:
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

    @staticmethod
    def _extract_can_sign(report: str) -> str:
        """从报告中提取能否签的结论"""
        if "不建议签" in report:
            return "不建议签"
        if "有条件可签" in report:
            return "有条件可签"
        if "可签" in report:
            return "可签"
        return "待评估"
