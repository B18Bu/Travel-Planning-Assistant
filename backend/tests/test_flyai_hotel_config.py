from datetime import date

import pytest

from app.config import Settings
from app.dependencies import build_flyai_hotel_recommendation_service
from app.errors import FliggyHotelNotConfigured
from app.models.flyai_hotel import FlyAIHotelSearchRequest
from app.services.flyai_hotel_recommendation import FlyAIHotelRecommendationService


def _request() -> FlyAIHotelSearchRequest:
    return FlyAIHotelSearchRequest(
        city_name="杭州",
        check_in=date(2099, 9, 1),
        check_out=date(2099, 9, 2),
    )


def test_flyai_hotel_settings_have_safe_defaults():
    settings = Settings(_env_file=None)

    assert settings.flyai_hotel_enabled is False
    assert settings.flyai_api_key == ""
    assert settings.flyai_cli_command == "flyai"
    assert settings.flyai_cli_timeout_seconds == 20.0
    assert settings.flyai_hotel_limit == 10


@pytest.mark.parametrize(
    "settings_kwargs",
    [
        {},
        {"flyai_hotel_enabled": True},
        {"flyai_hotel_enabled": True, "flyai_api_key": "  "},
    ],
)
def test_build_flyai_recommendation_service_disabled_or_key_missing_is_safe(
    monkeypatch, settings_kwargs
):
    settings = Settings(_env_file=None, **settings_kwargs)

    class ExplodingClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("未配置时不应构造会发请求的客户端")

    monkeypatch.setattr("app.dependencies.FlyAIHotelClient", ExplodingClient)
    monkeypatch.setattr("app.dependencies.AmapClient", ExplodingClient)

    service = build_flyai_hotel_recommendation_service(settings)

    with pytest.raises(FliggyHotelNotConfigured):
        import asyncio

        asyncio.run(service.recommend(_request()))


def test_build_flyai_recommendation_service_with_key_builds_service(monkeypatch):
    settings = Settings(
        _env_file=None,
        flyai_hotel_enabled=True,
        flyai_api_key="test-key",
        flyai_cli_command="flyai",
        flyai_cli_timeout_seconds=15.0,
        flyai_hotel_limit=8,
    )
    captured = {}

    class FakeFlyAIClient:
        def __init__(self, *args, **kwargs):
            captured["flyai_args"] = args
            captured["flyai_kwargs"] = kwargs

    class FakeAmapClient:
        def __init__(self, *args, **kwargs):
            captured["amap_kwargs"] = kwargs

    monkeypatch.setattr("app.dependencies.FlyAIHotelClient", FakeFlyAIClient)
    monkeypatch.setattr("app.dependencies.AmapClient", FakeAmapClient)

    service = build_flyai_hotel_recommendation_service(settings)

    assert isinstance(service, FlyAIHotelRecommendationService)
    assert captured["flyai_args"] == ("test-key",)
    assert captured["flyai_kwargs"]["command"] == "flyai"
    assert captured["flyai_kwargs"]["timeout_seconds"] == 15.0
    assert captured["amap_kwargs"]["base_url"] == "https://restapi.amap.com"
