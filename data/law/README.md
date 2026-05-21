# 法条数据库 — 数据上传说明

## 数据库信息

| 项目 | 值 |
|------|-----|
| PostgreSQL 数据库 | `law_db` |
| Qdrant Collection | `law_knowledge` |
| 向量维度 | 768 (ChatLaw-Text2Vec) |

## 数据表结构

### 1. legal_provisions — 法律法规（核心表）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| law_name | VARCHAR(256) | ✅ | 法律名称，如"中华人民共和国民法典" |
| law_type | VARCHAR(64) | ✅ | 法律类型：法律/行政法规/地方性法规/部门规章 |
| chapter | VARCHAR(256) | | 章 |
| section | VARCHAR(256) | | 节 |
| article_number | VARCHAR(64) | | 条文编号，如"第六百六十七条" |
| article_title | VARCHAR(512) | | 条文标题 |
| content | TEXT | ✅ | 条文内容（核心字段） |
| effective_date | DATE | | 生效日期 |
| status | VARCHAR(32) | | 状态：active/amended/repealed |
| keywords | TEXT[] | | 关键词标签 |

### 2. judicial_interpretations — 司法解释

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| interpretation_number | VARCHAR(128) | | 司法解释编号 |
| title | VARCHAR(512) | ✅ | 标题 |
| issuing_body | VARCHAR(256) | | 发布机关 |
| issue_date | DATE | | 发布日期 |
| effective_date | DATE | | 生效日期 |
| content | TEXT | ✅ | 内容（核心字段） |
| related_laws | TEXT | | 关联法律 |
| keywords | TEXT[] | | 关键词标签 |

### 3. administrative_regulations — 部门规章 / 行政法规

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| regulation_name | VARCHAR(512) | ✅ | 法规名称 |
| issuing_body | VARCHAR(256) | | 发布机关 |
| document_number | VARCHAR(128) | | 文号 |
| issue_date | DATE | | 发布日期 |
| effective_date | DATE | | 生效日期 |
| content | TEXT | ✅ | 内容（核心字段） |
| category | VARCHAR(128) | | 分类 |
| keywords | TEXT[] | | 关键词标签 |

## 上传数据格式

### JSON 格式（推荐）

```json
[
  {
    "table": "legal_provisions",
    "data": {
      "law_name": "中华人民共和国民法典",
      "law_type": "法律",
      "chapter": "第三编 合同",
      "section": "第一分编 通则",
      "article_number": "第六百六十七条",
      "article_title": "借款合同定义",
      "content": "借款合同是借款人向贷款人借款，到期返还借款并支付利息的合同。",
      "effective_date": "2021-01-01",
      "status": "active",
      "keywords": ["借款合同", "合同法", "借贷"]
    }
  },
  {
    "table": "legal_provisions",
    "data": {
      "law_name": "中华人民共和国刑法",
      "law_type": "法律",
      "chapter": "第二编 分则",
      "section": "第五章 侵犯财产罪",
      "article_number": "第二百六十四条",
      "article_title": "盗窃罪",
      "content": "盗窃公私财物，数额较大的，或者多次盗窃、入户盗窃、携带凶器盗窃、扒窃的，处三年以下有期徒刑、拘役或者管制，并处或者单处罚金...",
      "effective_date": "1997-10-01",
      "status": "active",
      "keywords": ["盗窃", "财产犯罪", "侵犯财产罪"]
    }
  }
]
```

### CSV 格式

也可使用 CSV 文件，第一行为列名，与上表字段一一对应。

## 推荐的法律法规清单

### 核心法律（必导）
- [ ] 《中华人民共和国宪法》
- [ ] 《中华人民共和国民法典》
- [ ] 《中华人民共和国刑法》
- [ ] 《中华人民共和国刑事诉讼法》
- [ ] 《中华人民共和国民事诉讼法》
- [ ] 《中华人民共和国行政诉讼法》
- [ ] 《中华人民共和国公司法》
- [ ] 《中华人民共和国劳动法》
- [ ] 《中华人民共和国劳动合同法》
- [ ] 《中华人民共和国知识产权法》系列

### 司法解释（推荐）
- [ ] 最高人民法院关于适用《民法典》的系列司法解释
- [ ] 最高人民法院关于审理民间借贷案件的司法解释
- [ ] 最高人民法院关于审理合同纠纷的司法解释
- [ ] 最高人民法院关于审理劳动争议的司法解释

## 数据来源

- **国家法律法规数据库**: https://flk.npc.gov.cn
- **司法部法律法规数据库**: http://search.chinalaw.gov.cn
- **最高人民法院**: https://www.court.gov.cn
