from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """服务端运行配置。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    heweather_api_key: str = ""
    amap_api_key: str = ""
    external_connect_timeout_seconds: float = 3.0
    external_read_timeout_seconds: float = 8.0
    external_total_timeout_seconds: float = 10.0


@lru_cache
def get_settings() -> Settings:
    """返回进程内共享的服务端配置。"""

    return Settings()
