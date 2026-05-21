# 法官数据库 — 数据上传说明

## 数据库信息

| 项目 | 值 |
|------|-----|
| PostgreSQL 数据库 | `judge_db` |
| Qdrant Collection | `judge_knowledge` |
| 向量维度 | 768 (ChatLaw-Text2Vec) |

## 数据表结构

### 1. judge_cases — 裁判文书 / 判例

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| case_number | VARCHAR(128) | ✅ | 案号，如 (2024)京0105民初12345号 |
| case_name | VARCHAR(512) | ✅ | 案件名称 |
| court_level | VARCHAR(64) | | 法院层级：基层/中级/高级/最高 |
| court_name | VARCHAR(256) | | 法院名称 |
| case_type | VARCHAR(64) | | 案件类型：民事/刑事/行政 |
| cause_of_action | VARCHAR(256) | | 案由 |
| judgment_date | DATE | | 判决日期 |
| plaintiff_claim | TEXT | | 原告诉讼请求 |
| defendant_defense | TEXT | | 被告答辩意见 |
| facts_summary | TEXT | | 事实摘要 |
| judgment_reasoning | TEXT | | 判决理由（核心字段） |
| judgment_result | TEXT | | 判决结果 |
| applicable_laws | TEXT | | 适用法律条文 |
| keywords | TEXT[] | | 关键词标签 |

### 2. sentencing_guidelines — 量刑标准

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| crime_category | VARCHAR(256) | ✅ | 罪名分类 |
| crime_subcategory | VARCHAR(256) | | 罪名子类 |
| sentencing_range | VARCHAR(128) | | 量刑范围 |
| aggravating_factors | TEXT | | 加重情节 |
| mitigating_factors | TEXT | | 减轻情节 |
| typical_penalty | TEXT | | 典型刑罚 |
| legal_basis | TEXT | | 法律依据 |
| source_document | VARCHAR(512) | | 来源文件 |

### 3. trial_procedures — 审判流程

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| procedure_type | VARCHAR(128) | ✅ | 程序类型 |
| procedure_name | VARCHAR(256) | ✅ | 程序名称 |
| stage | VARCHAR(64) | | 阶段 |
| description | TEXT | | 描述 |
| time_limit | VARCHAR(128) | | 时限 |
| legal_basis | TEXT | | 法律依据 |

## 上传数据格式

### JSON 格式（推荐）

将数据保存为 `.json` 文件放入本目录，格式如下：

```json
[
  {
    "table": "judge_cases",
    "data": {
      "case_number": "(2024)京0105民初12345号",
      "case_name": "张三诉李四借款合同纠纷案",
      "court_level": "基层",
      "court_name": "北京市朝阳区人民法院",
      "case_type": "民事",
      "cause_of_action": "借款合同纠纷",
      "judgment_date": "2024-03-15",
      "plaintiff_claim": "请求判令被告返还借款本金10万元及利息",
      "defendant_defense": "承认借款事实，但主张已部分还款",
      "facts_summary": "2023年1月，原告向被告出借10万元...",
      "judgment_reasoning": "本院认为，合法的借贷关系受法律保护...",
      "judgment_result": "被告于判决生效之日起十日内返还原告借款本金10万元",
      "applicable_laws": "《民法典》第六百六十七条、第六百七十五条",
      "keywords": ["借款合同", "民间借贷", "利息"]
    }
  }
]
```

### CSV 格式

也可使用 CSV 文件，第一行为列名，与上表字段一一对应。

## 数据来源建议

- **裁判文书网**: https://wenshu.court.gov.cn
- **中国司法案例网**: https://anli.court.gov.cn
- **最高人民法院公报案例**
- **指导性案例** (最高人民法院发布)
