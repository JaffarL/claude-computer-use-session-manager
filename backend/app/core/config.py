from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量读取控制面配置。"""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Computer Use 会话控制面"
    app_version: str = "0.1.0"
    app_environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = (
        "postgresql+asyncpg://computeruse:computeruse_dev@localhost:5432/computeruse"
    )
    redis_url: str = "redis://localhost:6379/0"

    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str | None = None
    anthropic_model: str | None = None
    api_provider: str = "anthropic"


@lru_cache
def get_settings() -> Settings:
    """返回进程内不可变的配置快照。"""
    return Settings()
