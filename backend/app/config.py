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

    # 和风天气逐日预报 API 的服务端密钥，默认空值；仅在后端使用，不得暴露。
    heweather_api_key: str = ""
    # 和风天气固定 HTTPS API 域名，默认值仅供后端使用，不接受客户端覆盖。
    heweather_base_url: str = "https://devapi.qweather.com"
    # 高德地理编码、驾车路线和 POI 文本搜索 API 的服务端密钥，默认空值；仅在后端使用，不得暴露。
    amap_api_key: str = ""
    # 高德地图固定 HTTPS API 域名，默认值仅供后端使用，不接受客户端覆盖。
    amap_base_url: str = "https://restapi.amap.com"

    # 所有外部 API HTTP 连接建立超时，默认 3.0 秒；仅由后端控制，不接受客户端覆盖。
    external_connect_timeout_seconds: float = 3.0
    # 所有外部 API HTTP 响应读取超时，默认 8.0 秒；单位为秒，仅由后端控制，不接受客户端覆盖。
    external_read_timeout_seconds: float = 8.0
    # 所有外部 API 单次请求总超时，默认 10.0 秒；单位为秒，仅由后端控制，不接受客户端覆盖。
    external_total_timeout_seconds: float = 10.0
    # 和风天气及高德 API 的最大请求尝试次数，默认 3 次；仅重试受控瞬时错误，仅由后端控制，不接受客户端覆盖。
    external_max_attempts: int = 3
    # 和风天气或高德 API 连续失败的熔断阈值，默认 3 次；仅由后端控制，不接受客户端覆盖。
    circuit_breaker_failure_threshold: int = 3
    # 和风天气或高德 API 熔断保持时长，默认 60 秒；单位为秒，仅由后端控制，不接受客户端覆盖。
    circuit_breaker_open_seconds: int = 60

    # 和风天气逐日预报结果的进程内缓存 TTL，默认 1800 秒；单位为秒，仅由后端控制，不接受客户端覆盖。
    weather_cache_ttl_seconds: int = 1800
    # 高德地理编码结果的进程内缓存 TTL，默认 604800 秒；单位为秒，仅由后端控制，不接受客户端覆盖。
    amap_geocode_cache_ttl_seconds: int = 604800
    # 高德驾车路线结果的进程内缓存 TTL，默认 900 秒；单位为秒，仅由后端控制，不接受客户端覆盖。
    amap_route_cache_ttl_seconds: int = 900
    # 高德 POI 搜索结果的进程内缓存 TTL，默认 3600 秒；单位为秒，仅由后端控制，不接受客户端覆盖。
    amap_poi_cache_ttl_seconds: int = 3600


@lru_cache
def get_settings() -> Settings:
    """返回进程内共享的服务端配置。"""

    return Settings()
