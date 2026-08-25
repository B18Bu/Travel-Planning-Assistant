from pathlib import Path


ROOT = Path(__file__).parents[2]
README = ROOT / "README.md"


def read_readme() -> str:
    return README.read_text(encoding="utf-8")


def test_readme_covers_scope_architecture_and_module_flow():
    text = read_readme()
    required_fragments = [
        "项目背景与目标", "非目标", "用户流程", "总体架构", "天气 Agent", "路线 Agent",
        "住宿 Agent", "餐饮 Agent", "汇总 Agent", "编排器", "API 层", "前端", "和风天气", "高德地图",
    ]
    for fragment in required_fragments:
        assert fragment in text
    assert "```text" in text or "```ascii" in text


def test_readme_documents_real_api_contract_and_status_semantics():
    text = read_readme()
    required_fragments = [
        "POST /api/travel-plans", "GET /api/health", "GET /api/ready", "geocode/geo", "direction/driving",
        "v5/place/text", "region", "city_limit", "request_id", "trace_id", "success", "partial", "degraded",
        "failed", "retrieved_at", "source_updated_at", "422", "500",
    ]
    for fragment in required_fragments:
        assert fragment in text


def test_readme_documents_security_frontend_and_non_transactional_boundary():
    text = read_readme()
    required_fragments = [
        "price", "inventory", "availability", "queue", "discount", "rating", "order_url", "密钥不提交",
        "marked", "DOMPurify", "FORBID_TAGS", "FORBID_ATTR", "XSS", "双栏", "知识库", "OTA", "交易",
    ]
    for fragment in required_fragments:
        assert fragment in text


def test_readme_documents_config_defaults_startup_operations_and_production_followups():
    text = read_readme()
    required_fragments = [
        "APP_ENV", "ALLOWED_ORIGINS", "HEWEATHER_API_KEY", "HEWEATHER_BASE_URL", "AMAP_API_KEY", "AMAP_BASE_URL",
        "EXTERNAL_CONNECT_TIMEOUT_SECONDS", "EXTERNAL_READ_TIMEOUT_SECONDS", "EXTERNAL_TOTAL_TIMEOUT_SECONDS",
        "EXTERNAL_MAX_ATTEMPTS", "CIRCUIT_BREAKER_FAILURE_THRESHOLD", "CIRCUIT_BREAKER_OPEN_SECONDS",
        "WEATHER_CACHE_TTL_SECONDS", "AMAP_GEOCODE_CACHE_TTL_SECONDS", "AMAP_ROUTE_CACHE_TTL_SECONDS",
        "AMAP_POI_CACHE_TTL_SECONDS", "PowerShell", "PYTHONPATH", "uvicorn", "http://127.0.0.1:8000", "pytest",
        "single-flight", "连接池", "缓存淘汰", "超时预算", "限流", "认证", "审计", "ready", "health",
    ]
    for fragment in required_fragments:
        assert fragment in text


def test_readme_shows_api_examples_without_claiming_frontend_displays_raw_json():
    text = read_readme()
    assert "请求示例" in text
    assert "响应示例" in text
    assert '"origin": "上海"' in text
    assert '"status": "success"' in text
    assert "页面不展示 JSON 源码" in text


def test_readme_describes_ticket_query_as_read_only():
    text = read_readme()
    assert "门票查询" in text
    assert "不创建订单" in text
    assert "不处理支付" in text



def test_registry_documents_flyai_ticket_read_only_boundary():
    registry = ROOT / "docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md"
    text = registry.read_text(encoding="utf-8")
    assert "Quickstart" in text
    assert "FLYAI_API_KEY" in text
    assert "ai-search" in text
    assert "flyai_text" in text
    assert "不解析价格" in text or "结构化价格" in text
    assert "不解析库存" in text or "结构化库存" in text


def test_readme_documents_flyai_ticket_read_only():
    text = read_readme()
    assert "FlyAI" in text
    assert "FLIGGY_TICKET_PROVIDER" in text
