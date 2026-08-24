from datetime import date, datetime, timezone

import httpx
import pytest
import respx

from app.services.cache import MemoryCache
from app.services.resilience import CircuitBreaker, ExternalServiceUnavailable
from app.services.heweather import HeWeatherClient


BASE = "https://pb5ctx5qqr.re.qweatherapi.com"


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


@pytest.mark.parametrize("bad_url", [
    "http://evil.test",
    "https://evil.test",
    "https://pb5ctx5qqr.re.qweatherapi.com/",
    "https://pb5ctx5qqr.re.qweatherapi.com/path",
    "https://pb5ctx5qqr.re.qweatherapi.com?x=1",
    "https://pb5ctx5qqr.re.qweatherapi.com#frag",
    "https://user@pb5ctx5qqr.re.qweatherapi.com",
    "https://pb5ctx5qqr.re.qweatherapi.com:443",
    "https://PB5CTX5QQR.RE.QWEATHERAPI.COM",
])
def test_rejects_noncanonical_weather_base_url(bad_url):
    with pytest.raises(ExternalServiceUnavailable, match="和风天气服务地址不受支持"):
        client(base_url=bad_url)


@pytest.mark.parametrize("attempts", [1, 2, 3])
def test_accepts_weather_attempt_count_bounds(attempts):
    assert client(max_attempts=attempts).max_attempts == attempts


@pytest.mark.parametrize("attempts", [0, 4, True, False])
def test_rejects_weather_attempt_count_out_of_range(attempts):
    with pytest.raises(ValueError):
        client(max_attempts=attempts)


@respx.mock
@pytest.mark.asyncio
async def test_weather_filters_before_start_and_limits_to_three_days():
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [
            {"fxDate": "2026-08-31", "textDay": "旧", "tempMin": "1", "tempMax": "2"},
            *[{"fxDate": f"2026-09-0{i}", "textDay": "晴", "tempMin": "20", "tempMax": "28"} for i in range(1, 6)],
        ],
    }))
    result = await client().daily_forecast("city", date(2026, 9, 1), 9)
    assert [item["date"] for item in result["daily"]] == [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]


@respx.mock
@pytest.mark.asyncio
async def test_weather_without_matching_start_date_is_controlled():
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [{"fxDate": "2026-08-31", "textDay": "旧"}],
    }))
    with pytest.raises(ExternalServiceUnavailable, match="和风天气未返回有效数据"):
        await client().daily_forecast("city", date(2026, 9, 1), 1)


@respx.mock
@pytest.mark.asyncio
async def test_weather_matching_days_are_returned_in_date_order():
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [
            {"fxDate": "2026-09-03", "textDay": "三", "tempMin": "20", "tempMax": "28"},
            {"fxDate": "2026-09-01", "textDay": "一", "tempMin": "20", "tempMax": "28"},
            {"fxDate": "2026-09-02", "textDay": "二", "tempMin": "20", "tempMax": "28"},
        ],
    }))
    result = await client().daily_forecast("city", date(2026, 9, 1), 3)
    assert [item["date"] for item in result["daily"]] == [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]


@respx.mock
@pytest.mark.asyncio
async def test_weather_days_three_and_nine_share_effective_cache_key():
    route = respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [
            {"fxDate": "2026-09-01", "textDay": "晴", "tempMin": "20", "tempMax": "28"},
            {"fxDate": "2026-09-02", "textDay": "晴", "tempMin": "20", "tempMax": "28"},
            {"fxDate": "2026-09-03", "textDay": "晴", "tempMin": "20", "tempMax": "28"},
        ],
    }))
    weather_client = client()
    first = await weather_client.daily_forecast("city", date(2026, 9, 1), 3)
    second = await weather_client.daily_forecast("city", date(2026, 9, 1), 9)
    assert route.call_count == 1
    assert first["daily"] == second["daily"]
    assert second["data_status"] == "cached"


@pytest.mark.parametrize("payload", [None, [], "bad"])
@respx.mock
@pytest.mark.asyncio
async def test_weather_top_level_non_dict_is_controlled(payload):
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(ExternalServiceUnavailable, match="和风天气未返回有效数据"):
        await client().daily_forecast("city", date(2026, 9, 1), 1)


@pytest.mark.parametrize("daily", [{}, [None], ["bad"]])
@respx.mock
@pytest.mark.asyncio
async def test_weather_daily_structure_types_are_controlled(daily):
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": daily,
    }))
    with pytest.raises(ExternalServiceUnavailable, match="和风天气未返回有效数据"):
        await client().daily_forecast("city", date(2026, 9, 1), 1)


