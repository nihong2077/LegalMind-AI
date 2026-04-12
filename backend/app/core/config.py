from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "LegalMind AI"
    
    REDIS_URL: str = "redis://localhost:6379"
    
    OPENAI_API_KEY: str = ""
    
    class Config:
        env_file = ".env"


settings = Settings()
