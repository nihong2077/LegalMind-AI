from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    API_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "LegalMind AI"

    REDIS_URL: str = "redis://localhost:6379/0"

    PG_JUDGE_URL: str = "postgresql+asyncpg://legalmind:legalmind_secure_2024@localhost:5432/judge_db"
    PG_LAWYER_URL: str = "postgresql+asyncpg://legalmind:legalmind_secure_2024@localhost:5432/lawyer_db"
    PG_LAW_URL: str = "postgresql+asyncpg://legalmind:legalmind_secure_2024@localhost:5432/law_db"

    QDRANT_URL: str = "http://localhost:6333"

    EMBEDDING_MODEL: str = "Qwen/Qwen3-Embedding-0.6B"
    EMBEDDING_DIM: int = 1024
    EMBEDDING_DEVICE: str = "cpu"
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

    OPENAI_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""

    LITELLM_PROXY_URL: str = "http://localhost:4000"
    LITELLM_VIRTUAL_KEY: str = ""


settings = Settings()
