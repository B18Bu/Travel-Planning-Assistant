from pathlib import Path

import pytest

from app.config import Settings


CONFIG_SOURCE = Path(__file__).parents[1] / "app" / "config.py"
ENV_EXAMPLE = Path(__file__).parents[1] / ".env.example"


def test_settings_expose_fixed_service_and_resilience_defaults():
    settings = Settings()

    expected_defaults = {
        "heweather_base_url": "https://pb5ctx5qqr.re.qweatherapi.com",
        "amap_base_url": "https://restapi.amap.com",
        "deepseek_base_url": "https://api.deepseek.com",
        "deepseek_timeout_seconds": 60.0,
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


@pytest.mark.parametrize("field", [
    "weather_cache_ttl_seconds",
    "amap_geocode_cache_ttl_seconds",
    "amap_route_cache_ttl_seconds",
    "amap_poi_cache_ttl_seconds",
    "circuit_breaker_failure_threshold",
    "circuit_breaker_open_seconds",
])
@pytest.mark.parametrize("value", [0, -1, True, False, "1.2", 1.2, "not-a-number"])
def test_settings_rejects_non_positive_integer_ttls_and_breaker_values(field, value):
    with pytest.raises(ValueError):
        Settings(**{field: value})


@pytest.mark.parametrize("value", [0, -1, 4, True, False, "1.2", 1.2, "not-a-number"])
def test_settings_rejects_invalid_external_max_attempts(value):
    with pytest.raises(ValueError):
        Settings(external_max_attempts=value)


def test_settings_accepts_dotenv_integer_strings():
    settings = Settings(
        external_max_attempts="3",
        circuit_breaker_failure_threshold="3",
        circuit_breaker_open_seconds="60",
        weather_cache_ttl_seconds="1800",
        amap_geocode_cache_ttl_seconds="604800",
        amap_route_cache_ttl_seconds="900",
        amap_poi_cache_ttl_seconds="3600",
    )
    assert settings.external_max_attempts == 3
    assert settings.weather_cache_ttl_seconds == 1800


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
        "DOCUMENT_BATCH_MAX_FILES",
        "KNOWLEDGE_SEARCH_RESULT_LIMIT",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_MAX_TOKENS",
        "DEEPSEEK_TIMEOUT_SECONDS",
    ]
    for name in env_names:
        monkeypatch.delenv(name, raising=False)

    defaults = Settings(_env_file=None)
    parsed = Settings(_env_file=ENV_EXAMPLE)

    fields = [
        "heweather_base_url",
        "amap_base_url",
        "deepseek_base_url",
        "deepseek_model",
        "deepseek_timeout_seconds",
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
        "document_batch_max_files",
        "knowledge_search_result_limit",
    ]
    for field in fields:
        assert getattr(parsed, field) == getattr(defaults, field)
        assert type(getattr(parsed, field)) is type(getattr(defaults, field))

    assert parsed.heweather_api_key == ""
    assert parsed.amap_api_key == ""
    assert parsed.document_batch_max_files == 10
    assert parsed.knowledge_search_result_limit == 12
    assert Path(parsed.document_data_dir).is_absolute()
    assert Path(parsed.document_data_dir).resolve() == (Path(__file__).parents[1] / "data").resolve()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mineru_base_url", "http://mineru.net"),
        ("mineru_base_url", "https://evil.example"),
        ("mineru_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ("qwen_vl_base_url", "http://dashscope.aliyuncs.com/compatible-mode/v1"),
        ("qwen_vl_base_url", "https://evil.example/compatible-mode/v1"),
        ("qwen_vl_base_url", "https://mineru.net"),
        ("deepseek_base_url", "http://api.deepseek.com"),
        ("deepseek_base_url", "https://api.deepseek.com/"),
        ("deepseek_base_url", "https://evil.example"),
    ],
)
def test_settings_reject_noncanonical_external_service_base_urls(field, value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field: value})


