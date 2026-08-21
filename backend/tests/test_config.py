from pathlib import Path

import pytest

from app.config import Settings


CONFIG_SOURCE = Path(__file__).parents[1] / "app" / "config.py"
ENV_EXAMPLE = Path(__file__).parents[1] / ".env.example"


def test_settings_expose_fixed_service_and_resilience_defaults():
    settings = Settings()

    expected_defaults = {
        "heweather_base_url": "https://devapi.qweather.com",
        "amap_base_url": "https://restapi.amap.com",
        "external_connect_timeout_seconds": 3.0,
        "external_read_timeout_seconds": 8.0,
        "external_total_timeout_seconds": 10.0,
        "external_max_attempts": 3,
        "circuit_breaker_failure_threshold": 3,
        "circuit_breaker_open_seconds": 60,
        "weather_cache_ttl_seconds": 1800,
        "amap_geocode_cache_ttl_seconds": 604800,
        "amap_route_cache_ttl_seconds": 900,
        "amap_poi_cache_ttl_seconds": 3600,
    }

    for field, expected in expected_defaults.items():
        assert getattr(settings, field) == expected


def test_env_example_parses_external_defaults_without_real_keys(monkeypatch):
    env_names = [
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
    ]
    for name in env_names:
        monkeypatch.delenv(name, raising=False)

    defaults = Settings(_env_file=None)
    parsed = Settings(_env_file=ENV_EXAMPLE)

    fields = [
        "heweather_base_url",
        "amap_base_url",
        "external_connect_timeout_seconds",
        "external_read_timeout_seconds",
        "external_total_timeout_seconds",
        "external_max_attempts",
        "circuit_breaker_failure_threshold",
        "circuit_breaker_open_seconds",
        "weather_cache_ttl_seconds",
        "amap_geocode_cache_ttl_seconds",
        "amap_route_cache_ttl_seconds",
        "amap_poi_cache_ttl_seconds",
    ]
    for field in fields:
        assert getattr(parsed, field) == getattr(defaults, field)
        assert type(getattr(parsed, field)) is type(getattr(defaults, field))

    assert parsed.heweather_api_key == ""
    assert parsed.amap_api_key == ""


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
    assert "仅后端控制，客户端不可覆盖" in text
    assert "仅用于受控瞬时错误" in text


def _comment_before_field(text: str, field: str) -> str:
    lines = text.splitlines()
    index = next(index for index, line in enumerate(lines) if field in line)
    comments = []
    index -= 1
    while index >= 0 and lines[index].lstrip().startswith("#"):
        comments.append(lines[index])
        index -= 1
    return "\n".join(reversed(comments))


CONFIG_FIELD_DOCUMENTATION = {
    "heweather_base_url": ["https://devapi.qweather.com", "和风天气", "仅由后端控制，不接受客户端覆盖"],
    "amap_base_url": ["https://restapi.amap.com", "高德", "仅由后端控制，不接受客户端覆盖"],
    "external_connect_timeout_seconds": ["单位为秒，默认值：3.0", "所有外部 API", "仅由后端控制，不接受客户端覆盖"],
    "external_read_timeout_seconds": ["单位为秒，默认值：8.0", "所有外部 API", "仅由后端控制，不接受客户端覆盖"],
    "external_total_timeout_seconds": ["单位为秒，默认值：10.0", "所有外部 API", "仅由后端控制，不接受客户端覆盖"],
    "external_max_attempts": ["单位为次，默认值：3", "和风天气及高德 API", "仅由后端控制，不接受客户端覆盖"],
    "circuit_breaker_failure_threshold": ["单位为次，默认值：3", "和风天气或高德 API", "仅由后端控制，不接受客户端覆盖"],
    "circuit_breaker_open_seconds": ["单位为秒，默认值：60", "和风天气或高德 API", "仅由后端控制，不接受客户端覆盖"],
    "weather_cache_ttl_seconds": ["单位为秒，默认值：1800", "和风天气逐日预报", "仅由后端控制，不接受客户端覆盖"],
    "amap_geocode_cache_ttl_seconds": ["单位为秒，默认值：604800", "高德地理编码", "仅由后端控制，不接受客户端覆盖"],
    "amap_route_cache_ttl_seconds": ["单位为秒，默认值：900", "高德驾车路线", "仅由后端控制，不接受客户端覆盖"],
    "amap_poi_cache_ttl_seconds": ["单位为秒，默认值：3600", "高德 POI", "仅由后端控制，不接受客户端覆盖"],
}


ENV_FIELD_DOCUMENTATION = {
    "HEWEATHER_BASE_URL": ["https://devapi.qweather.com", "和风天气", "仅后端控制，客户端不可覆盖"],
    "AMAP_BASE_URL": ["https://restapi.amap.com", "高德", "仅后端控制，客户端不可覆盖"],
    "EXTERNAL_CONNECT_TIMEOUT_SECONDS": ["单位：秒，默认值：3.0", "所有外部 API", "仅后端控制，客户端不可覆盖"],
    "EXTERNAL_READ_TIMEOUT_SECONDS": ["单位：秒，默认值：8.0", "所有外部 API", "仅后端控制，客户端不可覆盖"],
    "EXTERNAL_TOTAL_TIMEOUT_SECONDS": ["单位：秒，默认值：10.0", "所有外部 API", "仅后端控制，客户端不可覆盖"],
    "EXTERNAL_MAX_ATTEMPTS": ["单位：次，默认值：3", "和风天气及高德 API", "仅后端控制，客户端不可覆盖"],
    "CIRCUIT_BREAKER_FAILURE_THRESHOLD": ["单位：次，默认值：3", "和风天气或高德 API", "仅后端控制，客户端不可覆盖"],
    "CIRCUIT_BREAKER_OPEN_SECONDS": ["单位：秒，默认值：60", "和风天气或高德 API", "仅后端控制，客户端不可覆盖"],
    "WEATHER_CACHE_TTL_SECONDS": ["单位：秒，默认值：1800", "和风天气逐日预报", "仅后端控制，客户端不可覆盖"],
    "AMAP_GEOCODE_CACHE_TTL_SECONDS": ["单位：秒，默认值：604800", "高德地理编码", "仅后端控制，客户端不可覆盖"],
    "AMAP_ROUTE_CACHE_TTL_SECONDS": ["单位：秒，默认值：900", "高德驾车路线", "仅后端控制，客户端不可覆盖"],
    "AMAP_POI_CACHE_TTL_SECONDS": ["单位：秒，默认值：3600", "高德 POI", "仅后端控制，客户端不可覆盖"],
}


@pytest.mark.parametrize("field, required_fragments", CONFIG_FIELD_DOCUMENTATION.items())
def test_each_runtime_config_field_has_adjacent_documentation(field, required_fragments):
    comment = _comment_before_field(CONFIG_SOURCE.read_text(encoding="utf-8"), field)

    for fragment in required_fragments:
        assert fragment in comment, f"{field} 缺少相邻说明：{fragment}"


@pytest.mark.parametrize("field, required_fragments", ENV_FIELD_DOCUMENTATION.items())
def test_each_env_config_field_has_adjacent_documentation(field, required_fragments):
    comment = _comment_before_field(ENV_EXAMPLE.read_text(encoding="utf-8"), field)

    for fragment in required_fragments:
        assert fragment in comment, f"{field} 缺少相邻说明：{fragment}"
