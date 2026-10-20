from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    API_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "LegalMind AI"

    REDIS_URL: str = "redis://localhost:6379/0"
    # SSE 长连接各占一个连接，协同上线后并发订阅会明显抬高连接占用（T1.1）
    REDIS_MAX_CONNECTIONS: int = 50

    PG_JUDGE_URL: str = "postgresql+asyncpg://legalmind:legalmind_secure_2024@localhost:5432/judge_db"
    PG_LAWYER_URL: str = "postgresql+asyncpg://legalmind:legalmind_secure_2024@localhost:5432/lawyer_db"
    PG_LAW_URL: str = "postgresql+asyncpg://legalmind:legalmind_secure_2024@localhost:5432/law_db"
    # 协同会话/编排/记忆独立库（D2：三知识库库不动）
    PG_APP_URL: str = "postgresql+asyncpg://legalmind:legalmind_secure_2024@localhost:5432/legalmind_app"

    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_PATH: str = "data/qdrant_data"  # 本地模式路径，相对于项目根目录

    EMBEDDING_MODEL: str = "models/Qwen/Qwen3-Embedding-0.6B"
    EMBEDDING_DIM: int = 1024
    EMBEDDING_DEVICE: str = "cuda"
    EMBEDDING_BATCH_SIZE: int = 32

    RERANKER_MODEL: str = "Qwen/Qwen3-Reranker"
    RERANKER_DEVICE: str = "cpu"
    RERANKER_TOP_N: int = 20

    HYBRID_RECALL_TOP_K: int = 100
    FINAL_TOP_K: int = 8
    SCORE_THRESHOLD_DENSE: float = 0.55
    SCORE_THRESHOLD_SPARSE: float = 0.3

    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"

    RATE_LIMIT_MAX_REQUESTS: int = 30
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT: int = 30
    CIRCUIT_BREAKER_HALF_OPEN_MAX: int = 3

    # ---- resilience（Harness §7.2）----
    LLM_RETRY_ATTEMPTS: int = 3          # 重试次数（总尝试 = 1 + N）
    RETRY_BASE_DELAY: float = 0.5        # 指数退避基数：0.5s→1s→2s + 25% 抖动
    LLM_RETRY_DEADLINE: float = 30.0     # 重试总预算（秒，jitter deadline）
    LLM_CALL_TIMEOUT: float = 30.0       # 普通 LLM 调用读超时
    LLM_STREAM_CONNECT_TIMEOUT: float = 30.0  # 流式首字节（响应头）超时；迭代读沿用 client 120s

    OPENAI_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""

    LITELLM_PROXY_URL: str = "http://localhost:4000"
    LITELLM_VIRTUAL_KEY: str = ""

    # 本地微调模型（GGUF，经 Ollama 提供 OpenAI 兼容接口）
    LOCAL_LLM_API_BASE: str = "http://localhost:11434/v1"
    LOCAL_LLM_MODEL: str = "legalmind-ai"
    LOCAL_LLM_API_KEY: str = "ollama"

    # OCR 服务（PaddleOCR AIStudio 异步任务 API）
    OCR_API_URL: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    OCR_API_TOKEN: str = ""
    OCR_MODEL: str = "PP-OCRv6"
    OCR_POLL_INTERVAL: int = 5
    OCR_POLL_TIMEOUT: int = 300

    CORS_ORIGINS: str = "http://localhost:3000"

    # ---- 结构化日志（Harness §7.3）----
    LOG_LEVEL: str = "INFO"        # DEBUG/INFO/WARNING/ERROR
    LOG_FORMAT: str = "json"       # json（生产，compose 采集）| console（本地彩色）

    # ---- OpenTelemetry（T0.7，常开；Jaeger 不可达时导出静默失败，不阻断业务）----
    OTEL_ENABLED: bool = True
    OTEL_SERVICE_NAME: str = "legalmind-backend"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://jaeger:4317"  # OTLP gRPC；worker 复用同名配置

    # ---- 旧端点信封回滚开关（T0.12）----
    # False（默认）：/api/* 旧 29 端点全量穿 ApiResponse 信封；
    # True：回滚为旧裸响应（{"detail":...} 等），用于切换事故时一键止血。
    LEGACY_RESPONSE: bool = False

    # ---- Kafka（T0.8；默认关闭，开启后懒连，broker 故障降级不阻断业务）----
    ENABLE_KAFKA: bool = False
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_TOPIC_TURNS: str = "collab-turns"        # 主持人回合事件
    KAFKA_TOPIC_TURNS_DLQ: str = "collab-turns-dlq"  # 轮次死信（T1.6：attempts 耗尽）
    KAFKA_TOPIC_MEMORY: str = "memory-events"      # 记忆抽取/合并事件
    KAFKA_TOPIC_MEMORY_DLQ: str = "memory-events-dlq"  # 记忆抽取死信（T2.2：重试耗尽）
    KAFKA_TOPIC_DOC_TASKS: str = "doc-tasks"       # 文档/OCR 异步任务
    KAFKA_TOPIC_DOC_DLQ: str = "doc-tasks-dlq"     # 文档异步任务死信（T3.4：重试耗尽）
    KAFKA_CONNECT_TIMEOUT: float = 5.0             # 懒连首次建连超时（秒）
    KAFKA_CLIENT_ID: str = "legalmind-backend"

    # ---- LangGraph Checkpointer（T0.9，落 legalmind_app；故障可降级不阻断启动）----
    CHECKPOINT_POOL_MAX_SIZE: int = 10             # psycopg 连接池上限

    # ---- 协同 Worker（T0.10）----
    WORKER_HEARTBEAT_INTERVAL: float = 10.0        # 心跳间隔（秒）
    WORKER_HEARTBEAT_TTL: int = 30                 # 心跳 key 与在线判定窗口（秒）；连续丢失即判死
    WORKER_HEALTH_PORT: int = 8001                 # 容器内 healthz/metrics 端口
    WORKER_KEY_PREFIX: str = "legalmind:worker"    # 心跳 key 前缀
    WORKER_INDEX_KEY: str = "legalmind:workers:online"  # 在线 worker ZSET（score=最后心跳epoch）

    # ---- 协同轮次恢复引擎（T1.6）----
    TURN_LEASE_SECONDS: int = 90                   # 租约：超过该秒数无心跳的 running 轮次视为僵死
    TURN_HEARTBEAT_INTERVAL: float = 10.0          # 轮次续租间隔（秒）
    TURN_MAX_ATTEMPTS: int = 3                     # 连续失败该次数后进 DLQ + status=failed
    TURN_HISTORY_LIMIT: int = 20                   # 新轮次播种的会话历史消息条数（跨轮上下文）
    TURN_ORPHAN_SCAN_INTERVAL: float = 30.0        # worker 周期扫描僵死轮次（认领续跑）间隔（秒）

    # ---- 长期记忆自动抽取/合并（T2.2）----
    MEMORY_EXTRACT_MODEL: str = "deepseek-flash"   # 抽取用轻量模型（Flash）
    MEMORY_MERGE_THRESHOLD: float = 0.90           # cosine ≥ 此值 → 合并更新
    MEMORY_DEDUP_THRESHOLD: float = 0.75           # 0.75–0.90 → 去重提示；< 此值 → 新增
    MEMORY_MAX_ATTEMPTS: int = 3                   # 抽取失败重试上限，达上限进 DLQ
    MEMORY_TURN_MESSAGES_LIMIT: int = 40           # 单轮喂给抽取器的最多消息条数
    MEMORY_RETRY_BACKOFF: float = 1.0              # 抽取重试间隔基准（秒，attempt 递增）
    MEMORY_RECALL_TOP_K: int = 5                   # 对话链路 prepare 召回的用户记忆条数（T2.3）
    MEMORY_RECALL_MIN_SCORE: float = 0.0           # 记忆召回最低相似度阈值（0=不过滤）

    # ---- 文档/OCR 异步任务（T3.4：doc-worker 消费 doc-tasks）----
    DOC_MAX_ATTEMPTS: int = 3                      # OCR 失败重试上限，达上限进 DLQ + status=failed
    DOC_RETRY_BACKOFF: float = 1.0                 # OCR 重试间隔基准（秒，attempt 递增）

    # ---- 联网检索（DeepSeek 官方 tools：Search / Fetch，P2-WebSearch）----
    WEB_SEARCH_ENABLED: bool = True              # 发言 Agent 前置联网决策总开关
    WEB_SEARCH_COUNT: int = 10                   # 单次检索请求条数（1-50，文档默认 10）
    WEB_SEARCH_TOP_N: int = 5                    # 注入资料块/引用卡的结果条数上限
    WEB_SEARCH_TIMEOUT: float = 20.0             # 单次 search/fetch 读超时（秒）
    WEB_SEARCH_MAX_ATTEMPTS: int = 2             # 可重试错误（408/429/5xx/超时）的最大尝试次数
    WEB_SEARCH_NEED_CONTENT: bool = False        # 是否抓取正文（true 更全但更慢、体积更大）

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin"


settings = Settings()
