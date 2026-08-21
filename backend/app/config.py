from functools import lru_cache

from pydantic import Field, field_validator
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
    # 和风天气固定 HTTPS API 域名，默认值：https://devapi.qweather.com；仅由后端控制，不接受客户端覆盖。
    heweather_base_url: str = "https://devapi.qweather.com"
    # 高德地理编码、驾车路线和 POI 文本搜索 API 的服务端密钥，默认空值；仅在后端使用，不得暴露。
    amap_api_key: str = ""
    # 高德地图固定 HTTPS API 域名，默认值：https://restapi.amap.com；仅由后端控制，不接受客户端覆盖。
    amap_base_url: str = "https://restapi.amap.com"

    # 所有外部 API HTTP 连接建立超时，单位为秒，默认值：3.0；仅由后端控制，不接受客户端覆盖。
    external_connect_timeout_seconds: float = 3.0
    # 所有外部 API HTTP 响应读取超时，单位为秒，默认值：8.0；仅由后端控制，不接受客户端覆盖。
    external_read_timeout_seconds: float = 8.0
    # 所有外部 API 单次请求总超时，单位为秒，默认值：10.0；仅由后端控制，不接受客户端覆盖。
    external_total_timeout_seconds: float = 10.0
    # 和风天气及高德 API 的最大请求尝试次数，单位为次，默认值：3；仅重试受控瞬时错误；仅由后端控制，不接受客户端覆盖。
    external_max_attempts: int = Field(default=3, ge=1, le=3)
    # 和风天气或高德 API 连续失败的熔断阈值，单位为次，默认值：3；仅由后端控制，不接受客户端覆盖。
    circuit_breaker_failure_threshold: int = Field(default=3, gt=0)
    # 和风天气或高德 API 熔断保持时长，单位为秒，默认值：60；仅由后端控制，不接受客户端覆盖。
    circuit_breaker_open_seconds: int = Field(default=60, gt=0)

    # 和风天气逐日预报结果的进程内缓存 TTL，单位为秒，默认值：1800；仅由后端控制，不接受客户端覆盖。
    weather_cache_ttl_seconds: int = Field(default=1800, gt=0)
    # 高德地理编码结果的进程内缓存 TTL，单位为秒，默认值：604800；仅由后端控制，不接受客户端覆盖。
    amap_geocode_cache_ttl_seconds: int = Field(default=604800, gt=0)
    # 高德驾车路线结果的进程内缓存 TTL，单位为秒，默认值：900；仅由后端控制，不接受客户端覆盖。
    amap_route_cache_ttl_seconds: int = Field(default=900, gt=0)
    # 高德 POI 搜索结果的进程内缓存 TTL，单位为秒，默认值：3600；仅由后端控制，不接受客户端覆盖。
    amap_poi_cache_ttl_seconds: int = Field(default=3600, gt=0)

    @field_validator(
        "external_max_attempts",
        "circuit_breaker_failure_threshold",
        "circuit_breaker_open_seconds",
        "weather_cache_ttl_seconds",
        "amap_geocode_cache_ttl_seconds",
        "amap_route_cache_ttl_seconds",
        "amap_poi_cache_ttl_seconds",
        mode="before",
    )
    @classmethod
    def validate_external_integer_settings(cls, value):
        if isinstance(value, bool):
            raise ValueError("配置必须为整数")
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("配置必须为整数")
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or any(character in stripped for character in ".eE"):
                raise ValueError("配置必须为整数")
            try:
                int(stripped)
            except ValueError as error:
                raise ValueError("配置必须为整数") from error
        return value


@lru_cache
def get_settings() -> Settings:
    """返回进程内共享的服务端配置。"""

    return Settings()
