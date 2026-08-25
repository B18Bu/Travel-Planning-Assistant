from datetime import date

import httpx
import pytest

from app.config import Settings
from app.dependencies import build_hotel_search_service
from app.errors import FliggyHotelNotConfigured
from app.main import create_app
from app.models.fliggy_hotel import FliggyHotelSearchRequest

CANONICAL_URL = "https://eco.taobao.com/router/rest"


def test_hotel_settings_have_safe_defaults_and_distinct_ticket_fields():
    settings = Settings(_env_file=None)

    assert settings.fliggy_hotel_enabled is False
    assert settings.fliggy_hotel_app_key == ""
    assert settings.fliggy_hotel_app_secret == ""
    assert settings.fliggy_hotel_sub_channel == ""
    assert settings.fliggy_hotel_api_url == CANONICAL_URL
    assert settings.fliggy_enabled is False


@pytest.mark.parametrize(
    "value",
    [
        "http://eco.taobao.com/router/rest",
        "https://eco.taobao.com/router/rest/",
        "https://evil.example/router/rest",
        "https://eco.taobao.com/other",
    ],
)
def test_hotel_settings_reject_noncanonical_api_url(value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, fliggy_hotel_api_url=value)


def test_build_hotel_search_service_disabled_is_safe_and_never_constructs_client(monkeypatch):
    settings = Settings(_env_file=None)

    class ExplodingClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("未配置时不应构造会发请求的客户端")

    monkeypatch.setattr("app.dependencies.FliggyHotelClient", ExplodingClient)
    service = build_hotel_search_service(settings)

    with pytest.raises(FliggyHotelNotConfigured):
        import asyncio

        asyncio.run(
            service.search(
                FliggyHotelSearchRequest(
                    city_name="杭州",
                    check_in=date(2026, 9, 1),
                    check_out=date(2026, 9, 2),
                    page_no=1,
                    page_size=10,
                ),
                "trace-1",
            )
        )


def test_build_hotel_search_service_with_credentials_builds_hotel_service(monkeypatch):
    settings = Settings(
        _env_file=None,
        fliggy_hotel_enabled=True,
        fliggy_hotel_app_key="app-key",
        fliggy_hotel_app_secret="app-secret",
        fliggy_hotel_sub_channel="channel-1",
    )
    captured = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

    monkeypatch.setattr("app.dependencies.FliggyHotelClient", FakeClient)
    service = build_hotel_search_service(settings)

    assert service.__class__.__name__ == "HotelSearchService"
    assert captured["args"] == ("app-key", "app-secret", "channel-1")
    assert captured["kwargs"]["base_url"] == CANONICAL_URL


def test_create_app_injects_hotel_service_without_replacing_existing_state():
    ticket_service = object()
    orchestrator = object()
    app = create_app(orchestrator=orchestrator, fliggy_ticket_service=ticket_service)

    assert app.state.orchestrator is orchestrator
    assert app.state.fliggy_ticket_service is ticket_service
    assert hasattr(app.state, "fliggy_hotel_service")
    assert isinstance(app.state.fliggy_hotel_service, object)
