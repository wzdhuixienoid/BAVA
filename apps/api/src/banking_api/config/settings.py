from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from banking_api.domain.enums import RuntimeBackend


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://banking:banking@localhost:5432/banking"
    app_environment: Literal["development", "test", "production"] = "development"
    auth_mode: Literal["development", "oidc"]
    development_user_id: str = "dev-user-001"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_allowed_algorithms: list[str] = ["RS256"]
    oidc_jwks_cache_seconds: int = Field(default=300, ge=1, le=86400)
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000"]
    llm_provider: str = "openai_compatible"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 30
    agent_max_steps: int = 6
    agent_max_tool_calls: int = 4
    agent_runtime: RuntimeBackend = RuntimeBackend.LANGGRAPH
    langgraph_checkpoint_database_url: str = ""
    langgraph_strict_msgpack: bool = True
    transfer_approval_ttl_seconds: int = 600
    transfer_reauth_ttl_seconds: int = 300
    transfer_reauth_max_attempts: int = 3
    mock_reauth_code: str = "246810"
    security_reauth_failure_limit: int = Field(default=3, ge=1)
    security_reauth_failure_window_seconds: int = Field(default=600, ge=1)
    security_bypass_limit: int = Field(default=5, ge=1)
    security_bypass_window_seconds: int = Field(default=300, ge=1)
    security_write_lock_seconds: int = Field(default=900, ge=1)
    banking_business_timezone: str = "Asia/Shanghai"
    operation_recovery_enabled: bool = True
    operation_recovery_poll_interval_seconds: float = Field(default=5.0, gt=0)
    operation_recovery_lease_seconds: float = Field(default=60.0, gt=0)
    operation_recovery_initial_retry_seconds: float = Field(default=5.0, gt=0)
    operation_recovery_max_retry_seconds: float = Field(default=300.0, gt=0)
    operation_recovery_backoff_multiplier: int = Field(default=2, ge=1)
    operation_recovery_batch_size: int = Field(default=10, ge=1, le=100)
    outbox_publisher_enabled: bool = True
    outbox_publisher_poll_interval_seconds: float = Field(default=0.5, gt=0)
    outbox_publisher_lease_seconds: float = Field(default=30.0, gt=0)
    outbox_publisher_initial_retry_seconds: float = Field(default=1.0, gt=0)
    outbox_publisher_max_retry_seconds: float = Field(default=60.0, gt=0)
    outbox_publisher_backoff_multiplier: int = Field(default=2, ge=1)
    outbox_publisher_batch_size: int = Field(default=20, ge=1, le=100)
    task_worker_enabled: bool = True
    task_worker_poll_interval_seconds: float = Field(default=0.5, gt=0)
    task_worker_lease_seconds: float = Field(default=60.0, gt=0)
    task_worker_heartbeat_seconds: float = Field(default=15.0, gt=0)
    task_worker_initial_retry_seconds: float = Field(default=2.0, gt=0)
    task_worker_max_retry_seconds: float = Field(default=120.0, gt=0)
    task_worker_backoff_multiplier: int = Field(default=2, ge=1)
    task_worker_batch_size: int = Field(default=4, ge=1, le=100)
    task_worker_max_concurrency: int = Field(default=4, ge=1, le=100)

    @model_validator(mode="after")
    def validate_security_and_worker_settings(self) -> "Settings":
        if self.app_environment == "production" and self.auth_mode == "development":
            raise ValueError("AUTH_MODE=development is forbidden in production")
        if self.auth_mode == "oidc":
            if not self.oidc_issuer or not self.oidc_audience:
                raise ValueError("OIDC_ISSUER and OIDC_AUDIENCE are required in OIDC mode")
            if not self.oidc_allowed_algorithms:
                raise ValueError("OIDC_ALLOWED_ALGORITHMS must not be empty")
            forbidden = {"none", "HS256", "HS384", "HS512"}
            if forbidden.intersection(self.oidc_allowed_algorithms):
                raise ValueError("OIDC_ALLOWED_ALGORITHMS must use asymmetric algorithms")
        if self.task_worker_heartbeat_seconds >= self.task_worker_lease_seconds:
            raise ValueError(
                "TASK_WORKER_HEARTBEAT_SECONDS must be less than TASK_WORKER_LEASE_SECONDS"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
