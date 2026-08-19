from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
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
    sse_heartbeat_seconds: float = 15.0
    sse_queue_size: int = 100
    fake_agent_step_delay_seconds: float = 0.08
    agent_provider: Literal["fake", "anthropic"] = "fake"

    runtime_provider: Literal["fake", "docker"] = "fake"
    runtime_namespace: str = "computer-use-session-manager"
    sandbox_image: str = "computer-use-sandbox:local"
    sandbox_public_host: str = "127.0.0.1"
    sandbox_memory_limit: str = "768m"
    sandbox_nano_cpus: int = 1_000_000_000
    sandbox_pids_limit: int = 256
    sandbox_shm_size: str = "256m"
    sandbox_startup_timeout_seconds: float = 60.0
    runtime_reconcile_interval_seconds: float = 30.0
    vnc_access_ttl_seconds: int = 120

    anthropic_api_key: SecretStr | None = None
    # Some Anthropic-compatible gateways expose the credential as AUTH_TOKEN.
    anthropic_auth_token: SecretStr | None = None
    anthropic_base_url: str | None = None
    anthropic_model: str | None = None
    anthropic_max_tokens: int = 4096
    anthropic_max_iterations: int = 30
    api_provider: str = "anthropic"

    @model_validator(mode="after")
    def normalize_anthropic_credential(self) -> "Settings":
        """Fall back to AUTH_TOKEN when API_KEY is not supplied."""
        if (
            (
                self.anthropic_api_key is None
                or not self.anthropic_api_key.get_secret_value().strip()
            )
            and self.anthropic_auth_token is not None
            and self.anthropic_auth_token.get_secret_value().strip()
        ):
            self.anthropic_api_key = self.anthropic_auth_token
        return self


@lru_cache
def get_settings() -> Settings:
    """返回进程内不可变的配置快照。"""
    return Settings()