@pytest.mark.parametrize("days", [0, -1])
@pytest.mark.asyncio
async def test_weather_non_positive_days_are_controlled(days):
    with pytest.raises(ExternalServiceUnavailable, match="和风天气请求天数无效"):
        await client().daily_forecast("city", date(2026, 9, 1), days)


@pytest.mark.parametrize("bad_start", [None, "2026-09-01", datetime(2026, 9, 1)])
@pytest.mark.asyncio
async def test_weather_start_must_be_exact_date(bad_start):
    with pytest.raises(ExternalServiceUnavailable, match="和风天气请求日期无效"):
        await client().daily_forecast("city", bad_start, 1)


@respx.mock
@pytest.mark.asyncio
async def test_weather_cache_key_isolated_by_api_key():
    route = respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [{"fxDate": "2026-09-01", "textDay": "晴", "tempMin": "20", "tempMax": "28"}],
    }))
    cache = MemoryCache()
    await client(cache=cache, api_key="key-one").daily_forecast("city", date(2026, 9, 1), 1)
    await client(cache=cache, api_key="key-two").daily_forecast("city", date(2026, 9, 1), 1)
    assert route.call_count == 2
    assert len(cache._entries) == 2


@respx.mock
@pytest.mark.asyncio
async def test_weather_valid_key_preheat_does_not_allow_empty_key_cache_hit():
    route = respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [{"fxDate": "2026-09-01", "textDay": "晴", "tempMin": "20", "tempMax": "28"}],
    }))
    cache = MemoryCache()
    await client(cache=cache, api_key="key-one").daily_forecast("city", date(2026, 9, 1), 1)
    with pytest.raises(ExternalServiceUnavailable, match="API 密钥"):
        await client(cache=cache, api_key="").daily_forecast("city", date(2026, 9, 1), 1)
    assert route.call_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_weather_effective_cache_key_avoids_days_alias():
    route = respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [{"fxDate": "2026-09-01", "textDay": "晴", "tempMin": "20", "tempMax": "28"}],
    }))
    cache = MemoryCache()
    await client(cache=cache).daily_forecast("city", date(2026, 9, 1), 3)
    await client(cache=cache).daily_forecast("city", date(2026, 9, 1), 9)
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_weather_structured_cache_key_avoids_colon_collision():
    cache = MemoryCache()
    weather_client = client(cache=cache)
    key_one = weather_client._cache_key("a", date(2026, 9, 1), 1)
    key_two = weather_client._cache_key("a:2026-09-01", date(2026, 9, 1), 1)
    assert key_one != key_two
    assert "weather-key" not in key_one


@respx.mock
@pytest.mark.asyncio
async def test_weather_success_clears_prior_breaker_failure():
    breaker = CircuitBreaker(failure_threshold=2, open_seconds=60)
    breaker.record_failure()
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [
            {"fxDate": "2026-09-01", "textDay": "晴", "tempMin": "20", "tempMax": "28"},
        ],
    }))
    weather_client = client(breaker=breaker)

    await weather_client.daily_forecast("city", date(2026, 9, 1), 1)

    assert breaker.failure_count == 0
    breaker.ensure_available()


@pytest.mark.parametrize("condition", ["", [], {}, True, 1])
@respx.mock
@pytest.mark.asyncio
async def test_weather_condition_must_be_non_empty_string(condition):
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [
            {"fxDate": "2026-09-01", "textDay": condition, "tempMin": "20", "tempMax": "28"},
        ],
    }))
    weather_client = client()
    with pytest.raises(ExternalServiceUnavailable, match="和风天气未返回有效数据"):
        await weather_client.daily_forecast("city", date(2026, 9, 1), 1)
    assert weather_client.breaker.failure_count == 1


@pytest.mark.parametrize("field", ["tempMin", "tempMax"])
@pytest.mark.parametrize("value", [True, False, [], {}, "", "1.2", "坏"])
@respx.mock
@pytest.mark.asyncio
async def test_weather_temperature_rejects_non_integer_values(field, value):
    item = {"fxDate": "2026-09-01", "textDay": "晴", "tempMin": "20", "tempMax": "28"}
    item[field] = value
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [item],
    }))
    weather_client = client()
    with pytest.raises(ExternalServiceUnavailable, match="和风天气未返回有效数据"):
        await weather_client.daily_forecast("city", date(2026, 9, 1), 1)
    assert weather_client.breaker.failure_count == 1


