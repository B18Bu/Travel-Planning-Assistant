from datetime import date, datetime, timezone

import httpx
import pytest
import respx

from app.services.cache import MemoryCache
from app.services.resilience import CircuitBreaker, ExternalServiceUnavailable
from app.services.heweather import HeWeatherClient


BASE = "https://weather.test"


def client(**kwargs):
    options = {
        "api_key": "weather-key",
        "base_url": BASE,
        "cache": MemoryCache(),
        "breaker": CircuitBreaker(failure_threshold=3, open_seconds=60),
        "max_attempts": 3,
        "cache_ttl_seconds": 1800,
        "timeout": httpx.Timeout(2.0),
    }
    options.update(kwargs)
    return HeWeatherClient(**options)


@respx.mock
@pytest.mark.asyncio
async def test_maps_forecast_and_uses_fixed_endpoint_and_params():
    route = respx.get(f"{BASE}/v7/weather/3d").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "200",
                "updateTime": "2026-08-20T10:00:00+08:00",
                "daily": [
                    {"fxDate": "2026-09-01", "textDay": "小雨", "tempMin": "21", "tempMax": "28"},
                    {"fxDate": "2026-09-02", "textDay": "晴", "tempMin": "22", "tempMax": "29"},
                ],
            },
        )
    )

    result = await client().daily_forecast("101270101", date(2026, 9, 1), 1)

    assert route.call_count == 1
    assert route.calls[0].request.url.params["location"] == "101270101"
    assert route.calls[0].request.url.params["key"] == "weather-key"
    assert set(result) == {"data_status", "source_updated_at", "retrieved_at", "daily"}
    assert result["data_status"] == "realtime"
    assert result["source_updated_at"].tzinfo is not None
    assert result["retrieved_at"].tzinfo == timezone.utc
    assert result["daily"] == ({"date": date(2026, 9, 1), "condition": "小雨", "temp_min": 21, "temp_max": 28},)


@respx.mock
@pytest.mark.asyncio
async def test_cache_hit_calls_route_once_and_marks_cached_with_new_retrieved_at():
    route = respx.get(f"{BASE}/v7/weather/3d").mock(
        return_value=httpx.Response(
            200,
            json={"code": "200", "updateTime": "2026-08-20T10:00:00+08:00", "daily": [{"fxDate": "2026-09-01", "textDay": "晴", "tempMin": "20", "tempMax": "28"}]},
        )
    )
    weather_client = client()

    first = await weather_client.daily_forecast("city", date(2026, 9, 1), 3)
    second = await weather_client.daily_forecast("city", date(2026, 9, 1), 3)

    assert route.call_count == 1
    assert first["data_status"] == "realtime"
    assert second["data_status"] == "cached"
    assert second["source_updated_at"] == first["source_updated_at"]
    assert second["retrieved_at"] >= first["retrieved_at"]


@pytest.mark.asyncio
async def test_empty_key_fails_before_http():
    weather_client = client(api_key="")

    with pytest.raises(ExternalServiceUnavailable) as exc_info:
        await weather_client.daily_forecast("city", date(2026, 9, 1), 3)

    assert str(exc_info.value) == "和风天气 API 密钥未配置"


@respx.mock
@pytest.mark.asyncio
async def test_non_200_weather_code_is_controlled_error():
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={"code": "401"}))

    with pytest.raises(ExternalServiceUnavailable) as exc_info:
        await client().daily_forecast("city", date(2026, 9, 1), 3)

    assert str(exc_info.value) == "和风天气未返回有效数据"


@respx.mock
@pytest.mark.asyncio
async def test_429_is_retried_and_success_records_success(monkeypatch):
    route = respx.get(f"{BASE}/v7/weather/3d").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, json={"code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [{"fxDate": "2026-09-01", "textDay": "晴", "tempMin": "20", "tempMax": "28"}]}),
        ]
    )
    async def immediate(_delay):
        return None

    monkeypatch.setattr("app.services.resilience.asyncio.sleep", immediate)

    result = await client().daily_forecast("city", date(2026, 9, 1), 3)

    assert route.call_count == 2
    assert result["data_status"] == "realtime"


@pytest.mark.asyncio
async def test_open_breaker_fails_without_http(monkeypatch):
    breaker = CircuitBreaker(failure_threshold=1, open_seconds=60)
    breaker.record_failure()
    weather_client = client(breaker=breaker)

    called = False

    async def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("不应发 HTTP")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail_if_called)

    with pytest.raises(ExternalServiceUnavailable, match="外部服务熔断中"):
        await weather_client.daily_forecast("city", date(2026, 9, 1), 3)
    assert called is False


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("private-url"), httpx.ConnectError("private-host")])
@respx.mock
@pytest.mark.asyncio
async def test_transport_failures_are_retried_then_controlled(failure):
    route = respx.get(f"{BASE}/v7/weather/3d").mock(side_effect=failure)
    weather_client = client(max_attempts=2)

    with pytest.raises(ExternalServiceUnavailable) as exc_info:
        await weather_client.daily_forecast("secret-location", date(2026, 9, 1), 3)

    assert route.call_count == 2
    assert str(exc_info.value) == "外部服务暂不可用"
    assert all(value not in str(exc_info.value) for value in ("secret-location", BASE, "private"))
    assert weather_client.breaker.failure_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_429_exhaustion_records_failure_without_upstream_body():
    route = respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(429, text="secret body"))
    weather_client = client(max_attempts=2)

    with pytest.raises(ExternalServiceUnavailable) as exc_info:
        await weather_client.daily_forecast("secret-location", date(2026, 9, 1), 3)

    assert route.call_count == 2
    assert str(exc_info.value) == "外部服务暂不可用"
    assert "secret" not in str(exc_info.value)
    assert weather_client.breaker.failure_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_5xx_exhaustion_records_failure_without_upstream_body():
    route = respx.get(f"{BASE}/v7/weather/3d").mock(
        return_value=httpx.Response(503, text="secret upstream body")
    )
    weather_client = client(max_attempts=2)

    with pytest.raises(ExternalServiceUnavailable) as exc_info:
        await weather_client.daily_forecast("secret-location", date(2026, 9, 1), 3)

    assert route.call_count == 2
    assert str(exc_info.value) == "外部服务暂不可用"
    assert "secret" not in str(exc_info.value)
    assert weather_client.breaker.failure_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_non_429_4xx_is_single_request_and_controlled():
    route = respx.get(f"{BASE}/v7/weather/3d").mock(
        return_value=httpx.Response(400, text="https://private.example?key=secret")
    )

    with pytest.raises(ExternalServiceUnavailable) as exc_info:
        await client().daily_forecast("secret-location", date(2026, 9, 1), 3)

    assert route.call_count == 1
    assert str(exc_info.value) == "和风天气未返回有效数据"
    assert all(value not in str(exc_info.value) for value in ("secret", "private", BASE, "secret-location"))


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "200", "updateTime": "2026-08-20T10:00:00Z"},
        {"code": "200", "daily": []},
        {"code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [{"fxDate": "2026-09-01", "textDay": "雨", "tempMin": "坏", "tempMax": "20"}]},
    ],
)
@respx.mock
@pytest.mark.asyncio
async def test_invalid_weather_structure_is_controlled(payload):
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json=payload))

    with pytest.raises(ExternalServiceUnavailable) as exc_info:
        await client().daily_forecast("secret-location", date(2026, 9, 1), 3)

    assert str(exc_info.value) == "和风天气未返回有效数据"
    assert all(value not in str(exc_info.value) for value in ("secret-location", BASE, "坏"))
