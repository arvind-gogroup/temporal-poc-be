from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # PostgreSQL
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "review_db"
    POSTGRES_USER: str = "review_user"
    POSTGRES_PASSWORD: str = "review_pass"
    DATABASE_URL: str = ""

    # Temporal
    TEMPORAL_HOST: str = "localhost"
    TEMPORAL_PORT: int = 7233
    TEMPORAL_NAMESPACE: str = "default"
    TEMPORAL_TASK_QUEUE: str = "review-task-queue"

    # App
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # AI Summary
    AI_SUMMARY_MOCK: bool = True
    OPENAI_API_KEY: str = ""

    @model_validator(mode="after")
    def build_database_url(self) -> "Settings":
        if not self.DATABASE_URL:
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        return self

    @property
    def temporal_address(self) -> str:
        return f"{self.TEMPORAL_HOST}:{self.TEMPORAL_PORT}"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


settings = Settings()
