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
| **多智能体协同群聊** | 由隐藏主机/调度智能体动态排程的多智能体协作（星型图），SSE v2 逐 token 流式、轮次状态机、checkpoint/分支、接管式扮演 | `/messages` |
| **合同审查** | 三层四步审查框架、Playbook 合规检查、双维度风险评级（P0-P4）、Redline 修订 | `/documents` |
| **案情统一搜索** | 四路并行召回（法条/法官知识/用户记忆/历史消息），单路失败隔离 | `/search` |
| **用户长期记忆** | 用户画像抽取、向量召回、星标置顶、来源会话跳转、分类筛选 | `/memory` |
| **工作台** | 全局统计、最近案件、快速操作 | `/dashboard` |
| **图片合同 OCR** | 第三方 PaddleOCR 服务识别图片/扫描件合同（文档任务走 Kafka 队列） | 整合于 `/documents` |

> 旧的 `/chat`、`/court`、`/knowledge`、`/cases` 页面已物理删除，统一由 [AuthGuard](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/AuthGuard.tsx) 的 `LEGACY_ROUTE_MAP` 重定向到新路由（`/chat`→`/messages`、`/court`→`/messages?template=court`、`/dashboard`→`/messages`、`/knowledge`→`/search`、`/cases`→`/memory?view=cases`）。

---

## 2. 技术栈总览

### 2.1 后端

| 类别 | 技术选型 | 版本/说明 |
|------|---------|----------|
| 语言 | Python | 3.10+ |
| Web 框架 | FastAPI | ≥0.109，异步、自动 OpenAPI 文档 |
| LLM 编排 | LangChain + LangGraph | LangChain ≥0.3 + LangGraph 1.x（星型协同图；节点命名用 `__` 作命名空间分隔） |
| LLM 网关 | LiteLLM Proxy | 统一模型路由、限流、缓存、Fallback（后端不直持密钥） |
| 缓存/消息 | Redis | 7，异步客户端 `redis.asyncio`（Stream/PubSub/锁/票据/热缓存） |
| 消息队列 | Kafka | 官方 Apache KRaft 3.7.2（无 Zookeeper），3 topic + 各自 DLQ |
| 关系数据库 | PostgreSQL + pgvector | PG 16，**四库架构**（judge/lawyer/law + legalmind_app） |
| 向量数据库 | Qdrant | v1.9.0，**四套 Collection**（三知识库 + user_memories） |
| 嵌入模型 | Qwen3-Embedding-0.6B | 1024 维，sentence-transformers |
| 重排序模型 | Qwen3-Reranker | transformers 加载 |
| 文档解析 | PyMuPDF、python-docx | PDF/DOCX 文本提取 |
| 图像处理 | Pillow | 图片解码 |
| OCR | PaddleOCR AIStudio（第三方） | PP-OCRv6 异步任务 |
| HTTP 客户端 | httpx | 异步调用云端 API / OCR |
| 韧性 | tenacity + Redis 熔断器 | 重试/超时/熔断/降级（`core/resilience.py`） |
| 结构化日志 | structlog | JSON 日志，request-id 透传 |
| 可观测性 | OpenTelemetry + Jaeger | 追踪常开，OTLP 上报 |
| 监控 | prometheus-client | 指标暴露 `/metrics`（+ Prometheus/Grafana 看板） |
| 认证 | PyJWT | HS256，Bearer Token，`sub` 承载用户名 |

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
| 流式通信 | SSE（原生 EventSource + 自实现重连） | SSE v2 协议（message_start/message_delta/message_end） |

### 2.3 基础设施

- **容器化**：Docker Compose（11+ 个服务：redis/postgres/qdrant/litellm-db/jaeger/kafka/kafka-init/litellm/fastapi/worker-collab/worker-memory/worker-doc/frontend）
- **可观测性 profile**：`observability` profile 额外拉起 Prometheus（:9090）与 Grafana（:3001）
- **后台任务**：Kafka KRaft 队列 + 独立 worker 进程（取代早期 n8n 编排规划）
- **运行环境**：Linux / WSL2 Ubuntu

---

## 3. 系统架构

### 3.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                     浏览器（Next.js SSR/CSR）                  │
│   页面层 app/  │  组件层 components/  │  5 个 Zustand Store   │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP / SSE v2（Bearer JWT）
┌───────────────────────────▼─────────────────────────────────┐
│                    FastAPI 应用层（backend/app）              │
│  routers/ gateway（旧端点） + conversations / collab /        │
│           agents / memory / search                            │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              services 业务层（LangGraph）               │  │
│  │  collab（星型协同图）│ memory（长期记忆）│ workflows     │  │
│  │  （旧状态机）│ agents（技能）│ legal（检索）│ OCR        │  │
│  └───────────────────────────────────────────────────────┘  │
│  core 核心层：config / security / llm_client / redis_client   │
│    / pg_client（四库） / qdrant_client / embedding / reranker │
│    / response / errors / resilience / logging / tracing /     │
│    events / checkpoint / metrics / health / web_search        │
└───┬────────────┬───────────────┬───────────────┬────────────┘
    │            │               │               │
┌───▼───┐ ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────────┐
│ Redis │ │ PostgreSQL  │ │   Qdrant    │ │ 外部云端/第三方  │
│缓存/队列│ │ +pgvector   │ │  向量检索    │ │DeepSeek/PaddleOCR│
│锁/票据 │ │  四库架构    │ │ 四Collection │ └─────────────────┘
└───┬───┘ └─────────────┘ └─────────────┘
    │ Kafka（KRaft 3.7.2）
    ▼
┌──────────────────────────────┐   ┌──────────────────────────┐
│ worker-collab / -memory / -doc│   │ Jaeger(OTel) / Prometheus │
│ （独立进程，:8001 /healthz） │   │ /Grafana（observability） │
└──────────────────────────────┘   └──────────────────────────┘
                          ▲
                   LiteLLM Proxy（模型网关，唯一 LLM 出海口）
                   限流 / 缓存 / Fallback
```

### 3.2 请求处理主线

以最典型的 **多智能体协同群聊** 为例（[collab.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/collab.py) + [services/collab/runner.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/runner.py)）：

```
前端（useCollabStreamStore / lib/sse.ts，原生 EventSource）
  → POST /api/collab/conversations/{id}/events/ticket（JWT 鉴权，签发 60s 一次性票据）
  → GET  /api/collab/conversations/{id}/events（SSE，带 ticket；支持 Last-Event-ID 回放）
  → 用户发消息 → 会话消息落库 + 最近消息热缓存（Redis List）
  → 开启一轮 turn：写 turn 状态 + 抢占轮次锁（Redis SET NX PX 10min）
      Kafka 开启 → 投递 collab-turns（worker-collab 消费）；关闭 → 进程内 TurnRunner 兜底
  → LangGraph 星型协同图执行（host 隐藏主持人 + scheduler 隐藏调度智能体）：
      prepare（记忆召回 / 工具并行预取）→ 逐辐条 agent / tool 发声 → conclude（判决书/纪要）
  每轮 turn：
      调度智能体按上下文动态排序候选发言者（无硬编码业务顺序）
      每个 agent 收尾后 host 决策 → 下一发言者；tool 辐条（法规/类案检索）产出引用卡
      发言前写入「下面是——发言」分隔条（隐藏 host/scheduler 身份）
  → SSE v2 事件：message_start → message_delta(逐 token)* → message_end → turn 生命周期事件
  → host 决策落库 host_decisions；轮次状态机 + LangGraph Postgres Checkpointer 支持中断/恢复/分支
