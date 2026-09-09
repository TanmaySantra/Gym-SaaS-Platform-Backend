"""
Central application configuration.

All environment-dependent values are read once here via pydantic-settings.
Nothing else in the codebase should call os.environ directly.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    APP_NAME: str = "gym-saas-prototype"
    ENVIRONMENT: str = "development"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True

    # --- Database ---
    DATABASE_URL: str = "postgresql+psycopg://gym_user:gym_password@localhost:5432/gym_saas"

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- JWT ---
    JWT_SECRET: str = "insecure-dev-secret-change-me"
    JWT_REFRESH_SECRET: str = "insecure-dev-refresh-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- AI ---
    AI_API_KEY: str = ""
    AI_MODEL: str = "gemma-flash-lite"
    AI_PROVIDER_BASE_URL: str = "https://example-ai-provider.invalid/v1"

    # --- Celery ---
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # --- Business rules ---
    MEMBERSHIP_GRACE_PERIOD_DAYS: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
