# LegalMind AI · Code Wiki

> 智能司法协作平台 —— 基于大语言模型（LLM）与检索增强生成（RAG）的一站式法律 AI 系统。
> 本文档基于仓库真实代码梳理，涵盖整体架构、模块职责、关键类与函数、依赖关系及运行方式。

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术栈总览](#2-技术栈总览)
3. [系统架构](#3-系统架构)
4. [目录结构](#4-目录结构)
5. [后端详解](#5-后端详解)
6. [前端详解](#6-前端详解)
7. [数据存储设计](#7-数据存储设计)
8. [依赖关系](#8-依赖关系)
9. [项目运行方式](#9-项目运行方式)
10. [关键约定与工程规范](#10-关键约定与工程规范)
11. [已知事项与规划](#11-已知事项与规划)

---

## 1. 项目概述

### 1.1 项目定位

LegalMind AI 是一个面向中文法律场景的智能协作平台，通过 **DeepSeek 云端大模型 + 法律领域本地微调模型 + 混合检索（RAG）** 的组合，提供专业的法律 AI 服务。系统同时服务普通用户（咨询/合同）与法律专业视角（模拟法庭/知识库）。

### 1.2 核心能力

| 能力模块 | 说明 | 前端入口 |
|---------|------|---------|
| **智能法律咨询** | 多轮对话，RAG 注入法律知识，SSE 流式输出 | `/chat` |
| **合同审查** | 三层四步审查框架、Playbook 合规检查、双维度风险评级（P0-P4）、Redline 修订 | `/documents` |
| **模拟法庭** | 多智能体多轮辩论（法官/原告/被告），IRAC 裁决、判决书生成、补证中断 | `/court` |
| **法律知识库** | 四级检索（HyDE→混合召回→重排序→法律过滤），按法官/律师/法条三域组织 | `/knowledge` |
| **案件管理** | 案件列表与状态跟踪 | `/cases` |
| **工作台** | 全局统计、最近案件、快速操作 | `/dashboard` |
| **图片合同 OCR** | 第三方 PaddleOCR 服务识别图片/扫描件合同 | 整合于 `/documents` |

---

## 2. 技术栈总览

### 2.1 后端

| 类别 | 技术选型 | 版本/说明 |
|------|---------|----------|
| 语言 | Python | 3.10+ |
| Web 框架 | FastAPI | ≥0.109，异步、自动 OpenAPI 文档 |
| LLM 编排 | LangChain + LangGraph | LangChain ≥0.3，LangGraph ≥0.2（状态机工作流） |
| LLM 网关 | LiteLLM Proxy | 统一模型路由、限流、缓存、Fallback |
| 缓存/消息 | Redis | 7，异步客户端 `redis.asyncio` |
| 关系数据库 | PostgreSQL + pgvector | PG 16，三库架构 + 向量列 |
| 向量数据库 | Qdrant | v1.9.0，三套 Collection |
| 嵌入模型 | Qwen3-Embedding-0.6B | 1024 维，sentence-transformers |
| 重排序模型 | Qwen3-Reranker | transformers 加载 |
| 文档解析 | PyMuPDF、python-docx | PDF/DOCX 文本提取 |
| 图像处理 | Pillow | 图片解码 |
| OCR | PaddleOCR AIStudio（第三方） | PP-OCRv6 异步任务 |
| HTTP 客户端 | httpx | 异步调用云端 API / OCR |
| 监控 | prometheus-client | 指标暴露 `/metrics` |
| 认证 | PyJWT | HS256，Bearer Token |

### 2.2 前端

| 类别 | 技术选型 | 版本/说明 |
|------|---------|----------|
| 框架 | Next.js（App Router） | 14.2+ |
| 语言 | TypeScript | 5.2+ |
| UI 库 | React | 18.2 |
| 状态管理 | Zustand | 4.4 |
| 样式 | Tailwind CSS | 3.4 |
| 动画 | Framer Motion | 12.x |
| 3D | Three.js + React Three Fiber | 首页 Hero 场景 |
| 图标 | Lucide React | — |
| 流式通信 | SSE（原生 fetch + ReadableStream） | 通用解析器 |

### 2.3 基础设施

- **容器化**：Docker Compose（7 个服务）
- **编排（规划中）**：n8n（队列模式）—— 目录已建，尚未落地
- **运行环境**：Linux / WSL2 Ubuntu

---

## 3. 系统架构

### 3.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                     浏览器（Next.js SSR/CSR）                  │
│   页面层 app/  │  组件层 components/  │  Zustand Store        │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP / SSE（Bearer JWT）
┌───────────────────────────▼─────────────────────────────────┐
│                    FastAPI 应用层（backend/app）              │
│  routers/gateway.py — 统一 API 网关（31 个端点）              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              services 业务层（LangGraph）               │  │
│  │  workflows（状态机）│ agents（技能）│ legal（检索）│ OCR │  │
│  └───────────────────────────────────────────────────────┘  │
│  core 核心层：config / security / llm_client / redis_client  │
│               pg_client / qdrant_client / embedding / reranker│
└───┬────────────┬───────────────┬───────────────┬────────────┘
    │            │               │               │
┌───▼───┐ ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────────┐
│ Redis │ │ PostgreSQL  │ │   Qdrant    │ │ 外部云端/第三方  │
│缓存/队列│ │ +pgvector   │ │  向量检索    │ │DeepSeek/PaddleOCR│
└───────┘ │  三库架构    │ │ 三Collection │ └─────────────────┘
          └─────────────┘ └─────────────┘
                          ▲
                   LiteLLM Proxy（模型网关）
                   限流 / 缓存 / Fallback
```

### 3.2 请求处理主线

以最典型的 **流式法律咨询** 为例（[gateway.py `chat_stream`](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/gateway.py#L412)）：

```
前端 chatStream()
  → POST /api/chat/stream（JWT 鉴权 + 滑动窗口限流 + 熔断器检查）
  → 阶段1：RAG 检索
      retrieve_legal_knowledge()：
        HyDE 改写 → Dense+Sparse 混合召回（Qdrant + pgvector）
        → Qwen3-Reranker 精排 → 法律规则过滤
      结果作为独立 system 消息注入（不覆盖系统提示词）
  → 阶段2：LLM 流式生成
      本地微调模型不可用时自动降级 deepseek-flash（SSE status 通知前端）
      llm_client.chat_stream() 逐 chunk 转发
  → SSE 事件：status → message(多帧) → done / error
  → 成功/失败分别记录熔断器状态，成功时累加 dashboard 统计
```

### 3.3 LLM 调用路由

[llm_client.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/llm_client.py) 的 `LLMClient` 根据模型标识三路由：

| 判断条件 | 目标 | 实际模型 |
|---------|------|---------|
| 模型标识 == `legalmind-ft` | 本地接口（Ollama/llama.cpp，`LOCAL_LLM_API_BASE`） | `LOCAL_LLM_MODEL` |
| 配置了 LiteLLM URL + Virtual Key | LiteLLM Proxy（`LITELLM_PROXY_URL`） | 透传模型名 |
| 其他（直连） | `https://api.deepseek.com/v1` | 映射表（均→`deepseek-chat`） |

模型映射表 `DEEPSEEK_MODELS`：`deepseek-v4-pro`、`deepseek-flash` 均映射到云端 `deepseek-chat`。

---

## 4. 目录结构

```
LegalMind AI/
├── backend/                        # FastAPI 后端
│   ├── app/
│   │   ├── main.py                 # 应用入口、生命周期、健康检查、监控
│   │   ├── core/                   # 核心基础设施层
│   │   │   ├── config.py           # 全局配置（Pydantic Settings，读 .env）
│   │   │   ├── security.py         # JWT 签发/校验、当前用户依赖
│   │   │   ├── user_service.py     # 用户注册/认证（Redis + PBKDF2）
│   │   │   ├── redis_client.py     # Redis 连接、任务队列（List+Hash+Stream）
│   │   │   ├── pg_client.py        # PostgreSQL 三库引擎 + ORM 模型
│   │   │   ├── qdrant_client.py    # Qdrant 客户端 + Collection
│   │   │   ├── embedding.py        # Qwen3-Embedding 嵌入服务
│   │   │   ├── reranker.py         # Qwen3-Reranker 重排序
│   │   │   └── llm_client.py       # LLM 统一客户端（三路由）
│   │   ├── routers/
│   │   │   └── gateway.py          # 统一 API 网关（31 个端点）
│   │   └── services/               # 业务层
│   │       ├── workflows/          # LangGraph 工作流（状态机）
│   │       ├── agents/             # 智能体技能封装
│   │       ├── legal/              # 法律检索核心链路
│   │       └── ocr_service.py      # PaddleOCR 服务封装
│   ├── scripts/                    # 数据导入/清洗脚本
│   ├── sql/init/                   # 数据库初始化 SQL（三库 schema）
│   ├── tests/                      # 测试
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env
├── frontend/                       # Next.js 前端
│   ├── app/                        # App Router 页面
│   │   ├── lib/api.ts              # API 封装 + SSE 解析
│   │   ├── layout.tsx / page.tsx
│   │   └── */page.tsx              # 各业务页面
│   ├── components/                 # React 组件
│   ├── store/useChatStore.ts       # Zustand 全局状态
│   ├── Dockerfile
│   ├── package.json
│   └── tailwind/next/postcss 配置
├── litellm/config.yaml             # LiteLLM Proxy 模型配置
├── orchestration/n8n/              # n8n 编排（目录为空，规划中）
├── deploy/                         # 简化部署配置
│   ├── docker-compose.yml
│   └── env.example
├── docs/                           # 文档（现有占位空文件）
├── scripts/setup_local_model.sh    # 本地模型初始化脚本
├── docker-compose.yml              # 完整编排（7 服务）
└── .env / .env.example             # 环境变量（.env 不入 git）
```

---

## 5. 后端详解

### 5.1 应用入口：[main.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/main.py)

#### 生命周期 `lifespan`

FastAPI 的 `asynccontextmanager`，按优先级初始化各组件：

| 顺序 | 组件 | 失败策略 |
|------|------|---------|
| 1 | Redis（5 次重试，指数退避） | **致命**，启动失败 |
| 2 | 默认管理员账号（`admin/admin`） | 仅告警 |
| 3 | PostgreSQL 三库（5 次重试） | **致命** |
| 4 | Qdrant | 可降级（向量检索不可用） |
| 5 | LLM 客户端 | 可降级 |
| 6 | 内存监控后台任务 | — |

关闭时逆序释放：LLM → Qdrant → PG → Redis。

#### 横切能力

| 能力 | 实现 | 说明 |
|------|------|------|
| CORS | `CORSMiddleware` | 来源由 `CORS_ORIGINS` 逗号分隔配置 |
| 指标采集中间件 | `prometheus_middleware` | 统计 `http_requests_total`、`http_request_duration_seconds` |
| 全局异常处理 | `global_exception_handler` | 按异常类型映射 HTTP 状态码（见下表） |
| 健康检查 | `GET /health` | 聚合 Redis/LLM/PG/Qdrant/内存状态 |
| 指标暴露 | `GET /metrics` | Prometheus 文本格式 |

异常 → HTTP 状态映射（`EXCEPTION_STATUS_MAP`）：

| 异常 | 状态码 |
|------|-------|
| `PermissionError` | 403 |
| `FileNotFoundError` | 404 |
| `TimeoutError` | 504 |
| `ConnectionError` | 502 |
| `ValueError` / `KeyError` / `TypeError` | 400 |
| `RuntimeError` / 其他 | 500 |

#### 内存监控

后台任务每 30s 读取 `/proc/meminfo`：
- 使用率 ≥ 80%：告警 + `gc.collect()`
- 使用率 ≥ 90%：强制 GC + `torch.cuda.empty_cache()`（释放 GPU 显存）

---

### 5.2 core 核心层

#### 5.2.1 配置：[config.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/config.py)

使用 Pydantic `BaseSettings` 从 `.env` 加载。关键配置分组：

| 分组 | 关键配置项 |
|------|-----------|
| 数据库 | `REDIS_URL`、`PG_JUDGE_URL`、`PG_LAWYER_URL`、`PG_LAW_URL`、`QDRANT_URL`/`QDRANT_PATH` |
| 嵌入/重排 | `EMBEDDING_MODEL`(1024维)、`EMBEDDING_DEVICE`、`RERANKER_MODEL`、`RERANKER_TOP_N`、检索阈值 |
| 认证 | `JWT_SECRET_KEY`、`JWT_ALGORITHM` |
| 限流/熔断 | `RATE_LIMIT_MAX_REQUESTS`、`CIRCUIT_BREAKER_*` |
| API Key | `OPENAI_API_KEY`、`DEEPSEEK_API_KEY` |
| LiteLLM | `LITELLM_PROXY_URL`、`LITELLM_VIRTUAL_KEY` |
| 本地模型 | `LOCAL_LLM_API_BASE`、`LOCAL_LLM_MODEL`、`LOCAL_LLM_API_KEY` |
| OCR | `OCR_API_URL`、`OCR_API_TOKEN`、`OCR_MODEL`、`OCR_POLL_INTERVAL`、`OCR_POLL_TIMEOUT` |

#### 5.2.2 安全认证：[security.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/security.py)

| 函数/对象 | 签名 | 职责 |
|----------|------|------|
| `create_access_token` | `(data: dict, expires_delta=None) -> str` | 签发 JWT，含 `exp`/`iat`，默认有效期 **7 天** |
| `decode_access_token` | `(token: str) -> dict` | 解码校验，过期/无效抛 401 |
| `get_current_user` | FastAPI 依赖（HTTPBearer） | 提取并校验 Token，要求含 `sub`，返回 payload |

JWT 的 `sub` 字段承载用户名（前端识别用户的依据）。

#### 5.2.3 用户服务：[user_service.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/user_service.py)

用户数据存于 **Redis Hash**，key 模式 `legalmind:user:{username}`；另维护集合 `legalmind:user_index`。

| 函数 | 职责 | 副作用/依赖 |
|------|------|-----------|
| `hash_password` | PBKDF2-HMAC-SHA256（10 万次迭代），格式 `pbkdf2_sha256$iter$salt$hash` | — |
| `verify_password` | 校验密码，使用 `hmac.compare_digest`（防时序攻击） | — |
| `create_user` | 注册：校验用户名(2-32)/密码(4-64)、查重 | 写 Redis Hash + user_index |
| `authenticate_user` | 登录验证，成功返回用户 dict，失败返回 None | 读 Redis |
| `get_user` | 获取用户信息（剔除密码哈希） | 读 Redis |
| `ensure_default_admin` | 首次部署确保 `admin/admin` 存在 | 条件写 Redis |

#### 5.2.4 Redis 客户端：[redis_client.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/redis_client.py)

全局单例 `redis_client`（`decode_responses=True`，最大连接 20）。

**异步任务队列**（List + Hash + Stream 组合）：

| Key 模式 | 类型 | 用途 |
|----------|------|------|
| `legalmind:task_queue` | List | 待处理任务 ID 队列（`rpush`/`lpop`） |
| `legalmind:task_status:{id}` | Hash | 任务状态（类型/payload/status/progress/result） |
| `legalmind:task_stream:{id}` | Stream | 任务进度事件流（供前端订阅，maxlen 1000） |

| 函数 | 职责 |
|------|------|
| `init_redis` / `close_redis` / `get_redis` | 连接生命周期 |
| `generate_task_id` | UUID |
| `enqueue_task` | 入队（幂等：已存在则直接返回） |
| `get_task_status` / `update_task_status` | 状态读写（更新时同步发 Stream 事件） |
| `pop_task` | Worker 取任务 |
| `get_stream_events` | `XREAD` 订阅进度 |
| `redis_health_check` | Ping + 延迟 + 内存 |

#### 5.2.5 LLM 客户端：[llm_client.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/llm_client.py)

`LLMClient` 类，三套 httpx 客户端单例（Proxy / 直连 / 本地）。

| 方法 | 签名 | 职责/副作用 |
|------|------|-----------|
| `get_chat_model` | `(model, temperature, max_tokens, streaming) -> ChatOpenAI` | 返回 LangChain ChatOpenAI（按三路由配置） |
| `chat` | `async (model, messages, temperature, max_tokens, cache_key) -> dict` | 同步对话；支持 Redis 缓存（TTL 1h） |
| `chat_stream` | `async (model, messages, ...) -> AsyncIterator[dict]` | 流式对话 |
| `health_check` | 直连/代理健康检查 |
| `local_health_check` | 检查本地模型服务与已加载模型 |
| `list_models` | 列举 Proxy 模型 |
| `close` | 关闭所有客户端 |

全局入口：`get_llm_client()`（单例）、`close_llm_client()`。

#### 5.2.6 PostgreSQL 客户端：[pg_client.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/pg_client.py)

**三库独立引擎**（连接池 pool_size=5，max_overflow=10）：

| 引擎 | 库 | 内容 |
|------|-----|------|
| `judge_engine` | judge_db | 裁判文书、量刑标准、审判流程 |
| `lawyer_engine` | lawyer_db | 辩护策略、证据规则、合同模板、法律意见 |
| `law_engine` | law_db | 法律法规、司法解释、行政规章 |

**ORM 模型（11 个，均带可选 1024 维向量列）**：

| 库 | 模型类 | 表 |
|----|-------|-----|
| judge | `JudgeCase` | judge_cases（裁判文书） |
| judge | `SentencingGuideline` | sentencing_guidelines（量刑标准） |
| judge | `TrialProcedure` | trial_procedures（审判流程） |
| lawyer | `DefenseStrategy` | defense_strategies（辩护策略） |
| lawyer | `EvidenceRule` | evidence_rules（证据规则） |
| lawyer | `ContractReviewTemplate` | contract_review_templates（合同审查模板） |
| lawyer | `LegalOpinion` | legal_opinions（法律意见） |
| law | `LegalProvision` | legal_provisions（法律法规） |
| law | `JudicialInterpretation` | judicial_interpretations（司法解释） |
| law | `AdministrativeRegulation` | administrative_regulations（行政规章） |

| 函数 | 职责 |
|------|------|
| `init_pg` / `close_pg` | 三库建表 / 释放连接池 |
| `search_*_by_vector`（7 个） | 各表向量检索（cosine_distance），返回含相似度 score |
| `search_law_by_keyword` | 法条 ILIKE 全文检索 |

#### 5.2.7 Qdrant 客户端：[qdrant_client.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/qdrant_client.py)

三套 Collection（1024 维，Cosine）：`judge_knowledge`、`lawyer_knowledge`、`law_knowledge`。

客户端支持 **本地文件模式**（`QDRANT_PATH`）与 **远程 URL 模式**（`QDRANT_URL`）自动切换。

| 函数 | 职责 |
|------|------|
| `init_qdrant` / `close_qdrant` | 建 Collection / 关闭 |
| `upsert_vectors` | 批量插入/更新 |
| `search_vectors` | 向量检索（兼容 `query_points`/`search`，支持 payload 过滤） |
| `delete_vectors` | 删除 |
| `get_collection_info` | Collection 元信息 |

#### 5.2.8 嵌入与重排序

| 文件 | 核心函数 | 职责 |
|------|---------|------|
| [embedding.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/embedding.py) | `embed_text` / `embed_texts` / `compute_similarity` | Qwen3-Embedding（离线优先加载，归一化向量，线程池异步） |
| [reranker.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/reranker.py) | `rerank_documents` | Qwen3-Reranker 精排（query-doc 对打分，失败回退原序） |

---

### 5.3 路由层：[gateway.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/gateway.py)

统一 API 网关，前缀 `/api`，共 **31 个端点**。

#### 5.3.1 可靠性机制（gateway 内定义）

| 机制 | 类/函数 | 说明 |
|------|--------|------|
| 滑动窗口限流 | `SlidingWindowRateLimiter` | 默认 30 次/60s，按 `IP:用户:路由` 维度 |
| 熔断器 | `RedisCircuitBreaker` | 状态 CLOSED/OPEN/HALF_OPEN，存 Redis；失败 5 次开路，30s 后半开探测 |
| 熔断装饰器 | `circuit_protect` | 声明式保护，支持 fallback |
| 组合依赖 | `check_rate_limit` | 鉴权 + 限流，业务端点统一使用 |

#### 5.3.2 端点全景

**认证与系统**

| 方法 | 路径 | 职责 |
|------|------|------|
| POST | `/auth/register` | 注册 |
| POST | `/auth/token` | 登录获取 JWT |
| GET | `/models` | 可用模型列表（含可用性探测） |

**任务与熔断**

| 方法 | 路径 | 职责 |
|------|------|------|
| POST | `/tasks` | 创建异步任务 |
| GET | `/tasks/{id}` | 查询任务状态 |
| GET | `/stream/{id}` | SSE 订阅任务进度 |
| GET | `/circuit-breaker/{name}` | 熔断器状态 |
| POST | `/circuit-breaker/{name}/reset` | 重置熔断器 |

**对话**

| 方法 | 路径 | 职责 |
|------|------|------|
| POST | `/chat/stream` | 流式对话（RAG + 模型降级） |
| POST | `/chat` | 同步对话 |

**工作台**

| 方法 | 路径 | 职责 |
|------|------|------|
| GET | `/dashboard/stats` | 全局统计 |
| POST | `/dashboard/stats/increment` | 增量计数 |
| GET | `/dashboard/cases` | 最近案件 |
| POST | `/dashboard/cases` | 创建案件 |

**文档**

| 方法 | 路径 | 职责 |
|------|------|------|
| POST | `/documents/upload` | 上传（支持 PDF/Word/TXT/图片） |
| GET | `/documents` | 文档列表 |
| GET | `/documents/{id}` | 文档元信息 |
| GET | `/documents/{id}/content` | 提取内容（图片/扫描件自动 OCR） |
| POST | `/documents/{id}/analyze` | 异步入队分析 |

**智能体**

| 方法 | 路径 | 职责 |
|------|------|------|
| POST | `/agents/run` | 运行智能体（分析/审查/检索） |
| POST | `/agents/stream` | 流式运行智能体 |

**知识库**

| 方法 | 路径 | 职责 |
|------|------|------|
| POST | `/knowledge/search` | 四级语义检索 |
| GET | `/knowledge/list` | 分页列表（按 domain 查 PG） |

**模拟法庭辩论**

| 方法 | 路径 | 职责 |
|------|------|------|
| POST | `/debate/run` | 运行完整辩论 |
| POST | `/debate/stream` | 流式辩论（含补证中断） |
| POST | `/debate/kfe` | 仅提取关键法律事实 |

**合同**

| 方法 | 路径 | 职责 |
|------|------|------|
| POST | `/contract/review` | 同步合同审查 |
| POST | `/contract/review/stream` | 流式合同审查 |
| POST | `/contract/draft-clause` | 起草合同条款 |

#### 5.3.3 请求模型（Pydantic）

| 模型类 | 关键字段 |
|--------|---------|
| `ChatRequest` | `messages`、`model`、`temperature`、`max_tokens` |
| `AgentRequest` | `query`、`context`、`task_type` |
| `DebateRequest` | `case_description`、`evidence_summary`、`task_type`、`evidence_supplemented` |
| `ContractReviewRequest` | `contract_text`、`user_position`（默认乙方）、`review_stance`（默认常规） |
| `KnowledgeSearchRequest` / `KnowledgeListRequest` | 查询/域/分页参数 |

#### 5.3.4 合同审查流式 SSE 事件协议

`/contract/review/stream` 基于 `workflow.astream(stream_mode="updates")`，按节点发送：

| SSE event | 触发节点 | data 内容 |
|-----------|---------|----------|
| `metadata` | classify | 条款、合同类型、可读性 |
| `metadata` | scan_risks | 中观/微观问题、漏洞、缺失条款 |
| `message` | generate_report | 报告摘要 |
| `done` | finalize | 结构化审查数据 `structured_review` |
| `error` | 异常 | 错误信息 |

---

### 5.4 services 业务层

#### 5.4.1 workflows 工作流（LangGraph 状态机）

所有工作流通过 `build_*_workflow(heavy_llm, fast_llm)` 构建编译，采用「重型模型（Pro）做深度分析、快速模型（Flash）做检索/汇总」的双模型策略。

**(a) 合同审查工作流** [contract_review_workflow.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/contract_review_workflow.py)

状态 `ContractReviewState`，线性四节点：

```
classify → scan_risks → generate_report → finalize
```

| 节点 | 函数 | 职责（调用 ContractReviewSkill） |
|------|------|--------------------------------|
| classify | `classify_node` | 条款提取 + 合同分类 + Playbook 合规初检 |
| scan_risks | `scan_risks_node` | 中观/微观风险 + 漏洞 + 合规验证（统计 P0/P1） |
| generate_report | `generate_report_node` | 审查意见书 + 汇总（签约结论/P0-P4 计数） |
| finalize | `finalize_node` | 用 Flash 生成前端结构化 JSON（条款树/风险/修订/结论），失败有兜底结构 |

**(b) 辩论工作流** [debate_workflow.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/debate_workflow.py)

状态 `DebateWorkflowState`（最复杂，15 节点），融合 IRAC 框架 + 主动式法官：

```
extract_kfe → check_evidence ─(不足→结束/中断补证)
  → retrieve_knowledge → judge_opening → plaintiff_opening → defendant_opening
  → court_investigation → [辩论循环: plaintiff_rebuttal → defendant_rebuttal
    → judge_comment → convergence_check] ─(收敛→) judge_verdict
  → judgment_report → plain_language → finalize
```

关键机制:
- **补证中断**: 证据不足或法官点评标记 `evidence_needed` 时结束流程，前端补证后以 `evidence_supplemented=True` 重启（跳过开庭、不再中断）
- **收敛判定** `convergence_check`: 语义相似度 + 双方 KFE 一致性 + 最大轮次（3 轮）
- **条件路由**: `route_after_evidence` / `route_after_retrieve` / `route_after_convergence` / `route_after_verdict`

**(c) 法律咨询工作流** [legal_workflow.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/workflows/legal_workflow.py)

状态 `LegalWorkflowState`，按 `task_type` 条件入口并行路由:

```
            ┌→ analyze ──┐
entry → route_by_task_type → review ───→ synthesize → END
            └→ research ──┘
```

`task_type`：analyze / review / research / full（full 走全部三分支）。

#### 5.4.2 agents 智能体技能

均为「构造时注入 LLM」的薄封装，提供异步方法 + 流式生成器。

| 类 | 文件 | 核心方法 | 职责 |
|----|------|---------|------|
| `ContractReviewSkill` | contract_review_skill.py | `extract_and_classify`、`scan_risks`、`generate_report`、`draft_clause`、`full_review` | 合同审查核心（见下） |
| `JudgeSkill` | judge_skill.py | `preside_opening`(JSON/演讲双版本)、`court_investigation`、`evaluate_round`、`render_verdict`、`suggest_mediation` | 法官（开庭/调查/点评/IRAC裁决） |
| `PlaintiffSkill` | plaintiff_skill.py | `opening_statement`、`rebuttal`、`final_statement`（含流式版本） | 原告律师 |
| `DefendantSkill` | defendant_skill.py | `opening_statement`、`rebuttal`、`final_statement`（含流式版本） | 被告律师 |
| `MediatorSkill` | mediator_skill.py | `propose_mediation`、`evaluate_settlement` | 调解员 |
| `JudgmentReportSkill` | judgment_report_skill.py | `generate_judgment`、`generate_mediation_agreement` | 判决书/调解协议 |
| `LegalAnalyzer` | legal_analyzer.py | `analyze` | 案件分析 |
| `ContractReviewer` | contract_reviewer.py | `review` | 合同审查（简版） |
| `RegulatoryResearcher` | regulatory_researcher.py | `research` | 法规检索 |

**ContractReviewSkill 详解**（[contract_review_skill.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/agents/contract_review_skill.py)）:

- **Playbook 体系** `CONTRACT_PLAYBOOKS`: 内置 12 类合同（买卖/租赁/借贷/劳动/服务/担保/知识产权/互联网/婚姻家事/房地产/建设工程/公司投资），每类定义必备条款、常见风险、关键法律
- **系统提示词** `CONTRACT_REVIEW_SYSTEM_PROMPT`: 「三层四步」框架（宏观交易结构/中观文本形式/微观条款语言）+ 双维度风险评级（严重性 S1-S5 × 可能性 L1-L5 → 综合 P0-P4）
- 规则方法（静态）: `extract_clauses`（正则提取多格式中文条款）、`analyze_readability`、`detect_cross_references`、`check_playbook_compliance`
- 输出校验: `_validate_scan_output`、`_compute_risk_level`、`_parse_json`

#### 5.4.3 legal 法律检索层

| 文件 | 核心函数 | 职责 |
|------|---------|------|
| [rag_retriever.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/legal/rag_retriever.py) | `retrieve_legal_knowledge` | **四级检索总入口**（见下） |
| | `generate_hyde_document` | HyDE 假设文档改写 |
| | `format_retrieval_context` | 结果拼装为上下文文本 |
| [sparse_retriever.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/legal/sparse_retriever.py) | `extract_precise_terms`、`build_sparse_conditions`、`sparse_search_keywords`、`merge_dense_sparse_scores` | 稀疏检索（法条编号/日期/金额精确匹配，Dense/Sparse 分融合） |
| [legal_filter.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/legal/legal_filter.py) | `apply_legal_filter`、`compute_legal_score` | 第四级法律规则过滤（来源权重/时效衰减/文书类型加成/KFE 命中率） |
| [kfe_extractor.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/legal/kfe_extractor.py) | `extract_kfe`、`compare_kfe` | 关键法律事实提取/双方一致性比对（LLM + 规则兜底） |
| [convergence.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/legal/convergence.py) | `should_converge`、`compute_semantic_similarity`、`DebateConvergenceTracker` | 辩论收敛判定 |
| [aux_nodes.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/legal/aux_nodes.py) | `translate_to_plain_language`、`check_evidence_sufficiency`、`InterruptRequest` | 白话翻译、证据检查、中断结构 |

**四级检索收敛链路**（`retrieve_legal_knowledge`，核心）:

| 阶段 | 处理 | 关键依赖 |
|------|------|---------|
| Stage 1 | **HyDE 查询改写**（口语化→假设法律文档，2 变体） | LLM（Flash） |
| Stage 2 | **混合召回**: Dense（Qdrant）+ pgvector 并行召回 → 去重 → Sparse 精确匹配 → 分数融合（Top-100） | embedding / Qdrant / pg_client / sparse |
| Stage 3 | **Qwen3-Reranker 精排**（query-doc 相关性重打分，Top-20） | reranker |
| Stage 4 | **法律规则过滤**（来源/时效/类型/KFE 命中加权，Top-K） | legal_filter |

全链路多级降级：嵌入失败/无结果/过滤为空时均回退 `_keyword_fallback` 关键词检索。

#### 5.4.4 OCR 服务：[ocr_service.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/ocr_service.py)

封装 PaddleOCR AIStudio **异步任务模式**（提交→轮询→下载 JSONL）。

| 函数 | 职责 |
|------|------|
| `submit_ocr_job` | multipart 上传文件，返回 jobId |
| `poll_ocr_job` | 轮询状态，done 返回 jsonUrl；failed/超时抛异常 |
| `fetch_ocr_text` | 下载 JSONL，提取每页文本框，**按 y 坐标排序**保持阅读顺序，多字段名 fallback |
| `ocr_file` | **统一入口**: 提交→轮询→拉取；失败返回空串（不阻塞主流程） |

Token 从 `settings.OCR_API_TOKEN` 读取；可选预处理参数（方向分类/去畸变/行方向）默认关闭以加速。

---

## 6. 前端详解

### 6.1 路由与页面（App Router）

根布局 [layout.tsx](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/layout.tsx) 用 `AuthGuard` 包裹全部路由，设置全局元信息。

| 路由 | 文件 | 职责 | 主要使用组件 |
|------|------|------|------------|
| `/` | page.tsx | 登录前首页（Hero/能力介绍）；已登录重定向 `/dashboard` | Hero3DScene、Disclaimer |
| `/login` | login/page.tsx | 登录/注册页 | LoginModal |
| `/chat` | chat/page.tsx | 智能对话 | Sidebar、ChatInterface、RightPanel |
| `/court` | court/page.tsx | 模拟法庭（1092 行，流程编排 + 多气泡渲染 + 补证交互） | JudgeVerdictCard |
| `/documents` | documents/page.tsx | 合同审查（薄壳） | DocumentUpload |
| `/knowledge` | knowledge/page.tsx | 知识库检索/浏览（729 行） | — |
| `/cases` | cases/page.tsx | 案件列表管理（316 行） | — |
| `/dashboard` | dashboard/page.tsx | 工作台（统计 + 最近案件 + 快速入口） | — |

### 6.2 组件层

| 组件 | 行数 | 职责 |
|------|------|------|
| [ChatInterface](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/ChatInterface.tsx) | 489 | 对话主界面：消息流、模型切换下拉、快捷问题、结构化回复渲染 |
| [DocumentUpload](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/DocumentUpload.tsx) | 672 | 合同审查：拖拽/点选上传 → 取内容 → SSE 审查，三栏（条款树/原文/风险修订） |
| [JudgeVerdictCard](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/JudgeVerdictCard.tsx) | 710 | 庭审裁决卡片（KFE/证据/法条/各阶段气泡） |
| [RightPanel](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/RightPanel.tsx) | 204 | 对话右栏：快捷提问、相关法条、风险警示、术语解释 |
| [Sidebar](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/Sidebar.tsx) | 96 | 会话列表与导航 |
| [Hero3DScene](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/Hero3DScene.tsx) | 149 | 首页 Three.js 3D 场景 |
| [LoginModal](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/LoginModal.tsx) | 95 | 登录/注册弹窗 |
| [AuthGuard](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/AuthGuard.tsx) | 59 | 路由级登录守卫 |
| [Disclaimer](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/Disclaimer.tsx) | 36 | 免责声明 |
| HeroBackground | 11 | Hero 背景 |

### 6.3 状态管理：[useChatStore.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/store/useChatStore.ts)

Zustand 全局 store。

**State 字段**: `messages`、`sessions`/`currentSessionId`、`currentCase`/`cases`、`documents`、`isStreaming`/`streamingPhase`、`rightPanelData`、`selectedModel`、`authed`、`error`、`sidebarCollapsed`、`abortController`。

**关键 Actions**:

| Action | 职责 |
|--------|------|
| `sendMessage` | 核心对话流程：构造消息 → SSE 接收 → rAF 节流渲染 → 保存会话 |
| `stopStreaming` | 中断生成（abort） |
| `loginUser` / `setAuthed` / `checkAuth` | 登录态管理（登录时按用户加载会话） |
| `setSelectedModel` | 切换模型（持久化） |
| `createSession` / `switchSession` / `deleteSession` / `saveCurrentSession` | 多会话管理 |
| `uploadAndAnalyze` | 文档上传 + 入队分析 |
| `addMessage` / `updateLastAssistantMessage` | 消息操作 |

**内置本地规则库**: `LAW_KEYWORDS`、`RISK_KEYWORDS`、`TERM_EXPLANATIONS` 及场景检测 `detectScenario`，由 `buildRightPanelData` 聚合生成右栏数据（租赁/劳动/合同/消费/婚姻/侵权等场景）。

**持久化（localStorage，按用户名隔离）**:

| Key（base） | 用途 |
|------------|------|
| `legalmind_sessions` | 会话（最多 50 个） |
| `legalmind_chat_history` | 案件记忆 |
| `legalmind_selected_model` | 模型偏好 |

### 6.4 API 层：[api.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/api.ts)

**凭证管理**: Token 存 `localStorage.legalmind_token`，用户名存 `legalmind_username`。

**核心机制 — 通用 SSE 解析器** `parseSSEStream<T>`:
- 通过 `response.body.getReader()` + `TextDecoder` 增量读取
- 按 `event:` / `data:` 行解析，通过 `eventMap` 将事件名映射为强类型数据
- 被 `chatStream` / `debateStream` / `contractReviewStream` 统一复用

**导出函数分组**:

| 分组 | 函数 |
|------|------|
| 认证 | `login`、`register`、`setToken`/`clearToken`、`isAuthenticated`、`getUsername` |
| 对话 | `chatStream`（异步生成器）、`chatCompletion` |
| 模型 | `listModels` |
| 工作台 | `getDashboardStats`、`incrementStat`、`getRecentCases`、`createCase` |
| 文档 | `uploadDocument`（multipart）、`listDocuments`、`getDocumentContent`、`analyzeDocument` |
| 知识库 | `searchKnowledge`、`listKnowledge` |
| 辩论 | `debateStream`、`runDebate` |
| 合同 | `contractReviewStream`、`reviewContract` |
| 系统 | `checkHealth` |

**关键类型**: `ChatMessage`、`ModelOption`、`DashboardStats`、`DocumentItem`、`KnowledgeSearchResult`、`StructuredSummary`、`StructuredReviewData`，以及各流式事件联合类型（chunk/done/error/status/metadata）。

---

## 7. 数据存储设计

### 7.1 Redis 用途全景

| 用途 | Key 模式 |
|------|---------|
| 用户账号 | `legalmind:user:{username}`（Hash） |
| 用户索引 | `legalmind:user_index`（Set） |
| 任务队列 | `legalmind:task_queue`（List） |
| 任务状态 | `legalmind:task_status:{id}`（Hash） |
| 任务事件 | `legalmind:task_stream:{id}`（Stream） |
| 熔断器状态 | `legalmind:cb:{name}`（Hash） |
| 仪表盘统计 | `legalmind:stats:{key}` |
| 文档元信息 | `legalmind:docs:{id}`（Hash，含文件路径） |
| LLM 缓存 | `legalmind:llm_cache:{key}`（TTL 1h） |

### 7.2 PostgreSQL 三库

见 [5.2.6](#526-postgresql-客户端pg_clientpy)。三库独立、各表均配可选向量列，schema 初始化见 [backend/sql/init/](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/sql/init)（4 个 SQL：建库 + 三库 schema）。

### 7.3 Qdrant 三 Collection

见 [5.2.7](#527-qdrant-客户端qdrant_clientpy)。向量 1024 维 / Cosine，payload 承载原文与元数据。

### 7.4 存储分工原则

- **Redis**: 热数据、会话、队列、计数、短期缓存
- **PostgreSQL/pgvector**: 结构化法律数据 + 关系型向量召回（可 SQL 过滤）
- **Qdrant**: 专用向量检索主力（高性能 ANN + payload 过滤）
- 双向量库（PG + Qdrant）并行召回后去重，互为补充与兜底

---

## 8. 依赖关系

### 8.1 后端模块依赖（调用方向）

```
main.py
  ├─ core.config（所有模块的基础）
  ├─ core.redis_client ──► config
  ├─ core.pg_client ──► config
  ├─ core.qdrant_client ──► config
  ├─ core.llm_client ──► config + redis_client
  ├─ core.embedding / reranker ──► config
  └─ routers.gateway
       ├─ core.security / user_service / redis_client / llm_client
       └─ services
            ├─ workflows ──► agents + legal
            │    ├─ agents ──► llm_client（提供的 BaseChatModel）
            │    └─ legal
            │         ├─ rag_retriever ──► embedding/qdrant/reranker/sparse/legal_filter
            │         ├─ kfe_extractor / convergence / aux_nodes
            │         └─ sparse_retriever ──► qdrant
            └─ ocr_service ──► config（httpx 直连第三方）
```

### 8.2 前后端接口契约

前端经 `/api/*` 与后端交互;三类通信模式:
1. **普通 JSON**: CRUD / 查询
2. **multipart/form-data**: 文件上传
3. **SSE**: 流式对话 / 审查 / 辩论（事件:status/message/metadata/done/error）

### 8.3 外部服务依赖

| 服务 | 用途 | 凭据配置 |
|------|------|---------|
| DeepSeek Cloud API | 云端大模型 | `DEEPSEEK_API_KEY` |
| LiteLLM Proxy | 模型网关（可选） | `LITELLM_VIRTUAL_KEY` |
| 本地模型服务 | 法律微调模型 | `LOCAL_LLM_API_BASE` |
| PaddleOCR AIStudio | 图片 OCR | `OCR_API_TOKEN` |

---

## 9. 项目运行方式

> 环境约定：Linux / WSL2 Ubuntu；项目位于 `~/` 或 `/home/`（**禁用** `/mnt/c/`）；换行符 LF。

### 9.1 方式一：Docker Compose 完整部署（推荐）

根目录 [docker-compose.yml](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docker-compose.yml) 编排 7 个服务:redis / postgres / qdrant / litellm-db / litellm / fastapi / frontend。

```bash
# 1. 准备环境变量（.env 已配置，含 API Key，不入 git）
cp .env.example .env   # 仅首次,填入真实 DEEPSEEK_API_KEY / OCR_API_TOKEN 等

# 2. 构建并启动全部服务（-d 后台运行）
docker compose up -d --build

# 3. 查看服务状态与日志
docker compose ps
docker compose logs -f fastapi

# 4. 停止
docker compose down
```

服务访问地址:

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| 后端 API | http://localhost:8000 |
| API 文档（Swagger） | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/health |
| Prometheus 指标 | http://localhost:8000/metrics |
| LiteLLM | http://localhost:4000 |

### 9.2 方式二：本地开发运行

**后端**:

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 需先启动 Redis / PostgreSQL / Qdrant（可单独 docker compose up -d redis postgres qdrant）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**前端**:

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000
```

前端通过 `NEXT_PUBLIC_API_URL`（默认 `http://localhost:8000`）定位后端。

### 9.3 方式三：简化部署

[deploy/docker-compose.yml](file:///home/jing/Documents/trae_projects/LegalMind%20AI/deploy/docker-compose.yml) 提供仅含 backend/frontend/redis 的精简编排，配合 [deploy/env.example](file:///home/jing/Documents/trae_projects/LegalMind%20AI/deploy/env.example) 使用。

### 9.4 本地微调模型

通过 [scripts/setup_local_model.sh](file:///home/jing/Documents/trae_projects/LegalMind%20AI/scripts/setup_local_model.sh) 初始化本地模型服务（Ollama / llama.cpp server OpenAI 兼容接口），前端选择「法律领域微调模型」（标识 `legalmind-ft`）即路由到本地。

### 9.5 数据初始化

法律知识库通过 [backend/scripts/](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/scripts) 脚本导入:
- `import_all.py` — 一键导入（法律/律师/法官数据集 → 向量化 → Qdrant/PG）
- 另有分模块脚本: `import_law_datasets.py`、`import_cail2018.py`、`import_judge_data.py`、`import_to_qdrant.py`、`embed_cail2018.py`
- 进度记录于 `scripts/.import_progress/`，日志于 `.import_logs/`

### 9.6 默认账号

首次启动自动创建管理员: **admin / admin**（生产环境请及时修改）。

---

## 10. 关键约定与工程规范

| 类别 | 约定 |
|------|------|
| **密钥安全** | 所有密钥仅存 `.env`（已被 `.gitignore` 忽略）；代码经环境变量读取；`.env.example` 只放占位符 |
| **localStorage 隔离** | 所有前端存储 key 按用户名隔离，格式 `{base_key}:{username}` |
| **认证接口** | 注册 `/auth/register` 与登录 `/auth/token` 分离；JWT 的 `sub` 承载用户名 |
| **密码存储** | PBKDF2-HMAC-SHA256（10 万次）+ `hmac.compare_digest` 校验 |
| **模型 Fallback** | 所选模型不可用时自动切换 `deepseek-flash`，并通过 SSE `status` 事件通知前端 |
| **RAG 注入** | 检索内容作为**独立 system 消息**注入，不覆盖系统提示词（避免被带偏） |
| **异步任务** | Redis 队列 + 状态机；工具调用幂等（唯一 `call_id`）+ 超时熔断 |
| **LLM 路由** | `legalmind-ft` 走本地，配置 Proxy 走 LiteLLM，其余直连 DeepSeek |
| **流式渲染** | 前端用 requestAnimationFrame 节流，每帧最多更新一次 DOM |
| **监控** | 关键接口暴露 Prometheus 指标；内存/显存高占用自动回收限流 |

---

## 11. 已知事项与规划

| 事项 | 状态 | 说明 |
|------|------|------|
| **n8n 编排** | 🔶 规划中 | [orchestration/n8n/](file:///home/jing/Documents/trae_projects/LegalMind%20AI/orchestration) 目录已建但为空;规划以队列模式（`EXECUTIONS_MODE=queue`）接入多 Worker |
| **docs 文档** | 🔶 占位 | `docs/` 下 `api-reference.md`、`architecture.md`、`deployment.md` 当前为空文件 |
| **PaddleOCR 字段** | ⚠️ 待验证 | OCR JSONL 文本字段采用多名称 fallback;首次接入建议以真实响应核对字段 |
| **多页扫描 PDF** | ⚠️ 性能 | 逐页 OCR 耗时可能较长，已用 300s 超时兜底 + 临时文件即时清理 |
| LiteLLM 模型 | ✅ 已配置 | 注册 Pro/Flash 双模型，含双向 fallback、Redis 缓存、预算控制 |

---

> 本 Wiki 随代码迭代持续维护。如需定位具体实现，可优先从 [main.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/main.py)（启动主线）、[gateway.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/gateway.py)（接口全景）、[rag_retriever.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/legal/rag_retriever.py)（检索链路）三个入口入手。
