from app.config import Settings


def test_settings_expose_fixed_service_and_resilience_defaults():
    settings = Settings()

    assert settings.heweather_base_url == "https://devapi.qweather.com"
    assert settings.amap_base_url == "https://restapi.amap.com"
    assert settings.weather_cache_ttl_seconds == 1800
    assert settings.amap_route_cache_ttl_seconds == 900
    assert settings.external_max_attempts == 3
    assert settings.circuit_breaker_open_seconds == 60