@pytest.mark.parametrize("value", [None, 20, "20", -3, "-3"])
@respx.mock
@pytest.mark.asyncio
async def test_weather_temperature_accepts_none_or_integer_values(value):
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [{
            "fxDate": "2026-09-01", "textDay": "晴", "tempMin": value, "tempMax": value,
        }],
    }))
    result = await client().daily_forecast("city", date(2026, 9, 1), 1)
    assert result["daily"][0]["temp_min"] == value if isinstance(value, int) or value is None else int(value)


@pytest.mark.parametrize("update_time", [None, "bad-time"])
@respx.mock
@pytest.mark.asyncio
async def test_weather_missing_or_invalid_update_time_keeps_valid_daily_success(update_time):
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": update_time,
        "daily": [{"fxDate": "2026-09-01", "textDay": "晴", "tempMin": "20", "tempMax": "28"}],
    }))

    result = await client().daily_forecast("city", date(2026, 9, 1), 1)

    assert result["source_updated_at"] is None
    assert result["retrieved_at"].tzinfo == timezone.utc


@pytest.mark.parametrize("ttl", [0, -1, True, False])
def test_weather_rejects_non_positive_cache_ttl(ttl):
    with pytest.raises(ValueError):
        client(cache_ttl_seconds=ttl)


@respx.mock
@pytest.mark.asyncio
async def test_weather_realtime_and_cached_results_do_not_share_daily_items():
    cache = MemoryCache()
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": "2026-08-20T10:00:00Z",
        "daily": [{"fxDate": "2026-09-01", "textDay": "晴", "tempMin": "20", "tempMax": "28"}],
    }))
    weather_client = client(cache=cache)

    first = await weather_client.daily_forecast("city", date(2026, 9, 1), 1)
    first["daily"][0]["condition"] = "被修改"
    second = await weather_client.daily_forecast("city", date(2026, 9, 1), 1)

    assert second["data_status"] == "cached"
    assert second["daily"][0]["condition"] == "晴"
    assert second["daily"][0] is not first["daily"][0]


@respx.mock
@pytest.mark.asyncio
async def test_weather_cache_contains_only_controlled_projection():
    cache = MemoryCache()
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json={
        "code": "200",
        "updateTime": "2026-08-20T10:00:00Z",
        "key": "supplier-secret",
        "daily": [{"fxDate": "2026-09-01", "textDay": "晴", "tempMin": "20", "tempMax": "28", "raw": "discard"}],
    }))

    await client(cache=cache).daily_forecast("city", date(2026, 9, 1), 1)

    cached_value = next(iter(cache._entries.values()))[0]
    assert set(cached_value) == {"source_updated_at", "daily"}
    assert set(cached_value["daily"][0]) == {"date", "condition", "temp_min", "temp_max"}
    assert "code" not in cached_value
    assert "updateTime" not in cached_value
    assert "supplier-secret" not in repr(cached_value)


@pytest.mark.parametrize("payload", [
    None,
    {"code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": {}},
    {"code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [None]},
    {"code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [{"fxDate": "2026-09-01", "textDay": "晴", "tempMin": "坏", "tempMax": "28"}]},
])
@respx.mock
@pytest.mark.asyncio
async def test_each_malformed_weather_shape_records_breaker_failure(payload):
    respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(200, json=payload))
    weather_client = client()

    with pytest.raises(ExternalServiceUnavailable, match="和风天气未返回有效数据"):
        await weather_client.daily_forecast("city", date(2026, 9, 1), 1)

    assert weather_client.breaker.failure_count == 1


@pytest.mark.parametrize("status_code", [400, 401])
@respx.mock
@pytest.mark.asyncio
async def test_weather_non_2xx_success_shaped_response_is_not_cached(status_code):
    cache = MemoryCache()
    route = respx.get(f"{BASE}/v7/weather/3d").mock(return_value=httpx.Response(status_code, json={
        "code": "200",
        "updateTime": "2026-08-20T10:00:00Z",
        "daily": [{"fxDate": "2026-09-01", "textDay": "晴", "tempMin": "20", "tempMax": "28"}],
    }))
    weather_client = client(cache=cache)

    with pytest.raises(ExternalServiceUnavailable, match="和风天气未返回有效数据"):
        await weather_client.daily_forecast("city", date(2026, 9, 1), 1)

    assert route.call_count == 1
    assert cache._entries == {}
    assert weather_client.breaker.failure_count == 1