def test_document_settings_are_backend_only_and_have_safe_defaults():
    settings = Settings(_env_file=None)

    assert Path(settings.document_data_dir).is_absolute()
    assert Path(settings.document_data_dir).resolve() == (Path(__file__).parents[1] / "data").resolve()
    assert settings.document_max_upload_bytes == 20 * 1024 * 1024
    assert 0 < settings.document_max_upload_bytes <= 100 * 1024 * 1024
    assert settings.document_batch_max_files == 10
    assert 1 <= settings.document_batch_max_files <= 20
    assert settings.knowledge_search_result_limit == 12
    assert 1 <= settings.knowledge_search_result_limit <= 50
    assert settings.chroma_collection_name == "travel_documents"
    assert settings.mineru_api_key == ""
    assert settings.mineru_base_url == "https://mineru.net"
    assert settings.qwen_vl_api_key == ""
    assert settings.qwen_vl_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert settings.qwen_vl_model == "qwen-vl-max"
    assert settings.bge_model_path == r"D:\作业\model\bge-small-zh-v1.5"
    assert settings.deepseek_api_key == ""
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.deepseek_model == "deepseek-chat"
    assert settings.deepseek_max_tokens == 2000
    assert settings.deepseek_timeout_seconds == 60.0


@pytest.mark.parametrize("value", [0, -1, 100 * 1024 * 1024 + 1, True, False, "1.2", 1.2, "not-a-number"])
def test_settings_rejects_invalid_document_upload_size(value):
    with pytest.raises(ValueError):
        Settings(document_max_upload_bytes=value)


@pytest.mark.parametrize("value", [0, -1, 21, True, False, "1.2", 1.2, "not-a-number"])
def test_settings_rejects_invalid_document_batch_max_files(value):
    with pytest.raises(ValueError):
        Settings(document_batch_max_files=value)


@pytest.mark.parametrize("value", [0, -1, 51, True, False, "1.2", 1.2, "not-a-number"])
def test_settings_rejects_invalid_knowledge_search_result_limit(value):
    with pytest.raises(ValueError):
        Settings(knowledge_search_result_limit=value)


def test_settings_accepts_knowledge_search_result_limit_from_dotenv_string():
    assert Settings(_env_file=None, knowledge_search_result_limit="36").knowledge_search_result_limit == 36


@pytest.mark.parametrize("value", [0, 255, 8193, True, False, "1.2", 1.2, "not-a-number"])
def test_settings_rejects_invalid_deepseek_max_tokens(value):
    with pytest.raises(ValueError):
        Settings(deepseek_max_tokens=value)


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
        "DOCUMENT_BATCH_MAX_FILES",
        "KNOWLEDGE_SEARCH_RESULT_LIMIT",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_MAX_TOKENS",
        "DEEPSEEK_TIMEOUT_SECONDS",
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
    "heweather_base_url": ["https://pb5ctx5qqr.re.qweatherapi.com", "和风天气", "仅由后端控制，不接受客户端覆盖"],
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
    "knowledge_search_result_limit": ["默认值：12，范围：1—50", "知识检索", "仅由后端控制，不接受客户端覆盖"],
    "deepseek_base_url": ["https://api.deepseek.com", "DeepSeek", "仅由后端控制，不接受客户端覆盖"],
    "deepseek_model": ["deepseek-chat", "DeepSeek", "仅由后端控制，不接受客户端覆盖"],
    "deepseek_max_tokens": ["默认值：2000", "DeepSeek", "仅由后端控制，不接受客户端覆盖"],
    "deepseek_timeout_seconds": ["单位为秒，默认值：60.0", "DeepSeek", "仅由后端控制，不接受客户端覆盖"],
}


ENV_FIELD_DOCUMENTATION = {
    "HEWEATHER_BASE_URL": ["https://pb5ctx5qqr.re.qweatherapi.com", "和风天气", "仅后端控制，客户端不可覆盖"],
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
    "KNOWLEDGE_SEARCH_RESULT_LIMIT": ["默认值：12，范围：1—50", "知识检索", "仅后端控制，客户端不可覆盖"],
    "DEEPSEEK_BASE_URL": ["https://api.deepseek.com", "DeepSeek", "仅后端控制，客户端不可覆盖"],
    "DEEPSEEK_MODEL": ["deepseek-chat", "DeepSeek", "仅后端控制，客户端不可覆盖"],
    "DEEPSEEK_MAX_TOKENS": ["默认值：2000", "DeepSeek", "仅后端控制，客户端不可覆盖"],
    "DEEPSEEK_TIMEOUT_SECONDS": ["单位：秒，默认值：60.0", "DeepSeek", "仅后端控制，客户端不可覆盖"],
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
