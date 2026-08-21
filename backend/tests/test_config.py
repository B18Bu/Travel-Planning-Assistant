from pathlib import Path

from app.config import Settings


CONFIG_SOURCE = Path(__file__).parents[1] / "app" / "config.py"
ENV_EXAMPLE = Path(__file__).parents[1] / ".env.example"


def test_settings_expose_fixed_service_and_resilience_defaults():
    settings = Settings()

    assert settings.heweather_base_url == "https://devapi.qweather.com"
    assert settings.amap_base_url == "https://restapi.amap.com"
    assert settings.weather_cache_ttl_seconds == 1800
    assert settings.amap_route_cache_ttl_seconds == 900
    assert settings.external_max_attempts == 3
    assert settings.circuit_breaker_open_seconds == 60


def test_runtime_config_documents_api_scope_defaults_units_and_backend_boundary():
    text = CONFIG_SOURCE.read_text(encoding="utf-8")

    required_fragments = [
        "和风天气逐日预报 API",
        "高德地理编码、驾车路线和 POI 文本搜索 API",
        "固定 HTTPS API 域名",
        "单位为秒",
        "默认值",
        "仅在后端使用，不得暴露",
        "仅重试受控瞬时错误",
        "仅由后端控制，不接受客户端覆盖",
    ]
    for fragment in required_fragments:
        assert fragment in text


def test_env_example_documents_each_external_setting_and_never_contains_secret():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")

    for variable in [
        "HEWEATHER_API_KEY",
        "HEWEATHER_BASE_URL",
        "AMAP_API_KEY",
        "AMAP_BASE_URL",
        "EXTERNAL_CONNECT_TIMEOUT_SECONDS",
        "EXTERNAL_READ_TIMEOUT_SECONDS",
        "EXTERNAL_TOTAL_TIMEOUT_SECONDS",
        "EXTERNAL_MAX_ATTEMPTS",
        "CIRCUIT_BREAKER_FAILURE_THRESHOLD",
        "CIRCUIT_BREAKER_OPEN_SECONDS",
        "WEATHER_CACHE_TTL_SECONDS",
        "AMAP_GEOCODE_CACHE_TTL_SECONDS",
        "AMAP_ROUTE_CACHE_TTL_SECONDS",
        "AMAP_POI_CACHE_TTL_SECONDS",
    ]:
        assert variable in text

    assert "单位：秒" in text
    assert "不得提交真实值或暴露到前端" in text
    assert "仅用于后端请求，不允许客户端覆盖" in text
    assert "仅用于受控瞬时错误" in text
