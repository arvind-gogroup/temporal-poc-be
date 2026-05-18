"""Application configuration loaded from environment variables or a .env file.

All settings are validated by Pydantic at startup. DATABASE_URL is built
automatically from the individual POSTGRES_* vars unless explicitly provided.

Example .env (see .env.example for the full template):
    POSTGRES_HOST=localhost
    TEMPORAL_HOST=localhost
    APP_ENV=development
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised settings object; access the singleton via ``app.config.settings``.

    Values are read in priority order: environment variables → .env file → defaults.

    Attributes:
        POSTGRES_HOST: PostgreSQL hostname.
        POSTGRES_PORT: PostgreSQL port (default 5432).
        POSTGRES_DB: Database name.
        POSTGRES_USER: Database user.
        POSTGRES_PASSWORD: Database password.
        DATABASE_URL: Full asyncpg connection string. Auto-built from POSTGRES_*
            vars if not set explicitly.
        TEMPORAL_HOST: Temporal server hostname.
        TEMPORAL_PORT: Temporal gRPC port (default 7233).
        TEMPORAL_NAMESPACE: Temporal namespace (default "default").
        TEMPORAL_TASK_QUEUE: Task queue name polled by the worker.
        APP_ENV: Runtime environment; set to "production" to disable /docs.
        APP_PORT: Port the uvicorn server listens on.
        LOG_LEVEL: Python logging level string (e.g. "INFO", "DEBUG").
        AI_SUMMARY_MOCK: When True, returns a templated summary instead of
            calling a real LLM.
        OPENAI_API_KEY: API key for live LLM calls (unused while mocking).
    """

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
        """Construct DATABASE_URL from POSTGRES_* fields if not already set.

        Returns:
            The updated Settings instance.
        """
        if not self.DATABASE_URL:
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        return self

    @property
    def temporal_address(self) -> str:
        """Return the ``host:port`` string used to connect to Temporal.

        Returns:
            Formatted address string, e.g. ``"localhost:7233"``.
        """
        return f"{self.TEMPORAL_HOST}:{self.TEMPORAL_PORT}"

    @property
    def is_production(self) -> bool:
        """Return True when APP_ENV is set to ``"production"``.

        Used to disable Swagger UI and ReDoc in production deployments.
        """
        return self.APP_ENV == "production"


settings = Settings()
"""Module-level singleton. Import and use directly: ``from app.config import settings``."""
