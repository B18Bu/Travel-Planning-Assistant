from datetime import timezone

import httpx
import pytest
import respx

from app.services.amap import AmapClient
from app.services.cache import MemoryCache
from app.services.resilience import CircuitBreaker, ExternalServiceUnavailable


BASE = "https://amap.test"


def client(**kwargs):
    options = {
        "api_key": "amap-key",
        "base_url": BASE,
        "cache": MemoryCache(),
        "breaker": CircuitBreaker(failure_threshold=3, open_seconds=60),
        "max_attempts": 3,
        "geocode_cache_ttl_seconds": 604800,
        "route_cache_ttl_seconds": 900,
        "poi_cache_ttl_seconds": 3600,
        "timeout": httpx.Timeout(2.0),
    }
    options.update(kwargs)
    return AmapClient(**options)


@respx.mock
@pytest.mark.asyncio
async def test_maps_fixed_amap_endpoints_and_controlled_fields():
    geo = respx.get(f"{BASE}/v3/geocode/geo").mock(
        return_value=httpx.Response(
            200,
            json={"status": "1", "geocodes": [{"formatted_address": "成都市", "location": "104.06,30.57", "adcode": "510100", "private": "discard"}]},
        )
    )
    route = respx.get(f"{BASE}/v5/direction/driving").mock(
        return_value=httpx.Response(
            200,
            json={"status": "1", "route": {"paths": [{"distance": "1800", "duration": "600", "polyline": "secret"}]}},
        )
    )
    poi = respx.get(f"{BASE}/v5/place/text").mock(
        return_value=httpx.Response(
            200,
            json={"status": "1", "pois": [{"name": "示例酒店", "address": "示例路 1 号", "location": "104.08,30.57", "type": "住宿服务", "photos": "discard"}]},
        )
    )
    amap = client()

    location = await amap.geocode("成都")
    route_result = await amap.driving_route("104.06,30.57", "104.08,30.57")
    pois = await amap.search_poi("住宿服务", "成都")

    assert geo.calls[0].request.url.params["address"] == "成都"
    assert geo.calls[0].request.url.params["key"] == "amap-key"
    assert route.calls[0].request.url.params["origin"] == "104.06,30.57"
    assert route.calls[0].request.url.params["destination"] == "104.08,30.57"
    assert route.calls[0].request.url.params["key"] == "amap-key"
    assert poi.calls[0].request.url.params["keywords"] == "住宿服务"
    assert poi.calls[0].request.url.params["city"] == "成都"
    assert poi.calls[0].request.url.params["citylimit"] == "true"
    assert poi.calls[0].request.url.params["key"] == "amap-key"
    assert location["name"] == "成都市"
    assert location["location"] == "104.06,30.57"
    assert location["adcode"] == "510100"
    assert location["data_status"] == "realtime"
    assert location["retrieved_at"].tzinfo == timezone.utc
    assert route_result["distance_meters"] == 1800
    assert route_result["duration_minutes"] == 10
    assert route_result["data_status"] == "realtime"
    assert pois[0]["name"] == "示例酒店"
    assert pois[0]["category"] == "住宿服务"


@respx.mock
@pytest.mark.asyncio
async def test_amap_cache_hit_uses_one_route_call():
    route = respx.get(f"{BASE}/v5/direction/driving").mock(return_value=httpx.Response(200, json={"status": "1", "route": {"paths": [{"distance": "100", "duration": "60"}]}}))
    amap = client()

    first = await amap.driving_route("a", "b")
    second = await amap.driving_route("a", "b")

    assert route.call_count == 1
    assert first["distance_meters"] == second["distance_meters"]
    assert first["duration_minutes"] == second["duration_minutes"]
    assert second["data_status"] == "cached"


@respx.mock
@pytest.mark.asyncio
async def test_geocode_cache_hit_has_cached_metadata_and_one_request():
    route = respx.get(f"{BASE}/v3/geocode/geo").mock(
        return_value=httpx.Response(
            200,
            json={"status": "1", "info": "2026-08-20T10:00:00Z", "geocodes": [{"formatted_address": "成都", "location": "1,2", "adcode": "3"}]},
        )
    )
    amap = client()

    first = await amap.geocode("成都")
    second = await amap.geocode("成都")

    assert route.call_count == 1
    assert first["data_status"] == "realtime"
    assert second["data_status"] == "cached"
    assert second["source_updated_at"] == first["source_updated_at"]
    assert second["retrieved_at"] >= first["retrieved_at"]


@pytest.mark.asyncio
async def test_empty_key_and_open_breaker_are_checked_before_http(monkeypatch):
    amap = client(api_key="")
    called = False

    async def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("不应发 HTTP")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail_if_called)
    with pytest.raises(ExternalServiceUnavailable):
        await amap.geocode("secret-address")
    assert called is False


