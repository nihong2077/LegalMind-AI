from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    API_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "LegalMind AI"

    REDIS_URL: str = "redis://localhost:6379/0"

    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"

    RATE_LIMIT_MAX_REQUESTS: int = 30
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT: int = 30
    CIRCUIT_BREAKER_HALF_OPEN_MAX: int = 3

    OPENAI_API_KEY: str = ""

    LITELLM_PROXY_URL: str = "http://localhost:4000"
    LITELLM_VIRTUAL_KEY: str = ""


settings = Settings()
