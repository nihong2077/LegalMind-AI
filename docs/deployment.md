# LegalMind AI 部署指南

> 本文所有端口、服务名、镜像 tag、profile 与环境变量名均逐一核实自仓库配置：
> 根目录 [docker-compose.yml](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docker-compose.yml)（**权威编排**）、
> [deploy/docker-compose.yml](file:///home/jing/Documents/trae_projects/LegalMind%20AI/deploy/docker-compose.yml)、
> [backend/.env.example](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/.env.example)、
> [backend/app/core/config.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/config.py) 等。
> 本文不写入任何真实密钥：示例一律用 `<...>` 占位符。

## 1. 前置条件

| 依赖 | 版本要求 | 说明 |
|------|:--------:|------|
| Docker | `≥ 24` | 基础设施容器化 |
| Docker Compose | v2（`docker compose` 子命令） | 支持 `profiles`、`depends_on.condition` 等；v1 `docker-compose` 不保证兼容 |
| Python | `≥ 3.10` | 仅本地裸机运行后端时需要 |
| Node.js | `≥ 18` | 仅本地裸机运行前端时需要 |
| NVIDIA 驱动 + CUDA | `≥ 11.8` | **可选**。GPU 用于 embedding/reranker；无 GPU 时可从 compose 删除 `fastapi` 的 `deploy.resources` GPU 预留段，应用自动回退 CPU |
| RAG/模型权重 | — | 首启需下载/挂载 `models/Qwen/Qwen3-Embedding-0.6B` 等权重，注意显存/内存占用 |

说明：
- 有 GPU 时，`fastapi` 服务通过 `deploy.resources.reservations.devices`（driver `nvidia`, `capabilities: [gpu]`）透传 GPU，**需宿主已安装 nvidia-container-toolkit**；无 GPU 的机器可整体删除该段。
- `backend/app/main.py` 内置内存监控（`MEMORY_WARNING_THRESHOLD=0.80`、`MEMORY_CRITICAL_THRESHOLD=0.90`，每 30s 检查），高占用时自动 GC 并在有 CUDA 时 `torch.cuda.empty_cache()`。

## 2. 快速开始（完整 compose 一键部署）

```bash
# 1) 准备环境变量（真实密钥只进 .env，切勿提交）
cp .env.example .env        # 详见第 5 节，至少填 JWT_SECRET_KEY / DEEPSEEK_API_KEY / LITELLM_MASTER_KEY 等

# 2) 构建后端与前端镜像，并启动全部默认服务
docker compose up -d --build

# 3) 查看状态（等待 postgres/redis/qdrant/litellm 变 healthy）
docker compose ps

# 4) 跟踪日志
docker compose logs -f --tail=50

# 5) 停止（保留数据卷）/ 停止并删除数据卷
docker compose down            # 保留命名卷
docker compose down -v         # ⚠️ 连同 PG/Redis/Qdrant 数据一起删除

# 6) 仅重建后端镜像
docker compose build fastapi
docker compose up -d fastapi
```

启动后访问：
- 前端工作台 <http://localhost:3000>（`frontend` 服务）
- 后端 API / Swagger <http://localhost:8000/docs>（`fastapi` → 容器名 `legalmind-api`）
- 存活探针 <http://localhost:8000/healthz>、就绪探针 <http://localhost:8000/readyz>、指标 <http://localhost:8000/metrics>

> 默认服务集合不含 `kafka`（`ENABLE_KAFKA` 默认 `false`）与可观测组件（`observability` profile 默认关闭）。

## 3. 服务清单

以下来自根 [docker-compose.yml](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docker-compose.yml)：

| 服务名 | 镜像 | 容器名 | 宿主端口 | 关键依赖（depends_on） | 作用 |
|---|---|---|---|------------|------|
| `redis` | `redis:7-alpine` | `legalmind-redis` | `6379:6379` | — | 会话/缓存/队列；AOF 持久化，`maxmemory 256mb` + `allkeys-lru`，健康检查 `redis-cli ping` |
| `postgres` | `pgvector/pgvector:pg16` | `legalmind-postgres` | `5432:5432` | — | 三知识库 + `judge_db` 主库；挂载 `./backend/sql/init` 到 `/docker-entrypoint-initdb.d` |
| `qdrant` | `qdrant/qdrant:v1.9.0` | `legalmind-qdrant` | `6333:6333` | — | 向量库；健康检查用 bash `/dev/tcp` 内建探活（镜像不含 curl/wget） |
| `litellm-db` | `postgres:16-alpine` | `legalmind-litellm-db` | 无 | — | LiteLLM 自身元数据库（DB/用户均为 `litellm`） |
| `litellm` | `ghcr.io/berriai/litellm:main-stable` | `legalmind-litellm` | `4000:4000` | `litellm-db`(healthy)、`redis`(healthy) | LLM 代理网关；挂载 [litellm/config.yaml](file:///home/jing/Documents/trae_projects/LegalMind%20AI/litellm/config.yaml) 只读 |
| `fastapi` | 本地构建 `legalmind-backend:local` | `legalmind-api` | `8000:8000` | `redis`/`postgres`/`qdrant`/`litellm`(均 healthy)、`jaeger`(started) | 后端 API；可选 GPU 透传 |
| `worker-collab` | `legalmind-backend:local` | `legalmind-worker-collab` | 无（容器内 `:8001`） | `redis`(healthy)、`jaeger`(started) | 协同轮次执行 + 孤儿扫描 |
| `worker-memory` | `legalmind-backend:local` | `legalmind-worker-memory` | 无（容器内 `:8001`） | `redis`(healthy)、`jaeger`(started) | 长期记忆抽取/合并 |
| `worker-doc` | `legalmind-backend:local` | `legalmind-worker-doc` | 无（容器内 `:8001`） | `redis`(healthy)、`jaeger`(started) | 文档/OCR 异步任务 |
| `frontend` | 本地构建（`./frontend`）| `legalmind-frontend` | `3000:3000` | `fastapi`(healthy) | Next.js 前端；`NEXT_PUBLIC_API_URL=http://localhost:8000` |
| `jaeger` | `jaegertracing/all-in-one:1.60` | `legalmind-jaeger` | `16686:16686`(UI)、`4317:4317`(OTLP gRPC) | — | OTel trace 后端；`COLLECTOR_OTLP_ENABLED=true` |
| `kafka` | `apache/kafka:3.7.2` | `legalmind-kafka` | `9092:9092` | — | KRaft 单节点（broker+controller 同进程） |
| `kafka-init` | `apache/kafka:3.7.2` | `legalmind-kafka-init` | 无 | `kafka`(healthy) | 一次性任务：建 `collab-turns`/`memory-events`/`doc-tasks` 三个 topic |
| `prometheus` | `prom/prometheus:v2.55.1` | `legalmind-prometheus` | `9090:9090` | —（profile `observability`） | 指标采集 |
| `grafana` | `grafana/grafana:11.3.0` | `legalmind-grafana` | `3001:3000` | `prometheus`（profile `observability`） | 预置看板可视化 |

三个 worker 的启动命令（同镜像、`--role` 区分）：

| 容器 | command |
|---|---|
| `worker-collab` | `["python", "-m", "app.worker.main", "--role", "collab"]` |
| `worker-memory` | `["python", "-m", "app.worker.main", "--role", "memory"]` |
| `worker-doc` | `["python", "-m", "app.worker.main", "--role", "doc"]` |

命名卷：`redis_data`、`postgres_data`、`qdrant_data`、`litellm_db_data`、`kafka_data`、`uploads_data`（`fastapi` 与 `worker-doc` 共享，OCR 异步链路读取上传原件）、`grafana_data`。

### deploy/ 精简编排

[deploy/docker-compose.yml](file:///home/jing/Documents/trae_projects/LegalMind%20AI/deploy/docker-compose.yml) 是一个**简化部署**，只含 `backend` / `frontend` / `redis` 三个服务（build 指向 `../backend`、`../frontend`），**不包含** postgres / qdrant / litellm / kafka / jaeger / workers，环境变量也更少（`REDIS_URL`、`LITELLM_PROXY_URL`、`LITELLM_VIRTUAL_KEY`；**不注入真实 `DEEPSEEK_API_KEY`**，LLM 须指向外部 LiteLLM 服务）。配套示例为 [deploy/env.example](file:///home/jing/Documents/trae_projects/LegalMind%20AI/deploy/env.example)（`LITELLM_PROXY_URL`、`LITELLM_VIRTUAL_KEY`、`REDIS_URL`、`BACKEND_PORT`、`NEXT_PUBLIC_BACKEND_URL`）。**生产/完整功能请以根目录 compose 为准**。

## 4. 数据库初始化

`postgres` 挂载 [backend/sql/init](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/sql/init) 到 `/docker-entrypoint-initdb.d`，PostgreSQL 仅在**全新数据卷**首启时按文件名字典序执行。此外 `litellm-db` 是**独立**的 PostgreSQL 容器，其库 `litellm` 由镜像 `POSTGRES_DB=litellm` 直接创建，与本节的四个业务库无关。

四个业务库：
- `judge_db`：由 `postgres` 的 `POSTGRES_DB: judge_db` 在 initdb 阶段创建（不落 SQL 文件）。
- `lawyer_db`、`law_db`、`legalmind_app`：由 `00-create-dbs.sql` 创建（`CREATE DATABASE ... OWNER legalmind`）。

执行顺序与内容：

| 顺序 | 文件 | 目标库 | 内容 |
|---|---|---|---|
| 1 | `00-create-dbs.sql` | 默认库 | 建 `lawyer_db` / `law_db` / `legalmind_app` |
| 2 | `01-judge-schema.sql` | `judge_db`（默认连接）| `CREATE EXTENSION vector`；裁判文书/判例表（`judge_cases` 等） |
| 3 | `02-lawyer-schema.sql` | `lawyer_db`（`\c`） | 辩护策略/代理词等（`defense_strategies` 等） |
| 4 | `03-law-schema.sql` | `law_db`（`\c`） | 法律法规（`legal_provisions` 等） |
| 5 | `04-app-schema.sql` | `legalmind_app`（`\c`） | 应用库：`conversations`、`conversation_members`、`messages`、`agent_registry`、`case_roster_templates`、`memories`、`collab_turns`、`host_decisions` |
| 6 | `05-seed-agents-templates.sql` | `legalmind_app`（`\c`） | 种子数据：10 个 Agent + 8 个案情模板（`ON CONFLICT DO NOTHING`，幂等） |

要点：
- `04-app-schema.sql` / `05-...` 均含 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 与 `ON CONFLICT`，可重复执行。
- **已有数据卷不会重跑 initdb 脚本**：升级后如需补 `04-app-schema.sql` 的表，需手动执行，例如
  `docker compose exec -T postgres psql -U legalmind -d legalmind_app -f - < backend/sql/init/04-app-schema.sql`。
- LangGraph Checkpointer 的三张 checkpoint 表由后端启动时连 `legalmind_app` 自动建（可降级，失败不阻断启动）。

## 5. 环境变量参考

后端读取 `.env`（见 `config.py` 的 `SettingsConfigDict(env_file=".env")`），compose 亦通过 `environment` 注入部分变量并给出默认值。以下按分组列出，**示例均为占位符**。

### 5.1 后端核心
| 变量 | 默认值 | 说明 |
|---|---|---|
| `PROJECT_NAME` | `LegalMind AI` | 服务名 |
| `API_PREFIX` | `/api/v1` | API 前缀 |
| `CORS_ORIGINS` | `http://localhost:3000` | CORS 白名单（逗号分隔） |
| `JWT_SECRET_KEY` | `change-me-in-production` | JWT 签名密钥，建议 `openssl rand -hex 32` 生成 `<your-jwt-secret>` |
| `JWT_ALGORITHM` | `HS256` | JWT 算法 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `admin` | 首次部署默认管理员（启动时自动创建） |

### 5.2 Redis
| 变量 | 默认值 | 说明 |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | 连接串；compose 内为 `redis://redis:6379/0` |
| `REDIS_MAX_CONNECTIONS` | `50` | 连接池上限（SSE 长连接占用高） |

### 5.3 PostgreSQL（四库）
| 变量 | 说明 |
|---|---|
| `PG_JUDGE_URL` | 判例库，`postgresql+asyncpg://legalmind:<pg-password>@postgres:5432/judge_db` |
| `PG_LAWYER_URL` | 律师库 `lawyer_db` |
| `PG_LAW_URL` | 法规库 `law_db` |
| `PG_APP_URL` | 应用库 `legalmind_app`（会话/Agent/记忆/台账/checkpoint） |
| `PG_PASSWORD` | compose 变量，对应上面四个 URL 的口令占位 `<pg-password>`（默认 `legalmind_secure_2024`） |
| `CHECKPOINT_POOL_MAX_SIZE` | LangGraph checkpointer psycopg 连接池上限（默认 10） |

### 5.4 Qdrant 与向量/重排
| 变量 | 默认值 | 说明 |
|---|---|---|
| `QDRANT_URL` | `http://localhost:6333` | compose 内为 `http://qdrant:6333` |
| `QDRANT_PATH` | `data/qdrant_data` | 本地模式路径（相对项目根） |
| `EMBEDDING_MODEL` | `models/Qwen/Qwen3-Embedding-0.6B` | 稠密向量模型 |
| `EMBEDDING_DIM` | `1024` | 向量维度 |
| `EMBEDDING_DEVICE` | `cuda` | 可回退 `cpu` |
| `EMBEDDING_BATCH_SIZE` | `32` | 批大小 |
| `RERANKER_MODEL` / `RERANKER_DEVICE` / `RERANKER_TOP_N` | `Qwen/Qwen3-Reranker` / `cpu` / `20` | 重排模型、设备、保留条数 |
| `HYBRID_RECALL_TOP_K` / `FINAL_TOP_K` | `100` / `8` | 混合召回 / 最终保留 |
| `SCORE_THRESHOLD_DENSE` / `SCORE_THRESHOLD_SPARSE` | `0.55` / `0.3` | 稠密/稀疏打分阈值 |

### 5.5 LLM 与 LiteLLM
| 变量 | 说明 |
|---|---|
| `LITELLM_PROXY_URL` | 后端调用代理地址，compose 内 `http://litellm:4000` |
| `LITELLM_VIRTUAL_KEY` | 后端持有的虚拟 key `<your-virtual-key>`（非真实厂商 key） |
| `LITELLM_MASTER_KEY` | 代理主密钥 `<your-master-key>`，仅 `litellm` 容器消费 |
| `LITELLM_DB_PASSWORD` | LiteLLM 元数据库口令 `<litellm-db-password>`（默认 `litellm_secure_2024`） |
| `DEEPSEEK_API_KEY` | DeepSeek 真实厂商 key `<your-deepseek-key>`；由 `litellm` 注入到代理（见下方密钥隔离说明） |
| `OPENAI_API_KEY` | 备用 OpenAI key `<your-openai-key>`（默认空） |
| `LLM_RETRY_ATTEMPTS` / `RETRY_BASE_DELAY` / `LLM_RETRY_DEADLINE` / `LLM_CALL_TIMEOUT` / `LLM_STREAM_CONNECT_TIMEOUT` | 重试与超时调参 |

**密钥隔离策略**（见 [litellm/config.yaml](file:///home/jing/Documents/trae_projects/LegalMind%20AI/litellm/config.yaml) 注释）：
- 上游 `deepseek-v4-pro` / `deepseek-flash` 两个模型均以 `api_key: os.environ/DEEPSEEK_API_KEY` 在**代理侧**注入真实 key；
- 联网检索 `pass_through_endpoints`（`/v1/tools/search`、`/v1/tools/fetch`）由代理注入 `Authorization: Bearer os.environ/DEEPSEEK_API_KEY`，且**刻意不设 `forward_headers`**，避免客户端 key 覆盖注入的真实 key；
- 后端持有的是 `LITELLM_VIRTUAL_KEY`（虚拟 key），经代理鉴权后转发。
- 根 compose 的 `fastapi` 段**不再**透传 `DEEPSEEK_API_KEY`（真实 key 仅出现在 `litellm` 服务的 `environment` 中）；后端容器只持有 `LITELLM_VIRTUAL_KEY`，与 README「绝不注入后端 API 容器」一致。

### 5.6 本地微调模型
| 变量 | 默认值 | 说明 |
|---|---|---|
| `LOCAL_LLM_API_BASE` | `http://localhost:11434/v1` | Ollama 的 OpenAI 兼容接口 |
| `LOCAL_LLM_MODEL` | `legalmind-ai` | 模型名 |
| `LOCAL_LLM_API_KEY` | `ollama` | 占位 key（Ollama 不校验） |

### 5.7 OCR（PaddleOCR AIStudio 异步任务）
| 变量 | 默认值 | 说明 |
|---|---|---|
| `OCR_API_URL` | `https://paddleocr.aistudio-app.com/api/v2/ocr/jobs` | 任务 API |
| `OCR_API_TOKEN` | 空 | 访问令牌 `<your-ocr-token>`（compose 注入 `worker-doc`） |
| `OCR_MODEL` / `OCR_POLL_INTERVAL` / `OCR_POLL_TIMEOUT` | `PP-OCRv6` / `5` / `300` | 模型与轮询参数 |

### 5.8 可观测性（OTel）
| 变量 | 默认值 | 说明 |
|---|---|---|
| `OTEL_ENABLED` | `true` | 常开；Jaeger 不可达仅丢 trace，不阻断业务 |
| `OTEL_SERVICE_NAME` | `legalmind-backend` | 每 worker 覆盖为 `legalmind-worker-{role}` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://jaeger:4317` | OTLP gRPC |

### 5.9 Kafka
| 变量 | 默认值 | 说明 |
|---|---|---|
| `ENABLE_KAFKA` | `false` | 关闭时事件走**进程内降级** |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | broker 地址 |
| `KAFKA_CLIENT_ID` | `legalmind-backend` | 客户端 ID |
| `KAFKA_TOPIC_TURNS` / `KAFKA_TOPIC_MEMORY` / `KAFKA_TOPIC_DOC_TASKS` | `collab-turns` / `memory-events` / `doc-tasks` | 三个业务 topic |
| `KAFKA_TOPIC_TURNS_DLQ` / `KAFKA_TOPIC_MEMORY_DLQ` / `KAFKA_TOPIC_DOC_DLQ` | `collab-turns-dlq` / `memory-events-dlq` / `doc-tasks-dlq` | 重试耗尽的死信 topic |
| `KAFKA_CONNECT_TIMEOUT` | `5.0` | 懒连首次建连超时（秒） |

### 5.10 联网检索（DeepSeek Search/Fetch）
| 变量 | 默认值 | 说明 |
|---|---|---|
| `WEB_SEARCH_ENABLED` | `true` | 发言 Agent 前置联网决策总开关 |
| `WEB_SEARCH_COUNT` / `WEB_SEARCH_TOP_N` | `10` / `5` | 请求条数 / 注入结果上限 |
| `WEB_SEARCH_TIMEOUT` / `WEB_SEARCH_MAX_ATTEMPTS` | `20.0` / `2` | 读超时 / 可重试错误最大尝试 |
| `WEB_SEARCH_NEED_CONTENT` | `false` | 是否抓取正文 |

### 5.11 日志
| 变量 | 默认值 | 说明 |
|---|---|---|
| `LOG_FORMAT` | `json` | `json` 生产行日志 / `console` 本地彩色 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

### 5.12 协同 Worker / 轮次 / 记忆 / 文档
| 变量 | 默认值 | 说明 |
|---|---|---|
| `WORKER_HEARTBEAT_INTERVAL` / `WORKER_HEARTBEAT_TTL` | `10.0` / `30` | 心跳间隔 / 在线判定窗口（秒） |
| `WORKER_HEALTH_PORT` | `8001` | 容器内 healthz/metrics 端口 |
| `WORKER_KEY_PREFIX` / `WORKER_INDEX_KEY` | `legalmind:worker` / `legalmind:workers:online` | 心跳 key 前缀 / 在线 ZSET |
| `TURN_LEASE_SECONDS` / `TURN_HEARTBEAT_INTERVAL` / `TURN_MAX_ATTEMPTS` / `TURN_HISTORY_LIMIT` / `TURN_ORPHAN_SCAN_INTERVAL` | `90` / `10.0` / `3` / `20` / `30.0` | 轮次租约/续租/重试/历史/孤儿扫描 |
| `MEMORY_EXTRACT_MODEL` / `MEMORY_MERGE_THRESHOLD` / `MEMORY_DEDUP_THRESHOLD` / `MEMORY_MAX_ATTEMPTS` / `MEMORY_TURN_MESSAGES_LIMIT` / `MEMORY_RETRY_BACKOFF` / `MEMORY_RECALL_TOP_K` / `MEMORY_RECALL_MIN_SCORE` | `deepseek-flash` / `0.90` / `0.75` / `3` / `40` / `1.0` / `5` / `0.0` | 记忆抽取/合并/去重/召回 |
| `DOC_MAX_ATTEMPTS` / `DOC_RETRY_BACKOFF` | `3` / `1.0` | OCR 异步任务重试 |

### 5.13 前端
| 变量 | 值 | 说明 |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | compose 内 `frontend` 注入 |

## 6. Kafka（KRaft 单节点）

- 镜像 `apache/kafka:3.7.2`，KRaft 模式（`KAFKA_PROCESS_ROLES=broker,controller`，`KAFKA_NODE_ID=1`），单节点，**生产需换多节点集群**。
- 监听：`PLAINTEXT://0.0.0.0:9092` + `CONTROLLER://0.0.0.0:9093`；对外广播 `PLAINTEXT://kafka:9092`（容器网络内）。
- topic 副本因子均为 `1`，`KAFKA_NUM_PARTITIONS=3`；`kafka-init` 一次性任务用 `--if-not-exists --partitions 3 --replication-factor 1` 创建：

| topic | 生产者/消费者 | 用途 |
|---|---|---|
| `collab-turns` | 后端 ↔ `worker-collab` | 主持人回合事件 |
| `memory-events` | `worker-collab` → `worker-memory` | 记忆抽取/合并事件 |
| `doc-tasks` | 后端 → `worker-doc` | 文档/OCR 异步任务 |
| `collab-turns-dlq` / `memory-events-dlq` / `doc-tasks-dlq` | 各自消费者 | 重试耗尽死信（由应用按需创建） |

- **可关闭降级**：`ENABLE_KAFKA=false`（默认）时后端事件走**进程内** `event_bus`，`kafka` 与 `kafka-init` 可不启动；开启后为**懒连**，broker 故障自动降级、不阻断 API 请求（`worker-memory`/`worker-doc` 在 `ENABLE_KAFKA=true` 时才订阅对应 topic，`worker-collab` 无论开关都跑孤儿扫描）。
- 仅需 Kafka 时：`docker compose up -d kafka kafka-init`（并设 `ENABLE_KAFKA=true` 重启后端/workers）。

## 7. 可观测性 profile（observability）

[prometheus](file:///home/jing/Documents/trae_projects/LegalMind%20AI/deploy/observability/prometheus.yml) 与 `grafana` 定义了 `profiles: ["observability"]`，**默认不启动**；启用：

```bash
docker compose --profile observability up -d
```

- **Prometheus** <http://localhost:9090>，配置采集三个 job：
  - `legalmind-api` → `fastapi:8000/metrics`
  - `legalmind-workers` → `worker-collab:8001`、`worker-memory:8001`、`worker-doc:8001`
  - `litellm` → `litellm:4000/metrics`
  - `scrape_interval`/`evaluation_interval` 均为 `15s`。
- **Grafana** <http://localhost:3001>（容器内 3000 映射到宿主 3001），管理员口令由 `GRAFANA_ADMIN_PASSWORD`（默认 `admin` `<set-a-strong-password>`）控制，注册关闭（`GF_USERS_ALLOW_SIGN_UP=false`）。
- **预置装配**（挂载 `./deploy/observability/grafana-provisioning`）：
  - 数据源 [prometheus.yml](file:///home/jing/Documents/trae_projects/LegalMind%20AI/deploy/observability/grafana-provisioning/datasources/prometheus.yml)：名为 `Prometheus`、`uid=prometheus`、`url=http://prometheus:9090`、默认数据源。
  - 看板提供者 [provider.yml](file:///home/jing/Documents/trae_projects/LegalMind%20AI/deploy/observability/grafana-provisioning/dashboards/provider.yml)：`folder: LegalMind`，从 `/etc/grafana/provisioning/dashboards` 加载。
  - 预置看板 [legalmind-overview.json](file:///home/jing/Documents/trae_projects/LegalMind%20AI/deploy/observability/grafana-provisioning/dashboards/legalmind-overview.json)：**LegalMind 总览**，含 7 个面板 —— API QPS、HTTP P95 延迟、5xx 错误率、外部调用重试/LLM 调用、熔断器状态/拒绝、Kafka 消费积压 lag、Worker 在线/心跳年龄。
- **Jaeger** <http://localhost:16686>（OTLP gRPC `:4317`）**不属于** observability profile，随默认 `up` 启动；后端 OTel 常开，仅关容器会丢失 trace。

## 8. 本地开发运行（裸机）

1) 只起基础设施（Redis/PG/Qdrant/LiteLLM；无需 Kafka）：
```bash
docker compose up -d redis postgres qdrant litellm-db litellm
docker compose ps          # 等待全部 healthy
```
2) 启动后端：
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
3) 启动前端：
```bash
cd frontend
npm install && npm run dev      # http://localhost:3000
```
本地运行时把 `.env` 中的地址改为宿主机侧（`REDIS_URL=redis://localhost:6379/0`、四个 `PG_*_URL` 指向 `localhost:5432`、`QDRANT_URL=http://localhost:6333`、`LITELLM_PROXY_URL=http://localhost:4000`、`OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`）。

## 9. 本地微调模型部署

本地模型以 GGUF 量化文件经 **Ollama** 提供 OpenAI 兼容接口（脚本 [scripts/setup_local_model.sh](file:///home/jing/Documents/trae_projects/LegalMind%20AI/scripts/setup_local_model.sh)）：

- 模型目录：`models/a-----------lora/LegalMind AI/`，含 `legalmind-ai-q4_k_m.gguf`（约 5.0GB）、`Modelfile`、`README.md`（基座 `google/gemma-4-E4B-it`，LoRA rank=16/alpha=32，Q4_K_M）。
- 脚本流程：检测/安装 `ollama` → `ollama serve`（守护）→ 校验 GGUF 与 Modelfile → `ollama create legalmind-ai -f Modelfile` → `ollama list` 校验 → 冒烟测试。
- 部署后 OpenAI 兼容接口为 `http://localhost:11434/v1`，模型名 `legalmind-ai`；后端通过 `LOCAL_LLM_API_BASE` / `LOCAL_LLM_MODEL` / `LOCAL_LLM_API_KEY` 对接，前端可切换到「法律领域微调模型」。

```bash
bash scripts/setup_local_model.sh
```

## 10. 健康检查、运维与故障排查

### 10.1 探针语义（`fastapi`，见 [backend/app/main.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/main.py)、[backend/app/core/health.py](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/app/core/health.py)）

| 端点 | 语义 |
|---|---|
| `GET /healthz` | 存活探针：进程在即 200，**不查任何依赖**（断 Redis 仍 200） |
| `GET /readyz` | 就绪探针：并行检查 Redis/PostgreSQL/Qdrant/Kafka；全健康或 `disabled` 才 200，否则 503。单项超时 2.5s（Kafka 6.0s） |
| `GET /health` | 聚合健康：Redis/LLM/PG(四库)/Qdrant + 内存用量；返回 `status` = `healthy`/`degraded`/`unhealthy` |
| `GET /metrics` | Prometheus 文本格式指标 |

worker（`:8001`，容器内）另有 `/healthz`（仅进程存活）、`/readyz`（Redis 必需、Kafka 不可达为设计内降级）、`/metrics`。

### 10.2 依赖必需性 / 降级矩阵

| 依赖 | 必需性 | 缺失表现 |
|---|---|---|
| Redis | **必需** | 后端启动连不上会重试 5 次后**拒绝启动**；worker 连不上直接非零退出交编排重启 |
| PostgreSQL | **必需** | 四库任一不可用 → 启动重试 5 次后失败；`/readyz` 503 |
| Qdrant | **可降级** | 启动仅告警，向量检索不可用；`/readyz` 视为未就绪 |
| LiteLLM / LLM | **可降级** | 客户端初始化失败仅告警；`/health` 中 `litellm` 非健康 |
| LangGraph Checkpointer | **可降级** | 协同时空中断/恢复暂不可用 |
| Jaeger | **可降级** | 仅丢 trace，业务不受影响 |
| Kafka | **默认关** | `ENABLE_KAFKA=false` 走进程内事件；开启后 broker 故障自动降级 |

### 10.3 常见运维操作

```bash
docker compose ps                       # 服务与健康状态
docker compose logs -f fastapi          # 跟踪某服务日志
docker compose restart fastapi worker-collab worker-memory worker-doc
docker compose exec postgres psql -U legalmind -d legalmind_app   # 进库
docker compose exec redis redis-cli ping
docker compose down && docker compose up -d --build                # 全量重建
```

### 10.4 故障排查

- **`/readyz` 返回 503**：查看响应 `checks` 中哪一项非健康；PG 报错常见于四库 URL 口令/库名不匹配。
- **后端起不来且日志出现 `Redis 初始化失败`**：确认 `redis` 容器 healthy、`REDIS_URL` 正确。
- **新数据卷但 `legalmind_app` 无表**：initdb 脚本只在**全新卷**执行一次；已有卷需手动跑 `04-app-schema.sql`（见第 4 节）。
- **Qdrant 探针失败**：镜像无 curl/wget，健康检查用 bash `/dev/tcp` 探 `:6333`；确认 `QDRANT_URL` 与容器网络。
- **LLM 调用 401/403**：检查 `LITELLM_MASTER_KEY` / `LITELLM_VIRTUAL_KEY` / `DEEPSEEK_API_KEY` 是否已注入 `litellm` 容器（**不是**写入仓库的 `.env` 之外的地方）。
- **worker 不消费**：确认 `ENABLE_KAFKA=true` 且 `kafka` healthy、`kafka-init` 已建 topic；否则为设计内降级（仅心跳）。
- **无 GPU 报 CUDA 相关错误**：GPU 透传段非必需，可删除 `fastapi.deploy.resources` 并设 `EMBEDDING_DEVICE=cpu`。
- **Grafana 无数据**：需以 `--profile observability` 启动；确认 datasource `Prometheus` 已自动装配指向 `http://prometheus:9090`。

---

> 参考来源：[根 compose](file:///home/jing/Documents/trae_projects/LegalMind%20AI/docker-compose.yml)、[deploy compose](file:///home/jing/Documents/trae_projects/LegalMind%20AI/deploy/docker-compose.yml)、[backend/.env.example](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/.env.example)、[根 .env.example](file:///home/jing/Documents/trae_projects/LegalMind%20AI/.env.example)、[litellm/config.yaml](file:///home/jing/Documents/trae_projects/LegalMind%20AI/litellm/config.yaml)、[backend/sql/init](file:///home/jing/Documents/trae_projects/LegalMind%20AI/backend/sql/init)、[deploy/observability](file:///home/jing/Documents/trae_projects/LegalMind%20AI/deploy/observability)、[scripts/setup_local_model.sh](file:///home/jing/Documents/trae_projects/LegalMind%20AI/scripts/setup_local_model.sh)。
