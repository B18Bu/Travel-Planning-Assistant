from datetime import timezone

import httpx
import pytest
import respx

from app.services.amap import AmapClient
from app.services.cache import MemoryCache
from app.services.resilience import CircuitBreaker, ExternalServiceUnavailable

BASE = "https://restapi.amap.com"


def client(**kwargs):
    options = {"api_key": "amap-key", "base_url": BASE, "cache": MemoryCache(), "breaker": CircuitBreaker(3, 60), "max_attempts": 3, "geocode_cache_ttl_seconds": 604800, "route_cache_ttl_seconds": 900, "poi_cache_ttl_seconds": 3600, "timeout": httpx.Timeout(2.0)}
    options.update(kwargs)
    return AmapClient(**options)


@respx.mock
@pytest.mark.asyncio
async def test_maps_fixed_endpoints_and_allowed_fields():
    geo = respx.get(f"{BASE}/v3/geocode/geo").mock(return_value=httpx.Response(200, json={"status": "1", "geocodes": [{"formatted_address": "成都市", "location": "104.06,30.57", "adcode": "510100", "private": "discard"}]}))
    route = respx.get(f"{BASE}/v5/direction/driving").mock(return_value=httpx.Response(200, json={"status": "1", "route": {"paths": [{"distance": "1800", "duration": "600", "polyline": "secret"}]}}))
    poi = respx.get(f"{BASE}/v5/place/text").mock(return_value=httpx.Response(200, json={"status": "1", "pois": [{"name": "示例酒店", "address": "示例路 1 号", "location": "104.08,30.57", "type": "住宿服务", "photos": "discard"}]}))
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
    assert set(location) == {"name", "location", "adcode", "data_status", "source_updated_at", "retrieved_at"}
    assert set(route_result) == {"distance_meters", "duration_minutes", "data_status", "source_updated_at", "retrieved_at"}
    assert set(pois[0]) == {"name", "address", "location", "category", "data_status", "source_updated_at", "retrieved_at"}
    assert location["source_updated_at"] is None and route_result["source_updated_at"] is None
    assert location["retrieved_at"].tzinfo == timezone.utc
    assert route_result["duration_minutes"] == 10 and pois[0]["category"] == "住宿服务"


@respx.mock
@pytest.mark.asyncio
async def test_route_cache_hit_is_cached():
    route = respx.get(f"{BASE}/v5/direction/driving").mock(return_value=httpx.Response(200, json={"status": "1", "route": {"paths": [{"distance": "100", "duration": "60"}]}}))
    amap = client()
    first = await amap.driving_route("a", "b")
    second = await amap.driving_route("a", "b")
    assert route.call_count == 1 and first["distance_meters"] == second["distance_meters"]
    assert second["data_status"] == "cached" and second["source_updated_at"] is None


@respx.mock
@pytest.mark.asyncio
async def test_poi_cache_hit_has_ttl_metadata_and_no_raw_payload():
    route = respx.get(f"{BASE}/v5/place/text").mock(return_value=httpx.Response(200, json={"status": "1", "info": "private", "pois": [{"name": "餐厅", "address": "道路", "location": "1,2", "type": "餐饮", "photos": "private"}]}))
    cache = MemoryCache()
    amap = client(cache=cache)
    first = await amap.search_poi("餐饮", "成都")
    second = await amap.search_poi("餐饮", "成都")
    assert route.call_count == 1 and first[0]["data_status"] == "realtime" and second[0]["data_status"] == "cached"
    assert second[0]["retrieved_at"] >= first[0]["retrieved_at"]
    cached_value = next(iter(cache._entries.values()))[0]
    assert set(cached_value) == {"data", "data_status", "source_updated_at", "retrieved_at"}
    assert set(cached_value["data"]) == {"pois"}
    assert set(cached_value["data"]["pois"][0]) == {"name", "address", "location", "category"}
    assert "status" not in cached_value["data"]
    assert "info" not in cached_value["data"]
    assert "photos" not in cached_value["data"]["pois"][0]
    assert "amap-key" not in repr(cached_value)
    assert "private" not in repr(cached_value)


@respx.mock
@pytest.mark.asyncio
async def test_geocode_cache_hit_is_cached():
    route = respx.get(f"{BASE}/v3/geocode/geo").mock(return_value=httpx.Response(200, json={"status": "1", "geocodes": [{"formatted_address": "成都", "location": "1,2", "adcode": "3"}]}))
    amap = client()
    first = await amap.geocode("成都")
    second = await amap.geocode("成都")
    assert route.call_count == 1 and first["data_status"] == "realtime" and second["data_status"] == "cached"