@pytest.mark.asyncio
async def test_open_breaker_is_checked_after_key(monkeypatch):
    breaker = CircuitBreaker(failure_threshold=1, open_seconds=60)
    breaker.record_failure()
    amap = client(breaker=breaker)
    called = False

    async def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("不应发 HTTP")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail_if_called)
    with pytest.raises(ExternalServiceUnavailable, match="外部服务熔断中"):
        await amap.geocode("secret-address")
    assert called is False


@respx.mock
@pytest.mark.asyncio
async def test_non_429_4xx_is_single_request_and_controlled():
    route = respx.get(f"{BASE}/v3/geocode/geo").mock(return_value=httpx.Response(400, text="secret body https://private.example"))

    with pytest.raises(ExternalServiceUnavailable) as exc_info:
        await client().geocode("secret-address")

    assert route.call_count == 1
    assert str(exc_info.value) == "高德地图未返回有效数据"
    assert all(value not in str(exc_info.value) for value in ("secret", "private", BASE, "secret-address"))


@pytest.mark.parametrize("status_code", [429, 503])
@respx.mock
@pytest.mark.asyncio
async def test_retryable_failures_exhaust_and_record_failure(status_code):
    route = respx.get(f"{BASE}/v3/geocode/geo").mock(return_value=httpx.Response(status_code, text="secret body"))
    amap = client(max_attempts=2)

    with pytest.raises(ExternalServiceUnavailable) as exc_info:
        await amap.geocode("secret-address")

    assert route.call_count == 2
    assert str(exc_info.value) == "外部服务暂不可用"
    assert "secret" not in str(exc_info.value)
    assert amap.breaker.failure_count == 1


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("private-url"), httpx.ConnectError("private-host")])
@respx.mock
@pytest.mark.asyncio
async def test_timeout_and_transport_failure_are_controlled(failure):
    route = respx.get(f"{BASE}/v3/geocode/geo").mock(side_effect=failure)

    with pytest.raises(ExternalServiceUnavailable) as exc_info:
        await client(max_attempts=2).geocode("secret-address")

    assert route.call_count == 2
    assert str(exc_info.value) == "外部服务暂不可用"
    assert all(value not in str(exc_info.value) for value in ("private", "secret-address", BASE))


@pytest.mark.asyncio
async def test_empty_key_fails_before_http(monkeypatch):
    amap = client(api_key="")
    called = False

    async def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("不应发 HTTP")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail_if_called)
    with pytest.raises(ExternalServiceUnavailable) as exc_info:
        await amap.geocode("成都")
    assert str(exc_info.value) == "高德地图 API 密钥未配置"
    assert called is False


@respx.mock
@pytest.mark.asyncio
async def test_status_not_one_is_controlled_error():
    respx.get(f"{BASE}/v3/geocode/geo").mock(return_value=httpx.Response(200, json={"status": "0", "info": "private"}))

    with pytest.raises(ExternalServiceUnavailable) as exc_info:
        await client().geocode("成都")
    assert str(exc_info.value) == "高德地图未返回有效数据"


@pytest.mark.parametrize("method,args", [("geocode", ("成都",)), ("driving_route", ("a", "b"))])
@respx.mock
@pytest.mark.asyncio
async def test_empty_geocode_or_route_is_controlled_error(method, args):
    path = "/v3/geocode/geo" if method == "geocode" else "/v5/direction/driving"
    payload = {"status": "1", "geocodes": []} if method == "geocode" else {"status": "1", "route": {"paths": []}}
    respx.get(f"{BASE}{path}").mock(return_value=httpx.Response(200, json=payload))

    with pytest.raises(ExternalServiceUnavailable) as exc_info:
        await getattr(client(), method)(*args)
    assert str(exc_info.value) in {"高德地图未找到地点", "高德地图未返回有效路线"}


@respx.mock
@pytest.mark.asyncio
async def test_empty_poi_is_valid_empty_list():
    respx.get(f"{BASE}/v5/place/text").mock(return_value=httpx.Response(200, json={"status": "1", "pois": []}))

    assert await client().search_poi("住宿", "成都") == []


@respx.mock
@pytest.mark.asyncio
async def test_429_is_retried():
    route = respx.get(f"{BASE}/v3/geocode/geo").mock(side_effect=[httpx.Response(429), httpx.Response(200, json={"status": "1", "geocodes": [{"formatted_address": "成都", "location": "1,2", "adcode": "3"}]})])
    amap = client()
    result = await amap.geocode("成都")
    assert route.call_count == 2
    assert result["location"] == "1,2"


@pytest.mark.asyncio
async def test_open_breaker_fails_without_http(monkeypatch):
    breaker = CircuitBreaker(failure_threshold=1, open_seconds=60)
    breaker.record_failure()
    amap = client(breaker=breaker)
    called = False

    async def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("不应发 HTTP")

    monkeypatch.setattr(httpx.AsyncClient, "get", fail_if_called)
    with pytest.raises(ExternalServiceUnavailable, match="外部服务熔断中"):
        await amap.geocode("成都")
    assert called is False
