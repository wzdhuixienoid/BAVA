from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from banking_api.domain.enums import RuntimeBackend


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://banking:banking@localhost:5432/banking"
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
    def validate_task_worker_timing(self) -> "Settings":
        if self.task_worker_heartbeat_seconds >= self.task_worker_lease_seconds:
            raise ValueError(
                "TASK_WORKER_HEARTBEAT_SECONDS must be less than "
                "TASK_WORKER_LEASE_SECONDS"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