@pytest.mark.asyncio
async def test_empty_key_and_open_breaker_fail_before_http(monkeypatch):
    called = False
    async def fail(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("不应发 HTTP")
    monkeypatch.setattr(httpx.AsyncClient, "get", fail)
    with pytest.raises(ExternalServiceUnavailable, match="API 密钥"):
        await client(api_key="").geocode("成都")
    breaker = CircuitBreaker(1, 60); breaker.record_failure()
    with pytest.raises(ExternalServiceUnavailable, match="外部服务熔断中"):
        await client(breaker=breaker).geocode("成都")
    assert not called


@respx.mock
@pytest.mark.asyncio
async def test_non_429_4xx_is_single_controlled_request():
    route = respx.get(f"{BASE}/v3/geocode/geo").mock(return_value=httpx.Response(400, text="secret body https://private.example"))
    with pytest.raises(ExternalServiceUnavailable, match="未返回有效数据"):
        await client().geocode("secret-address")
    assert route.call_count == 1


@pytest.mark.parametrize("status_code", [429, 503])
@respx.mock
@pytest.mark.asyncio
async def test_retryable_exhaustion_is_controlled(status_code):
    route = respx.get(f"{BASE}/v3/geocode/geo").mock(return_value=httpx.Response(status_code, text="secret body"))
    amap = client(max_attempts=2)
    with pytest.raises(ExternalServiceUnavailable, match="暂不可用"):
        await amap.geocode("secret-address")
    assert route.call_count == 2 and amap.breaker.failure_count == 1


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("private-url"), httpx.ConnectError("private-host")])
@respx.mock
@pytest.mark.asyncio
async def test_transport_failures_are_controlled(failure):
    route = respx.get(f"{BASE}/v3/geocode/geo").mock(side_effect=failure)
    with pytest.raises(ExternalServiceUnavailable, match="暂不可用"):
        await client(max_attempts=2).geocode("secret-address")
    assert route.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_retry_success_clears_prior_breaker_failure(monkeypatch):
    breaker = CircuitBreaker(2, 60); breaker.record_failure()
    route = respx.get(f"{BASE}/v3/geocode/geo").mock(side_effect=[httpx.Response(429), httpx.Response(200, json={"status": "1", "geocodes": [{"formatted_address": "成都", "location": "1,2", "adcode": "3"}]})])
    async def immediate(_delay): return None
    monkeypatch.setattr("app.services.resilience.asyncio.sleep", immediate)
    await client(breaker=breaker).geocode("成都")
    assert route.call_count == 2 and breaker.failure_count == 0
    breaker.ensure_available()


@respx.mock
@pytest.mark.asyncio
async def test_status_empty_results_and_empty_poi_are_controlled_or_valid():
    respx.get(f"{BASE}/v3/geocode/geo").mock(return_value=httpx.Response(200, json={"status": "0", "info": "private"}))
    with pytest.raises(ExternalServiceUnavailable): await client().geocode("成都")
    respx.reset(); respx.get(f"{BASE}/v3/geocode/geo").mock(return_value=httpx.Response(200, json={"status": "1", "geocodes": []}))
    with pytest.raises(ExternalServiceUnavailable, match="未找到地点"): await client().geocode("成都")
    respx.reset(); respx.get(f"{BASE}/v5/direction/driving").mock(return_value=httpx.Response(200, json={"status": "1", "route": {"paths": []}}))
    with pytest.raises(ExternalServiceUnavailable, match="有效路线"): await client().driving_route("a", "b")
    respx.reset(); respx.get(f"{BASE}/v5/place/text").mock(return_value=httpx.Response(200, json={"status": "1", "pois": []}))
    assert await client().search_poi("住宿", "成都") == []


@pytest.mark.parametrize("bad_url", ["http://evil.test", "https://evil.test"])
def test_rejects_untrusted_base_url(bad_url):
    with pytest.raises(ExternalServiceUnavailable, match="服务地址不受支持"):
        client(base_url=bad_url)


@pytest.mark.parametrize("attempts", [0, 4, 99])
def test_rejects_attempt_count_out_of_range(attempts):
    with pytest.raises(ValueError): client(max_attempts=attempts)


@pytest.mark.parametrize("payload", [None, [], "bad"])
@respx.mock
@pytest.mark.asyncio
async def test_top_level_non_dict_is_controlled(payload):
    respx.get(f"{BASE}/v3/geocode/geo").mock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(ExternalServiceUnavailable, match="有效数据"): await client().geocode("成都")


@pytest.mark.parametrize("geocodes", [[None], ["bad"]])
@respx.mock
@pytest.mark.asyncio
async def test_geocode_item_non_dict_is_controlled(geocodes):
    respx.get(f"{BASE}/v3/geocode/geo").mock(return_value=httpx.Response(200, json={"status": "1", "geocodes": geocodes}))
    with pytest.raises(ExternalServiceUnavailable, match="找到地点"): await client().geocode("成都")


@pytest.mark.parametrize("route_payload", [None, [], "bad"])
@respx.mock
@pytest.mark.asyncio
async def test_route_non_dict_is_controlled(route_payload):
    respx.get(f"{BASE}/v5/direction/driving").mock(return_value=httpx.Response(200, json={"status": "1", "route": route_payload}))
    with pytest.raises(ExternalServiceUnavailable, match="有效路线"): await client().driving_route("a", "b")


@respx.mock
@pytest.mark.asyncio
async def test_route_path_and_number_types_are_controlled():
    respx.get(f"{BASE}/v5/direction/driving").mock(return_value=httpx.Response(200, json={"status": "1", "route": {"paths": [None]}}))
    with pytest.raises(ExternalServiceUnavailable, match="有效路线"): await client().driving_route("a", "b")
    respx.reset(); respx.get(f"{BASE}/v5/direction/driving").mock(return_value=httpx.Response(200, json={"status": "1", "route": {"paths": [{"distance": "坏", "duration": "1"}]}}))
    with pytest.raises(ExternalServiceUnavailable, match="有效路线"): await client().driving_route("a", "b")


@pytest.mark.parametrize("pois", [[None], ["bad"]])
@respx.mock
@pytest.mark.asyncio
async def test_poi_item_non_dict_is_controlled(pois):
    respx.get(f"{BASE}/v5/place/text").mock(return_value=httpx.Response(200, json={"status": "1", "pois": pois}))
    with pytest.raises(ExternalServiceUnavailable, match="有效 POI"): await client().search_poi("餐饮", "成都")
