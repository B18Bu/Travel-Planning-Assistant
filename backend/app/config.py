from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """服务端运行配置；外部密钥只允许由后端环境变量读取。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # 和风天气逐日预报 API 的服务端密钥，只在后端使用，不得暴露。
    heweather_api_key: str = ""
    # 和风天气固定 HTTPS API 域名，不允许客户端覆盖。
    heweather_base_url: str = "https://devapi.qweather.com"
    # 高德地理编码、驾车路线和 POI 文本搜索 API 的服务端密钥，只在后端使用。
    amap_api_key: str = ""
    # 高德地图固定 HTTPS API 域名，不允许客户端覆盖。
    amap_base_url: str = "https://restapi.amap.com"

    # 外部 HTTP 请求的连接、读取和总超时，单位为秒。
    external_connect_timeout_seconds: float = 3.0
    external_read_timeout_seconds: float = 8.0
    external_total_timeout_seconds: float = 10.0
    # 首次请求加重试的最大尝试次数，仅重试受控瞬时错误。
    external_max_attempts: int = 3
    # 单一服务连续失败达到该次数后打开熔断器。
    circuit_breaker_failure_threshold: int = 3
    # 熔断打开的持续时间，单位为秒。
    circuit_breaker_open_seconds: int = 60

    # 和风天气逐日预报的进程内缓存时长，单位为秒。
    weather_cache_ttl_seconds: int = 1800
    # 高德地理编码结果的进程内缓存时长，单位为秒。
    amap_geocode_cache_ttl_seconds: int = 604800
    # 高德驾车路线结果的进程内缓存时长，单位为秒。
    amap_route_cache_ttl_seconds: int = 900
    # 高德 POI 搜索结果的进程内缓存时长，单位为秒。
    amap_poi_cache_ttl_seconds: int = 3600


@lru_cache
def get_settings() -> Settings:
    """返回进程内共享的服务端配置。"""

    return Settings()
