from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "OrderFlow Core"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://orderflow:orderflow@localhost:5432/orderflow"

    secret_key: str = "dev-only-secret-key-change-me-in-production-32b"
    access_token_expire_minutes: int = 30
    algorithm: str = "HS256"

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
