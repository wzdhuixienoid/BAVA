from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