```

> 旧的直连对话端点（`/api/chat`、`/api/chat/stream`、`/api/agents/run`、`/api/agents/stream`、`/api/debate/*`）已在 gateway 中标记 `deprecated=True`，仅作兼容保留；`LEGACY_RESPONSE` 开关已删除。

### 3.3 LLM 调用路由

[llm_client.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/llm_client.py) 的 `LLMClient` 根据模型标识三路由：

| 判断条件 | 目标 | 实际模型 |
|---------|------|---------|
| 模型标识 == `legalmind-ft` | 本地接口（Ollama/llama.cpp，`LOCAL_LLM_API_BASE`） | `LOCAL_LLM_MODEL` |
| 配置了 LiteLLM URL + Virtual Key | LiteLLM Proxy（`LITELLM_PROXY_URL`） | 透传模型名 |
| 其余（未配置代理） | 直接 raise（fail-closed） | —（**绝不直连厂商 API**） |

后端不直连厂商 API：未配置 LiteLLM 代理时 `get_chat_model` / `chat` / `chat_stream` 一律抛错，`health_check` 返回 `unhealthy`。

所有出站 LLM 调用统一经 `core/resilience.py` 包装（按服务名 `litellm`/`local_model`/`ocr`/`qdrant` 走 per-service Redis 熔断器，fail-open），流式重试仅在首字节到达前允许，避免重复生成与重复计费。后端**不持有 LLM 密钥**，一律经内部 LiteLLM 透传。

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
│   │   │   ├── response.py         # 统一响应信封 + EnvelopeRouter + 异常处理器
│   │   │   ├── errors.py           # ErrorCode 枚举 + BizException
│   │   │   ├── resilience.py       # 重试/超时/熔断/降级（RedisCircuitBreaker）
│   │   │   ├── logging.py          # structlog + request-id 中间件
│   │   │   ├── tracing.py          # OpenTelemetry 初始化与 ASGI 插桩
│   │   │   ├── events.py           # Kafka EventBus（懒连 + 失败降级）
│   │   │   ├── checkpoint.py       # LangGraph AsyncPostgresSaver
│   │   │   ├── metrics.py          # Prometheus 指标 + ASGI 中间件
│   │   │   ├── health.py           # /healthz、/readyz 就绪聚合
│   │   │   ├── redis_client.py     # Redis 连接、任务队列、协同键/锁/票据
│   │   │   ├── pg_client.py        # PostgreSQL 四库引擎 + ORM（知识库 + 应用）
│   │   │   ├── qdrant_client.py    # Qdrant 客户端 + Collection
│   │   │   ├── embedding.py        # Qwen3-Embedding 嵌入服务
│   │   │   ├── reranker.py         # Qwen3-Reranker 重排序
│   │   │   ├── web_search.py       # 联网检索（仅经 LiteLLM 透传）
│   │   │   └── llm_client.py       # LLM 统一客户端（两路由：本地微调 / LiteLLM 代理）
│   │   ├── routers/
│   │   │   ├── gateway.py          # 旧端点集合（含 deprecated 兼容端点）
│   │   │   ├── conversations.py    # 会话/消息/成员/接管/转发/纪要/checkpoint/fork
│   │   │   ├── collab.py           # 协同 SSE（票据 + 事件流）
│   │   │   ├── agents.py           # 模板与 Agent 目录（只读）
│   │   │   ├── memory.py           # 用户长期记忆 CRUD + 开关
│   │   │   └── search.py           # 案情统一搜索
│   │   ├── worker/                 # Kafka 后台 worker
│   │   │   ├── main.py             # --role collab|memory|doc，心跳/健康/指标
│   │   │   └── consumers/
│   │   │       ├── collab.py       # 轮次消费 + 孤儿扫描
│   │   │       ├── memory.py       # 记忆事件消费
│   │   │       └── doc.py          # 文档任务消费
│   │   └── services/               # 业务层
│   │       ├── collab/             # LangGraph 星型协同图（host/scheduler/辐条/模板）
│   │       ├── memory/             # 长期记忆抽取/管线/存储
│   │       ├── workflows/          # 旧 LangGraph 状态机（合同/辩论/咨询）
│   │       ├── agents/             # 智能体技能封装
│   │       ├── legal/              # 法律检索核心链路
│   │       └── ocr_service.py      # PaddleOCR 服务封装
│   ├── scripts/                    # 数据导入/清洗脚本
│   ├── sql/init/                   # 数据库初始化 SQL（建库 + 四库 schema + 种子）
│   ├── tests/                      # 测试
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env
├── frontend/                       # Next.js 前端
│   ├── app/                        # App Router 页面
│   │   ├── lib/                    # http.ts / api.ts / collab.ts / sse.ts / memory.ts / search.ts
│   │   ├── layout.tsx / page.tsx   # 布局（AuthGuard 包裹）/ 首页
│   │   └── login/ messages/ memory/ search/ documents/ dashboard/
│   ├── components/
│   │   ├── collab/                 # Avatar/ChatArea/ConversationList/IconRail/MessageBubble/RightRail/...
│   │   ├── memory/                 # CasesPane/MemoryDetail/MemoryEditor/MemoryList
│   │   ├── search/                 # SearchBar/SearchResults/ForwardDialog/NewGroupFromQuoteDialog/...
│   │   └── （旧组件：ChatInterface/DocumentUpload/JudgeVerdictCard/Hero3DScene 等）
│   ├── store/                      # useChatStore / useCollabStore / useCollabStreamStore / useMemoryStore / useSearchStore
│   ├── Dockerfile
│   ├── package.json
│   └── tailwind/next/postcss 配置
├── litellm/config.yaml             # LiteLLM Proxy 模型配置
├── orchestration/n8n/              # 早期 n8n 编排目录（已被 Kafka + worker 取代，保留）
├── deploy/                         # 简化部署配置
│   ├── docker-compose.yml
│   └── env.example
├── docs/                           # 文档（含 collab-implementation_plan.md）
├── scripts/setup_local_model.sh    # 本地模型初始化脚本
├── docker-compose.yml              # 完整编排（11+ 服务）
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
| 3 | PostgreSQL **四库**（5 次重试） | **致命** |
| 4 | LangGraph Checkpointer（AsyncPostgresSaver） | 可降级（无检查点能力） |
| 5 | Qdrant | 可降级（向量检索不可用） |
| 6 | LLM 客户端 | 可降级 |
| 7 | 内存监控后台任务 | — |

Kafka EventBus 在启动时初始化，但采用**懒连接**：连接失败或发送异常均不阻断主流程（`ENABLE_KAFKA` 默认关，关时协作/记忆/文档任务回退进程内执行）。

关闭时逆序释放：event_bus → checkpointer → llm → qdrant → pg → redis。

#### 横切能力

| 能力 | 实现 | 说明 |
|------|------|------|
| CORS | `CORSMiddleware` | 来源由 `CORS_ORIGINS` 逗号分隔配置 |
| 请求上下文 | `RequestContextMiddleware`（[logging.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/logging.py)） | 最外层，注入 request-id 并绑定 structlog |
| 指标采集中间件 | `PrometheusASGIMiddleware`（[metrics.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/metrics.py)） | 低基数路由模板标签统计 `http_requests_total`、时延 |
| 旧响应兼容 | `LegacyEnvelopeMiddleware`（[response.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/response.py)） | 将新信封统一映射回旧前端约定 |
| 全局异常处理 | `register_exception_handlers`（[response.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/response.py)） | `BizException`→错误码信封；其他异常映射 HTTP 状态 |
| 追踪插桩 | `instrument_app`（[tracing.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/tracing.py)） | OpenTelemetry 常开，OTLP 上报 Jaeger |
| 健康检查 | `GET /health` | 聚合 Redis/LLM/PG 四库/Qdrant/内存状态 |
| 存活/就绪探针 | `GET /healthz`、`GET /readyz` | `/healthz` 永不查依赖（恒 200）；`/readyz` 并行依赖检查，未就绪返回 503 |
| 指标暴露 | `GET /metrics` | Prometheus 文本格式 |

异常 → HTTP 状态映射（[response.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/response.py) 的 `_STATUS_TO_ERROR` / `register_exception_handlers`）：

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
| 数据库 | `REDIS_URL`(max 50 conns)、`PG_JUDGE_URL`、`PG_LAWYER_URL`、`PG_LAW_URL`、**`PG_APP_URL`**、`QDRANT_URL`/`QDRANT_PATH`、`CHECKPOINT_POOL_MAX_SIZE` |
| 嵌入/重排 | `EMBEDDING_MODEL`(1024维)、`EMBEDDING_DEVICE`、`RERANKER_MODEL`、`RERANKER_TOP_N`、`HYBRID_RECALL_TOP_K`、`FINAL_TOP_K` |
| 认证 | `JWT_SECRET_KEY`、`JWT_ALGORITHM`、`ADMIN_USERNAME`/`ADMIN_PASSWORD` |
| 限流/熔断 | `RATE_LIMIT_*`、`CIRCUIT_BREAKER_*` |
| LLM 韧性 | `LLM_RETRY_*`、`LLM_CALL_TIMEOUT`、`LLM_STREAM_CONNECT_TIMEOUT` |
| API Key | `OPENAI_API_KEY`、`DEEPSEEK_API_KEY` |
| LiteLLM | `LITELLM_PROXY_URL`、`LITELLM_VIRTUAL_KEY` |
| 本地模型 | `LOCAL_LLM_API_BASE`、`LOCAL_LLM_MODEL`、`LOCAL_LLM_API_KEY` |
| Kafka | `ENABLE_KAFKA`(默认 False)、`KAFKA_BOOTSTRAP_SERVERS`、`KAFKA_TOPIC_TURNS`/`MEMORY`/`DOC_TASKS`（各带 `_DLQ`）、`KAFKA_CONNECT_TIMEOUT`、`KAFKA_CLIENT_ID` |
| Worker | `WORKER_HEARTBEAT_INTERVAL/TTL`、`WORKER_HEALTH_PORT`、`WORKER_KEY_PREFIX`、`WORKER_INDEX_KEY` |
| 轮次 | `TURN_LEASE_SECONDS`、`TURN_HEARTBEAT_INTERVAL`、`TURN_MAX_ATTEMPTS`、`TURN_HISTORY_LIMIT`、`TURN_ORPHAN_SCAN_INTERVAL` |
| 记忆 | `MEMORY_EXTRACT_MODEL`、`MEMORY_MERGE_THRESHOLD`、`MEMORY_DEDUP_THRESHOLD`、`MEMORY_MAX_ATTEMPTS`、`MEMORY_RECALL_TOP_K`、`MEMORY_RECALL_MIN_SCORE` |
| 文档任务 | `DOC_MAX_ATTEMPTS`、`DOC_RETRY_BACKOFF` |
| 联网检索 | `WEB_SEARCH_ENABLED`、`WEB_SEARCH_COUNT`、`WEB_SEARCH_TIMEOUT`、`WEB_SEARCH_MAX_ATTEMPTS` |
| 可观测性 | `LOG_LEVEL`/`LOG_FORMAT`、`OTEL_ENABLED`、`OTEL_SERVICE_NAME`、`OTEL_EXPORTER_OTLP_ENDPOINT` |
| OCR | `OCR_API_URL`、`OCR_API_TOKEN`、`OCR_MODEL`、`OCR_POLL_INTERVAL`、`OCR_POLL_TIMEOUT` |

> 注：`API_PREFIX="/api/v1"` 为历史遗留字段，**实际路由前缀为 `/api`**（未使用该字段）。

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

全局单例 `redis_client`（`decode_responses=True`，最大连接 50）。承载三种职责：**任务队列原语**、**协同会话热数据/锁/SSE 票据**、**熔断器/记忆开关/worker 心跳**。

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

**协同会话键**（多智能体群聊）：

| Key 模式 | 类型 | 用途 |
|----------|------|------|
| `legalmind:conv:{id}:messages:recent` | List | 会话最近消息热缓存（`LTRIM` 20 条，TTL 600s） |
| `legalmind:conv:{id}:events` | Stream + PubSub | 协作事件流（`MAXLEN` 500，支持 `Last-Event-ID` 回放） |
| `legalmind:lock:conv:{id}` | String | 轮次锁（`SET NX PX 10min`） |
| `legalmind:sse_ticket:{ticket}` | String | SSE 一次性票据（TTL 60s） |

| 函数 | 职责 |
|------|------|
| `conv_recent_key` / `conv_events_key` / `conv_lock_key` / `sse_ticket_key` | 键名构造 |
| `issue_sse_ticket` / `consume_sse_ticket` | 签发 / 核销一次性 SSE 票据 |
| `acquire_turn_lock` / `release_turn_lock` / `get_turn_lock_holder` / `refresh_turn_lock` | 轮次锁抢占/释放/续期 |
| `append_conv_event` / `read_conv_events_since` | 追加事件 / 按 ID 回放 |
| `get_recent_messages` / `push_recent_message` / `set_recent_messages` / `invalidate_recent_messages` | 热缓存读写/失效 |

> 其他键：熔断器 `legalmind:cb:{name}`（见 [5.2.9](#529-新增核心模块)）、记忆开关 `legalmind:memory:enabled:{user_id}`、worker 心跳 `legalmind:worker:*` + 在线 ZSET `legalmind:workers:online`。

#### 5.2.5 LLM 客户端：[llm_client.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/llm_client.py)

`LLMClient` 类，两套 httpx 客户端单例（LiteLLM Proxy / 本地微调）。

| 方法 | 签名 | 职责/副作用 |
|------|------|-----------|
| `get_chat_model` | `(model, temperature, max_tokens, streaming) -> ChatOpenAI` | 返回 LangChain ChatOpenAI（本地微调 / LiteLLM 代理两路由；未配代理抛错） |
| `chat` | `async (model, messages, temperature, max_tokens, cache_key) -> dict` | 同步对话；支持 Redis 缓存（TTL 1h） |
| `chat_stream` | `async (model, messages, ...) -> AsyncIterator[dict]` | 流式对话 |
| `health_check` | LiteLLM 代理健康检查（未配代理返回 `unhealthy`） |
| `local_health_check` | 检查本地模型服务与已加载模型 |
| `list_models` | 列举 Proxy 模型 |
| `close` | 关闭所有客户端 |

全局入口：`get_llm_client()`（单例）、`close_llm_client()`。

#### 5.2.6 PostgreSQL 客户端：[pg_client.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/pg_client.py)

**四库独立引擎**（知识库三库连接池 pool_size=5/max_overflow=10；应用库 app_engine pool_size=10/max_overflow=20）：

| 引擎 | 库 | 内容 |
|------|-----|------|
| `judge_engine` | judge_db | 裁判文书、量刑标准、审判流程 |
| `lawyer_engine` | lawyer_db | 辩护策略、证据规则、合同模板、法律意见 |
| `law_engine` | law_db | 法律法规、司法解释、行政规章 |
| `app_engine` | **legalmind_app** | 会话/消息/成员/Agent 注册表/记忆/轮次/主持决策 |

> 应用库使用**独立 SQLAlchemy metadata（`AppBase`）**，与知识库 metadata（`Base`）分离，避免跨库表污染（pgvector 列问题）。

**知识库 ORM 模型（10 个，均带可选 1024 维向量列，`Base`）**：

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

**应用 ORM 模型（8 个，`AppBase`）**：`Conversation`、`ConversationMember`、`Message`（`sender_type` 支持 user/agent/tool 等）、`AgentRegistry`、`CaseRosterTemplate`、`Memory`（含 `starred`）、`CollabTurn`、`HostDecision`。

| 函数 | 职责 |
|------|------|
| `init_pg` / `close_pg` | 四库建表 / 释放连接池 |
| `search_*_by_vector`（7 个） | 各知识表向量检索（cosine_distance），返回含相似度 score |
| `search_law_by_keyword` | 法条 ILIKE 全文检索 |

#### 5.2.7 Qdrant 客户端：[qdrant_client.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/qdrant_client.py)

**四套 Collection**（1024 维，Cosine）：知识库三套 `judge_knowledge`、`lawyer_knowledge`、`law_knowledge`（`COLLECTIONS` 字典按域路由），以及用户记忆 `user_memories`（`COLLECTION_USER_MEMORIES`）。

客户端支持 **本地文件模式**（`QDRANT_PATH`）与 **远程 URL 模式**（`QDRANT_URL`）自动切换；Collection 存在性检查使用 `await client.collection_exists(name)` 以规避本地模式异常。

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
| [web_search.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/web_search.py) | `search_web` / `fetch_url` | 联网检索（DeepSeek 官方 API **仅经 LiteLLM 透传**；未配置代理 fail-closed；408/429/5xx 退避重试，4xx 不重试直接抛 `WebSearchError`） |

#### 5.2.9 新增核心模块

P0~P4 协同重构引入的 Harness 横切模块：

| 文件 | 核心导出 | 职责 |
|------|---------|------|
| [response.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/response.py) | `success` / `error` / `ApiResponse`、`EnvelopeRouter`、`register_exception_handlers`、`LegacyEnvelopeMiddleware`、`sse_error_event` | 统一响应信封 `{success,data|error}`、路由工厂、异常处理与前端的旧响应兼容 |
| [errors.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/errors.py) | `ErrorCode` 枚举、`BizException` 及快捷异常类 | 业务错误码（SUCCESS=0、INVALID_PARAMS=40001、NOT_FOUND=40004、UNAUTHORIZED=40101、RATE_LIMITED=42901、TURN_LOCK_CONFLICT=50901、INTERNAL_ERROR=50000、LLM_CALL_FAILED=50201、CIRCUIT_OPEN=50301、KAFKA_DEGRADED=50310、UPSTREAM_TIMEOUT=50401 等） |
| [resilience.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/resilience.py) | `RedisCircuitBreaker`、`with_resilience`、`open_resilient_stream`、`CircuitState` | per-service Redis 熔断器（前缀 `legalmind:cb:`，fail-open）、重试/超时/降级 |
| [logging.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/logging.py) | `setup_logging`、`RequestContextMiddleware` | structlog JSON 日志 + request-id 透传 |
| [tracing.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/tracing.py) | `setup_tracing`、`instrument_app` | OpenTelemetry 常开初始化与 ASGI 插桩 |
| [events.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/events.py) | `EventBus`、`make_consumer`、`event_bus` | Kafka 事件总线（懒连、失败降级不抛异常，`publish` 返回 bool） |
| [checkpoint.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/checkpoint.py) | `init_checkpointer` / `close_checkpointer` / `get_checkpointer` | LangGraph `AsyncPostgresSaver`（连 legalmind_app，建 checkpoints/checkpoint_blobs/checkpoint_writes 表） |
| [metrics.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/metrics.py) | `PrometheusASGIMiddleware`、各类 `*_TOTAL` 指标、`record_kafka_lag` | HTTP/LLM/Kafka/Worker/协同/记忆/文档/联网检索指标（低基数标签） |
| [health.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/health.py) | `readiness_report`、`check_redis/check_postgres/check_qdrant/check_kafka` | 就绪聚合，单组件失败隔离 |

---

### 5.3 路由层

统一前缀 `/api`，由 **6 个 router** 组成：`gateway`（旧端点集合）+ `conversations` / `collab` / `agents` / `memory` / `search`（协同重构新增）。各新 router 均使用 `EnvelopeRouter` 工厂（统一响应信封），`gateway` 仍为普通 `APIRouter`。

| Router | 前缀 | 职责 |
|--------|------|------|
| [gateway.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/gateway.py) | `/api` | 旧端点兼容集合（含 deprecated 端点） |
| [conversations.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/conversations.py) | `/api/conversations` | 会话/消息/成员/接管/转发/纪要/checkpoint/fork |
| [collab.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/collab.py) | `/api/collab/conversations` | 协同 SSE（票据 + 事件流） |
| [agents.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/agents.py) | `/api/agents` | 模板卡与 Agent 目录（只读） |
| [memory.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/memory.py) | `/api/memories` | 用户长期记忆 CRUD + 开关 |
| [search.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/search.py) | `/api/search` | 案情统一搜索 |

#### 5.3.1 可靠性机制

| 机制 | 类/函数 | 说明 |
|------|--------|------|
| 滑动窗口限流 | `SlidingWindowRateLimiter`（gateway 内定义） | 默认 30 次/60s，按 `IP:用户:路由` 维度 |
| 熔断器 | `RedisCircuitBreaker`（已收口至 [core/resilience.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/resilience.py)） | 状态 CLOSED/OPEN/HALF_OPEN，存 Redis；失败阈值开路、超时后半开探测 |
| 熔断装饰器 | `circuit_protect`（gateway 保留兼容） | 声明式保护，支持 fallback |
| 组合依赖 | `check_rate_limit` | 鉴权 + 限流，业务端点统一使用 |

#### 5.3.2 端点全景

**协同会话**（[conversations.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/conversations.py)）

| 方法 | 路径 | 职责 |
|------|------|------|
| GET | `/conversations` | 会话列表 |
| POST | `/conversations` | 建会话（type/template_id/my_role/target_agent_id/agent_ids/title） |
| POST | `/conversations/import` | 旧本地会话迁移（保留原始时间戳，不触发新轮次） |
| GET/PATCH/DELETE | `/conversations/{id}` | 会话详情/更新/删除 |
| POST/DELETE | `/conversations/{id}/members` | 成员增删 |
| POST | `/conversations/{id}/my_role` | 用户角色接管（空值交还 AI，跨轮持久化） |
| GET/POST | `/conversations/{id}/messages` | 消息读取/发送 |
| POST | `/conversations/{id}/forward` | 转发卡片消息到已有会话 |
| POST | `/conversations/{id}/minutes` | 生成会商纪要 |
| GET | `/conversations/{id}/turns/{turn_id}/checkpoints` | 轮次检查点 |
| POST | `/conversations/{id}/turns/{turn_id}/fork` | 轮次分支（回到此轮） |

> 轮次锁冲突返回 **50901**；`ENABLE_KAFKA` 决定协作走 `MODE_KAFKA`（投递 `collab-turns`）或 `MODE_INPROCESS`。

**协同 SSE**（[collab.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/collab.py)）

| 方法 | 路径 | 职责 |
|------|------|------|
| POST | `/collab/conversations/{id}/events/ticket` | 签发 60s 一次性 SSE 票据 |
| GET | `/collab/conversations/{id}/events` | SSE 事件流（`EventSourceResponse`，`Last-Event-ID` 回放） |

**智能体与模板**（[agents.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/agents.py)，只读）

| 方法 | 路径 | 职责 |
|------|------|------|
| GET | `/agents/templates` | 模板卡列表（8 个） |
| GET | `/agents` | Agent 列表（支持 `is_tool`/`q` 过滤） |
| GET | `/agents/{agent_id}` | Agent 详情 |

**用户记忆**（[memory.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/memory.py)）

| 方法 | 路径 | 职责 |
|------|------|------|
| GET/PUT | `/memories/setting` | 记忆功能开关 |
| GET | `/memories` | 列表（分类/星标/搜索/分页） |
| POST | `/memories` | 新增 |
| GET/PATCH/DELETE | `/memories/{memory_id}` | 详情/更新/删除（含归档） |

**统一搜索**（[search.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/search.py)）

| 方法 | 路径 | 职责 |
|------|------|------|
| POST | `/search/unified` | 四路并行召回（法条/法官知识/用户记忆/历史消息），单路失败隔离 fail-open（单路超时 20s） |

**gateway 旧端点**（保留兼容）

| 方法 | 路径 | 职责 |
|------|------|------|
| POST | `/auth/register`、`/auth/token` | 注册 / 登录获取 JWT |
| GET | `/models` | 可用模型列表（含可用性探测） |
| POST/GET | `/tasks`、`/tasks/{id}`、`/stream/{id}` | 异步任务创建/查询/SSE 订阅 |
| GET/POST | `/circuit-breaker/{name}`、`/circuit-breaker/{name}/reset` | 熔断器状态/重置 |
| POST | `/chat`、`/chat/stream` | 对话（**deprecated**） |
| GET/POST | `/dashboard/stats`、`/dashboard/stats/increment`、`/dashboard/cases` | 工作台 |
| POST/GET | `/documents/upload`、`/documents`、`/documents/{id}`、`/documents/{id}/content`、`/documents/{id}/analyze` | 文档上传/列表/内容（图片自动 OCR）/入队分析 |
| POST | `/agents/run`、`/agents/stream` | 运行智能体（**deprecated**） |
| POST/GET | `/knowledge/search`、`/knowledge/list` | 四级语义检索 / 分页列表 |
| POST | `/debate/run`、`/debate/stream`、`/debate/kfe` | 模拟法庭辩论（**deprecated**） |
| POST | `/contract/review`、`/contract/review/stream`、`/contract/draft-clause` | 合同审查（**未废弃**，前端 `/documents` 仍使用） |

#### 5.3.3 请求模型（Pydantic）

| 模型类 | 关键字段 |
|--------|---------|
| `ChatRequest` | `messages`、`model`、`temperature`、`max_tokens` |
| `AgentRequest` | `query`、`context`、`task_type` |
| `DebateRequest` | `case_description`、`evidence_summary`、`task_type`、`evidence_supplemented` |
| `ContractReviewRequest` | `contract_text`、`user_position`（默认乙方）、`review_stance`（默认常规） |
| `KnowledgeSearchRequest` / `KnowledgeListRequest` | 查询/域/分页参数 |
| `CreateConversationRequest` | `type`、`template_id`、`my_role`、`target_agent_id`、`agent_ids`、`title` |
| `UnifiedSearchRequest` | `query`、`sources`（四路子集过滤） |

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

协同重构后业务层新增 `collab/`（多智能体协同编排）与 `memory/`（用户长期记忆）两个子包；`workflows/`、`agents/`、`legal/`、`ocr_service.py` 为旧链路，保持业务红线不变。

#### 5.4.1 collab 协同编排（LangGraph 星型图）

核心是**星型协同图**：隐藏主机（host）为中枢，各 Agent/工具为辐条；**无任何硬编码业务顺序边**，发言者由调度智能体动态排序。

| 文件 | 核心类/函数 | 职责 |
|------|------------|------|
| [state.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/state.py) | `CollabState` | 图状态（会话/成员/候选/轮次/记忆等） |
| [graph.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/graph.py) | `build_collab_graph` | 构建编译星型图（host/scheduler 零固定出边，可注入件） |
| [host_skill.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/host_skill.py) | `HostSkill.speak_and_decide` | 隐藏主持人：发言 + 决策下一发言者 |
| [scheduler_skill.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/scheduler_skill.py) | `SchedulerSkill.decide` | 隐藏调度智能体（D14）：按上下文排序候选 |
| [prompts.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/prompts.py) | `is_court_template` | 模板判据（业务分派只依据 adapter，无硬编码顺序） |
| [registry.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/registry.py) | `RegistryService` / `get_registry` | agent_registry + case_roster_templates（进程级缓存） |
| [runner.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/runner.py) | `TurnRunner` | 轮次执行/恢复引擎（`get_turn_runner()`/`reset_turn_runner()` 进程内单例） |
| [agent_nodes.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/agent_nodes.py) | `make_agent_runner` / `AgentNodeRunner` | Agent 辐条：零侵入 Skill 适配 + S1 流式 |
| [tool_nodes.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/tool_nodes.py) | `make_tool_runner` / `ToolNodeRunner` | 工具辐条（法规/类案检索 → 引用卡，`event_key={turn_id}:r{round}:{tool_id}:0` 幂等） |
| [memory_recall.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/memory_recall.py) | `make_memory_recall` | prepare 节点记忆召回（top5，fail-open） |
| [web_decision.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/web_decision.py) | `make_web_context` / `WebContextProvider` | 联网前置决策（fail-open） |
| [minutes.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/minutes.py) | `MinutesRunner` | 会商纪要生成 |
| [conversation_store.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/conversation_store.py) | `ConversationStore` / `PgConversationStore` | 会话/消息存储协议 + PG 实现 |
| [turn_store.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/turn_store.py) | `TurnStore` / `PgTurnStore` | 轮次状态存储协议 + PG 实现 |
| [audit.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/audit.py) | `record_host_decision` | host 决策落库（fail-open） |
| [speaker_notice.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/speaker_notice.py) | `make_speaker_notice` | 轮次发言分隔条（隐藏主持人身份） |
| [production.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/production.py) | `build_production_injectables` / `get_collab_graph` | 生产接线：按 `state.case_type` 的 adapter 分派（同一张编译图服务所有模板） |
| [templates/court.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/templates/court.py) | `build_court_host_advisor`、`court_scheduler`、`build_court_interaction_card`、`make_court_conclude_producer` | 庭审模板件（纯可注入函数，`build_court_wiring()` 统一装配） |

> 关键约定：host/scheduler **对用户完全隐藏**；每轮发言由隐藏调度智能体排序；轮次状态机 + Postgres Checkpointer 支持中断/恢复/分支。

#### 5.4.2 memory 用户长期记忆

| 文件 | 核心类/函数 | 职责 |
|------|------------|------|
| [extractor.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/memory/extractor.py) | 抽取器 | 用 `MEMORY_EXTRACT_MODEL`（Flash）轻量抽取用户画像 |
| [pipeline.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/memory/pipeline.py) | `ingest_turn` / `dispatch_memory_event` / `load_turn_transcript` | 记忆事件管线（消费侧入口） |
| [store.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/memory/store.py) | `MemoryStore` | PG 权威 + Qdrant 向量；按 user_id 收敛；嵌入失败仅标 `failed` 不阻断；开关键 `legalmind:memory:enabled:{user_id}`；`SCOPES=user/case`、`STATUSES=active/archived` |

> 开关关闭即「不读不写」；去重阈值 0.75、合并阈值 0.90 触发告警但不静默合并；召回失败 fail-open 返回空。

#### 5.4.3 workflows 工作流（LangGraph 状态机）

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

#### 5.4.4 agents 智能体技能

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

> 协同重构后，这些 Skill 通过**零侵入适配**接入协同图辐条（`collab/agent_nodes.py`）：将群组上下文块映射到既有流式方法参数，**不改动原有 persona 提示词**。`judge_skill.py` 新增 `build_collab_system_prompt` 分支。庭审裁决始终由法官智能体出具。

**ContractReviewSkill 详解**（[contract_review_skill.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/agents/contract_review_skill.py)）:

- **Playbook 体系** `CONTRACT_PLAYBOOKS`: 内置 12 类合同（买卖/租赁/借贷/劳动/服务/担保/知识产权/互联网/婚姻家事/房地产/建设工程/公司投资），每类定义必备条款、常见风险、关键法律
- **系统提示词** `CONTRACT_REVIEW_SYSTEM_PROMPT`: 「三层四步」框架（宏观交易结构/中观文本形式/微观条款语言）+ 双维度风险评级（严重性 S1-S5 × 可能性 L1-L5 → 综合 P0-P4）
- 规则方法（静态）: `extract_clauses`（正则提取多格式中文条款）、`analyze_readability`、`detect_cross_references`、`check_playbook_compliance`
- 输出校验: `_validate_scan_output`、`_compute_risk_level`、`_parse_json`

#### 5.4.5 legal 法律检索层

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

#### 5.4.6 OCR 服务：[ocr_service.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/ocr_service.py)

封装 PaddleOCR AIStudio **异步任务模式**（提交→轮询→下载 JSONL）。

| 函数 | 职责 |
|------|------|
| `submit_ocr_job` | multipart 上传文件，返回 jobId |
| `poll_ocr_job` | 轮询状态，done 返回 jsonUrl；failed/超时抛异常 |
| `fetch_ocr_text` | 下载 JSONL，提取每页文本框，**按 y 坐标排序**保持阅读顺序，多字段名 fallback |
| `ocr_file` | **统一入口**: 提交→轮询→拉取；失败返回空串（不阻塞主流程） |

Token 从 `settings.OCR_API_TOKEN` 读取；可选预处理参数（方向分类/去畸变/行方向）默认关闭以加速。

---

### 5.5 worker 后台进程

独立进程（与 API 容器同镜像、不同启动命令）：`python -m app.worker.main --role collab|memory|doc`。

| 文件 | 职责 |
|------|------|
| [worker/main.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/worker/main.py) | 角色入口；`:8001` 暴露 `/healthz`（不查依赖）、`/readyz`、`/metrics`；每 10s 发 Redis 心跳（实例 key TTL 30s + 滚动 ZSET `legalmind:workers:online`）；优雅停机即刻摘除心跳 |
| [consumers/collab.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/worker/consumers/collab.py) | 消费 `collab-turns`（`consume_turns`，组 `legalmind-worker-collab`）；另跑 `orphan_scan_loop`（无论 Kafka 开关均运行），与消费器**共用同一 TurnRunner** |
| [consumers/memory.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/worker/consumers/memory.py) | 消费 `memory-events` → `ingest_turn`；毒消息逐条隔离，重试耗尽路由 `memory-events-dlq` |
| [consumers/doc.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/worker/consumers/doc.py) | 消费 `doc-tasks` → OCR；毒消息逐条隔离，重试耗尽路由 `doc-tasks-dlq` |

> Kafka 关闭（`ENABLE_KAFKA=False`）时，协作/记忆/文档任务自动回退进程内执行，不阻断主业务流。

---

## 6. 前端详解

### 6.1 路由与页面（App Router）

根布局 [layout.tsx](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/layout.tsx) 用 [AuthGuard](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/AuthGuard.tsx) 包裹全部路由（`PUBLIC_PATHS=['/', '/login']`），设置全局元信息。

| 路由 | 文件 | 职责 | 主要使用组件 |
|------|------|------|------------|
| `/` | page.tsx | 登录前首页（Hero/能力介绍）；已登录重定向 `/messages` | Hero3DScene、Disclaimer |
| `/login` | login/page.tsx | 登录/注册页 | LoginModal |
| `/messages` | messages/page.tsx | 消息中心（微信式三栏 IA：IconRail \| ConversationList \| ChatArea \| RightRail） | collab/*、NewConversationWizard、LegacyMigrationBanner |
| `/search` | search/page.tsx | 案情搜索 / 知识库浏览 | search/*（IconRail） |
| `/memory` | memory/page.tsx | 用户长期记忆（`?view=cases` 切换到案件视图 `CasesPane`） | memory/*（IconRail） |
| `/documents` | documents/page.tsx | 合同审查（薄壳） | DocumentUpload |
| `/dashboard` | dashboard/page.tsx | 工作台（统计 + 最近案件 + 快速入口） | — |

> 旧的 `/chat`、`/court`、`/knowledge`、`/cases` 页面**已物理删除**；[AuthGuard](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/AuthGuard.tsx) 的 `LEGACY_ROUTE_MAP`（`/chat`→`/messages`、`/court`→`/messages?template=court`、`/dashboard`→`/messages`、`/knowledge`→`/search`、`/cases`→`/memory?view=cases`）负责重定向。全局导航由 [IconRail](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/collab/IconRail.tsx) 承载（消息中心/案情搜索/记忆/合同审查 4 项）。

### 6.2 组件层

**协同组件** [components/collab/](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/collab)

| 组件 | 职责 |
|------|------|
| `IconRail` | 最左全局图标栏（导航 + 当前用户 + 登出 + 记忆开关） |
| `ConversationList` | 会话列表 |
| `ChatArea` / `ConversationView` | 会话主区与消息流渲染 |
| `MessageBubble` | 消息气泡（含引用卡/工具卡渲染） |
| `RightRail` | 右栏：轮次时间线、「回到此轮」分支等 |
| `NewConversationWizard` | 建群向导（模板成员仅支持追加） |
| `InteractionCard` | 交互卡片（如庭审补证卡片） |
| `LegacyMigrationBanner` | 旧 localStorage 会话迁移横幅 |
| `Avatar` / `format.ts` | 头像与格式化工具 |

**记忆组件** `components/memory/`：`MemoryList`、`MemoryDetail`、`MemoryEditor`、`CasesPane`（案件视图）。

**搜索组件** `components/search/`：`SearchBar`、`SearchResults`、`KnowledgeBrowsePanel`、`ForwardDialog`（转发到已有会话）、`NewGroupFromQuoteDialog`（引用并新建协同群聊）。

**通用/旧组件**

| 组件 | 行数 | 职责 |
|------|------|------|
| [DocumentUpload](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/DocumentUpload.tsx) | 672 | 合同审查（前端 UI 不动）：拖拽/点选上传 → 取内容 → SSE 审查，三栏（条款树/原文/风险修订） |
| [ChatInterface](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/ChatInterface.tsx) | 489 | 旧对话界面（保留，配合 useChatStore） |
| [JudgeVerdictCard](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/JudgeVerdictCard.tsx) | 710 | 庭审裁决卡片（KFE/证据/法条/各阶段气泡） |
| [RightPanel](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/RightPanel.tsx) | 204 | 对话右栏：快捷提问、相关法条、风险警示、术语解释 |
| [Sidebar](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/Sidebar.tsx) | 96 | 会话列表与导航 |
| [Hero3DScene](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/Hero3DScene.tsx) | 149 | 首页 Three.js 3D 场景 |
| [LoginModal](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/LoginModal.tsx) | 95 | 登录/注册弹窗 |
| [AuthGuard](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/AuthGuard.tsx) | 59 | 路由级登录守卫 + 旧路由重定向 |
| [Disclaimer](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/components/Disclaimer.tsx) | 36 | 免责声明 |
| HeroBackground | 11 | Hero 背景 |

### 6.3 状态管理（5 个 Zustand Store）

| Store | 行数 | 职责 |
|-------|------|------|
| [useChatStore.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/store/useChatStore.ts) | 697 | 旧对话 store（保留）：消息流、多会话、登录态、右栏数据 |
| [useCollabStore.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/store/useCollabStore.ts) | 114 | 协同会话列表、Agent 模板目录、当前选中会话 |
| [useCollabStreamStore.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/store/useCollabStreamStore.ts) | 560 | 协同 SSE 流状态（含 `turnId` 定位当前轮次） |
| [useMemoryStore.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/store/useMemoryStore.ts) | 157 | 记忆列表/详情/编辑/开关 |
| [useSearchStore.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/store/useSearchStore.ts) | 76 | 统一搜索状态 |

#### useChatStore（[useChatStore.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/store/useChatStore.ts)）

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

### 6.4 API / lib 层

前端 `app/lib/` 下 6 个模块：

| 文件 | 行数 | 职责 |
|------|------|------|
| [http.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/http.ts) | 323 | 统一 HTTP 客户端：响应信封解包、401/429/502/503/504 退避重试 |
| [api.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/api.ts) | 492 | 旧 API 封装（保留旧导出，内部转发 http.ts 符号） |
| [collab.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/collab.ts) | 329 | 协同：会话/Agent/模板/SSE 票据/旧会话 import |
| [sse.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/sse.ts) | 169 | 基于原生 `EventSource` 的自实现重连（`MAX_RETRIES=12`、退避封顶 8s、累计窗口约 71s） |
| [memory.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/memory.ts) | 127 | 记忆 CRUD / 开关 |
| [search.ts](file:///home/jing/Documents/trae_projects/LegalMind%20AI/frontend/app/lib/search.ts) | 187 | 统一搜索 |

**凭证管理**: Token 存 `localStorage.legalmind_token`，用户名存 `legalmind_username`。

**旧 SSE 解析器（api.ts）** `parseSSEStream<T>`（合同审查等旧流式仍在用）：
- 通过 `response.body.getReader()` + `TextDecoder` 增量读取，按 `event:` / `data:` 行解析，`eventMap` 映射为强类型数据

**api.ts 导出函数分组**:

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

> 协同 SSE 协议（v2）：`message_start` → `message_delta`(逐 token) → `message_end`，另含轮次生命周期与工具/卡片事件；前端 `useCollabStreamStore` 消费。流式失败支持约 70s 总重连窗口（可承受 30s 断网），「重试」按钮正确触发**流重连**而非重发消息。

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
| 会话最近消息 | `legalmind:conv:{id}:messages:recent`（List，`LTRIM` 20 / TTL 600s） |
| 协作事件流 | `legalmind:conv:{id}:events`（Stream `MAXLEN` 500 + PubSub） |
| 轮次锁 | `legalmind:lock:conv:{id}`（`SET NX PX 10min`） |
| SSE 一次性票据 | `legalmind:sse_ticket:{ticket}`（TTL 60s） |
| 记忆开关 | `legalmind:memory:enabled:{user_id}`（用户级，默认开） |
| worker 心跳 | `legalmind:worker:{...}`（实例 key TTL 30s）+ `legalmind:workers:online`（ZSET） |

### 7.2 PostgreSQL 四库

见 [5.2.6](#526-postgresql-客户端pg_clientpy)。知识库三库（judge/lawyer/law）各表配可选向量列，独立 metadata `Base`；应用库 **legalmind_app** 使用独立 metadata `AppBase`（避免 pgvector 列跨库污染），存放会话/消息/成员/记忆/轮次/主持决策。schema 初始化见 [backend/sql/init/](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/sql/init)（6 个 SQL：建库 + 三知识库 schema + 应用库 schema + Agent/模板种子）。

### 7.3 Qdrant 四 Collection

见 [5.2.7](#527-qdrant-客户端qdrant_clientpy)。知识库三套 `judge_knowledge`/`lawyer_knowledge`/`law_knowledge` + 用户记忆 `user_memories`；向量 1024 维 / Cosine，payload 承载原文与元数据。

### 7.4 存储分工原则

- **Redis**: 热数据、会话热缓存、队列、轮次锁、SSE 票据、计数、短期缓存、worker 心跳
- **PostgreSQL/pgvector**: 结构化法律数据（三知识库）+ 关系型向量召回（可 SQL 过滤）；应用数据独立存 `legalmind_app`
- **Qdrant**: 专用向量检索主力（高性能 ANN + payload 过滤），含用户记忆向量
- **Kafka**: 异步任务队列（collab-turns/memory-events/doc-tasks + 各自 DLQ）
- 双向量库（PG + Qdrant）并行召回后去重，互为补充与兜底

---

## 8. 依赖关系

### 8.1 后端模块依赖（调用方向）

```
main.py
  ├─ core.config（所有模块的基础）
  ├─ core.response / errors（统一信封 + 错误码）
  ├─ core.logging / tracing / metrics / health / resilience（横切：日志/追踪/指标/健康/韧性）
  ├─ core.redis_client ──► config
  ├─ core.pg_client（四库） ──► config
  ├─ core.qdrant_client ──► config
  ├─ core.llm_client ──► config + redis_client + resilience
  ├─ core.events（Kafka EventBus）──── Kafka
  ├─ core.checkpoint ──► pg_client（legalmind_app）
  ├─ core.embedding / reranker / web_search ──► config
  ├─ routers（gateway / conversations / collab / agents / memory / search）
  │    ├─ core.security / user_service / redis_client / llm_client
  │    └─ services
  │         ├─ collab（LangGraph 星型图）
  │         │    ├─ graph ──► host_skill / scheduler_skill / agent_nodes / tool_nodes
  │         │    ├─ production ──► templates/court + memory_recall + web_decision
  │         │    ├─ runner ──► conversation_store / turn_store / checkpoint
  │         │    └─ registry / minutes / audit / speaker_notice
  │         ├─ memory ──► extractor / pipeline / store（PG + Qdrant + embedding）
  │         ├─ workflows ──► agents + legal
  │         │    ├─ agents ──► llm_client（提供的 BaseChatModel）
  │         │    └─ legal
  │         │         ├─ rag_retriever ──► embedding/qdrant/reranker/sparse/legal_filter
  │         │         ├─ kfe_extractor / convergence / aux_nodes
  │         │         └─ sparse_retriever ──► qdrant
  │         └─ ocr_service ──► config + resilience（httpx 直连第三方）
  └─ worker（collab/memory/doc 消费器）──► core.events + services（collab / memory / ocr）
```

### 8.2 前后端接口契约

前端经 `/api/*` 与后端交互；通信模式：

1. **统一信封 JSON**: 除 SSE 外所有响应均为 `{success, data|error}`（`EnvelopeRouter` 产出，`LegacyEnvelopeMiddleware` 兼容旧约定）
2. **multipart/form-data**: 文件上传（文档/OCR）
3. **SSE（协同 v2）**: `/api/collab/conversations/{id}/events` 需先取一次性票据；事件 `message_start` / `message_delta` / `message_end` + 轮次/工具/卡片事件，支持 `Last-Event-ID` 回放
4. **SSE（旧）**: 合同审查等仍走 `status/message/metadata/done/error`
5. **异步任务**: 协同/记忆/文档任务经 Kafka（`ENABLE_KAFKA` 关时进程内）

### 8.3 外部服务依赖

| 服务 | 用途 | 凭据配置 |
|------|------|---------|
| DeepSeek Cloud API | 云端大模型 / 联网检索 | `DEEPSEEK_API_KEY`（仅 LiteLLM 内部持有） |
| LiteLLM Proxy | 模型网关（唯一 LLM 出海口） | `LITELLM_VIRTUAL_KEY` |
| 本地模型服务 | 法律微调模型 | `LOCAL_LLM_API_BASE` |
| PaddleOCR AIStudio | 图片 OCR | `OCR_API_TOKEN` |
| Kafka（KRaft） | 异步任务队列 | `KAFKA_BOOTSTRAP_SERVERS` |
| Jaeger | 分布式追踪后端（OTel OTLP） | `OTEL_EXPORTER_OTLP_ENDPOINT` |
| Prometheus / Grafana | 指标采集与看板 | observability profile |

---

## 9. 项目运行方式

> 环境约定：Linux / WSL2 Ubuntu；项目位于 `~/` 或 `/home/`（**禁用** `/mnt/c/`）；换行符 LF。

### 9.1 方式一：Docker Compose 完整部署（推荐）

根目录 [docker-compose.yml](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docker-compose.yml) 编排 **11+ 个服务**：redis / postgres(pgvector:pg16，挂 `backend/sql/init` 四库初始化) / qdrant(v1.9.0) / litellm-db / jaeger(all-in-one:1.60，:16686/:4317) / kafka(apache/kafka:3.7.2 KRaft，:9092) / kafka-init（建 3 topic：collab-turns、memory-events、doc-tasks，各 3 partition）/ litellm(:4000) / fastapi(:8000) / **worker-collab / worker-memory / worker-doc**（同镜像不同 `--role`，:8001）/ frontend(:3000)。

启用 `observability` profile 会额外拉起 **prometheus(:9090)** 与 **grafana(:3001)**（预置 QPS/P95/错误率/重试/熔断/lag/心跳看板）。

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
| 存活/就绪探针 | http://localhost:8000/healthz、http://localhost:8000/readyz |
| Prometheus 指标 | http://localhost:8000/metrics |
| worker 健康 | http://localhost:8001/healthz（各 worker 容器） |
| LiteLLM | http://localhost:4000 |
| Jaeger UI | http://localhost:16686 |
| Grafana / Prometheus | http://localhost:3001、http://localhost:9090（需启用 observability profile） |

```bash
# 启用可观测性组件（Prometheus + Grafana）
docker compose --profile observability up -d
```

### 9.2 方式二：本地开发运行

**后端**:

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 需先启动 Redis / PostgreSQL / Qdrant（可单独 docker compose up -d redis postgres qdrant）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**后台 worker（可选，需 Kafka；`ENABLE_KAFKA=False` 时任务回退进程内，无需 worker）**:

```bash
cd backend
python -m app.worker.main --role collab   # 消费 collab-turns + 孤儿扫描
python -m app.worker.main --role memory   # 消费 memory-events
python -m app.worker.main --role doc      # 消费 doc-tasks
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
| **LLM 路由** | `legalmind-ft` 走本地，配置 Proxy 走 LiteLLM，其余直连 DeepSeek（生产一律经 LiteLLM，后端不直持密钥） |
| **统一响应信封** | 除 SSE 外一律 `{success, data\|error}`；错误用 `ErrorCode` 枚举（如 50901 轮次锁冲突、50310 Kafka 降级）；`LegacyEnvelopeMiddleware` 兼容旧前端 |
| **请求追踪** | 最外层 `RequestContextMiddleware` 注入 request-id 并绑定 structlog；OpenTelemetry **常开**，OTLP 上报 Jaeger |
| **韧性** | 统一经 `core/resilience.py`：per-service Redis 熔断器（fail-open）、重试/超时/降级；流式重试仅限首字节前 |
| **Kafka 降级** | `ENABLE_KAFKA` 开关；EventBus 懒连、发送失败不抛异常；worker 独立进程 + Redis 心跳；Kafka 关闭时协作/记忆/文档任务回退进程内 |
| **协同 SSE 协议** | 一次性票据换取事件流；SSE v2 逐 token（`message_start/delta/end`）+ `Last-Event-ID` 回放；重连约 70s 窗口、重试按钮触发流重连 |
| **幂等与隔离** | 群聊消息 `event_key` 唯一 + `ON CONFLICT DO NOTHING`；工具卡 `event_key={turn_id}:r{round}:{tool_id}:0`；各 worker 毒消息逐条隔离，重试耗尽进 DLQ |
| **主机/调度隐藏** | 主持人（host）与调度智能体（scheduler）**对用户完全隐藏**；用户仅见「下面是——发言」中性分隔条；裁决由法官智能体出具 |
| **应用库隔离** | 应用库 `legalmind_app` 用独立 metadata `AppBase`，与知识库 `Base` 分离，规避跨库 pgvector 列污染 |
| **记忆开关** | 每用户 Redis 开关 `legalmind:memory:enabled:{user_id}`，默认开；关闭即不读不写；抽取用 Flash 模型 |
| **流式渲染** | 前端用 requestAnimationFrame 节流，每帧最多更新一次 DOM；协同流状态由 `useCollabStreamStore` 管理 |
| **监控** | 关键接口暴露 Prometheus 指标（低基数标签）；内存/显存高占用自动回收限流；健康检查严格区分 `/healthz`（不查依赖）与 `/readyz`（聚合并行依赖） |

---

## 11. 已知事项与规划

| 事项 | 状态 | 说明 |
|------|------|------|
| **多智能体协同重构（P0–P4）** | ✅ 已完成 | 星型协同图（隐藏 host/scheduler）、轮次状态机 + checkpoint/fork、接管式扮演（my_role）、会商纪要、引用卡、联网检索、长期记忆、四路统一搜索、Harness 横切、可观测性 |
| **异步任务编排** | ✅ 已落地 | 早期 n8n 规划**已被取代**：改用 Kafka KRaft（apache/kafka:3.7.2）+ 三个独立 worker（collab/memory/doc），[orchestration/n8n/](file:///home/jing/Documents/trae_projects/LegalMind%20AI/orchestration) 目录保留但不再使用 |
| **旧端点收敛** | ✅ 已标记 | `/api/chat`、`/api/chat/stream`、`/api/agents/run`、`/api/agents/stream`、`/api/debate/*` 已标 `deprecated=True`；`LEGACY_RESPONSE` 开关已删除。合同审查端点未废弃（前端仍用） |
| **docs 文档** | ✅ 已补齐 | [docs/collab-implementation_plan.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/collab-implementation_plan.md) 为权威事实来源；[api-reference.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/api-reference.md) / [architecture.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/architecture.md) / [deployment.md](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docs/deployment.md) 已按当前代码事实写完 |
| **PaddleOCR 字段** | ⚠️ 待验证 | OCR JSONL 文本字段采用多名称 fallback；首次接入建议以真实响应核对字段 |
| **多页扫描 PDF** | ⚠️ 性能 | 逐页 OCR 耗时可能较长，已用 300s 超时兜底 + 临时文件即时清理 |
| LiteLLM 模型 | ✅ 已配置 | 注册 Pro/Flash 双模型，含双向 fallback、Redis 缓存、预算控制 |
| Kafka / 可观测性 | ✅ 已配置 | KRaft 无 Zookeeper；Jaeger + OTel 常开；Prometheus + Grafana 经 observability profile 拉起 |

---

> 本 Wiki 随代码迭代持续维护。如需定位具体实现，可优先从 [main.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/main.py)（启动主线）、[collab.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/routers/collab.py) + [services/collab/production.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/collab/production.py)（协同 SSE 与图接线）、[rag_retriever.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/services/legal/rag_retriever.py)（检索链路）三个入口入手。
