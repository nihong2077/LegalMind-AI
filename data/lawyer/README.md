# 律师数据库 — 数据上传说明

## 数据库信息

| 项目 | 值 |
|------|-----|
| PostgreSQL 数据库 | `lawyer_db` |
| Qdrant Collection | `lawyer_knowledge` |
| 向量维度 | 768 (ChatLaw-Text2Vec) |

## 数据表结构

### 1. defense_strategies — 辩护策略

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| strategy_name | VARCHAR(256) | ✅ | 策略名称 |
| case_type | VARCHAR(128) | | 适用案件类型 |
| applicable_scenario | TEXT | | 适用场景描述 |
| argument_template | TEXT | | 论证模板（核心字段） |
| evidence_requirements | TEXT | | 证据要求 |
| success_rate | VARCHAR(32) | | 成功率评估 |
| reference_cases | TEXT | | 参考案例 |

### 2. evidence_rules — 证据规则

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| rule_name | VARCHAR(256) | ✅ | 规则名称 |
| evidence_type | VARCHAR(128) | | 证据类型 |
| admissibility_criteria | TEXT | | 可采性标准（核心字段） |
| burden_of_proof | TEXT | | 举证责任 |
| exclusion_rules | TEXT | | 排除规则 |
| legal_basis | TEXT | | 法律依据 |

### 3. contract_review_templates — 合同审查模板

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| contract_type | VARCHAR(128) | ✅ | 合同类型 |
| contract_subtype | VARCHAR(128) | | 合同子类型 |
| clause_category | VARCHAR(128) | | 条款分类 |
| risk_level | VARCHAR(16) | | 风险等级：P0/P1/P2 |
| review_checkpoint | TEXT | | 审查要点（核心字段） |
| suggested_wording | TEXT | | 建议措辞 |
| legal_basis | TEXT | | 法律依据 |

### 4. legal_opinions — 代理词 / 法律意见书

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| opinion_type | VARCHAR(128) | ✅ | 文书类型：代理词/辩护词/法律意见书 |
| case_type | VARCHAR(128) | | 案件类型 |
| title | VARCHAR(512) | | 标题 |
| content | TEXT | ✅ | 正文内容（核心字段） |
| key_arguments | TEXT | | 核心论点摘要 |

## 上传数据格式

### JSON 格式（推荐）

```json
[
  {
    "table": "defense_strategies",
    "data": {
      "strategy_name": "民间借贷 — 诉讼时效抗辩",
      "case_type": "民事",
      "applicable_scenario": "借款到期后超过三年未主张权利",
      "argument_template": "根据《民法典》第一百八十八条，向人民法院请求保护民事权利的诉讼时效期间为三年...",
      "evidence_requirements": "需提供借款合同、还款记录等证明时效起算点的证据",
      "success_rate": "较高",
      "reference_cases": "(2023)最高法民申1234号"
    }
  },
  {
    "table": "contract_review_templates",
    "data": {
      "contract_type": "买卖合同",
      "clause_category": "违约责任",
      "risk_level": "P1",
      "review_checkpoint": "违约金比例是否超过实际损失的30%",
      "suggested_wording": "建议将违约金调整为不超过合同总价的20%，并明确损失计算方式",
      "legal_basis": "《民法典》第五百八十五条"
    }
  }
]
```

## 数据来源建议

- **中国裁判文书网**: 辩护词、代理词
- **司法部律师工作局**: 律师业务指引
- **全国律协**: 律师业务操作指引
- **合同审查实务**: 各类合同审查清单和模板
- **证据法学教材**: 证据规则体系
