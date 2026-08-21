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
    assert poi.calls[0].request.url.params["region"] == "成都"
    assert poi.calls[0].request.url.params["city_limit"] == "true"
    assert "city" not in poi.calls[0].request.url.params
    assert "citylimit" not in poi.calls[0].request.url.params
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
    assert isinstance(cached_value["data"], list)
    assert set(cached_value["data"][0]) == {"name", "address", "location", "category"}
    assert "status" not in cached_value
    assert "info" not in cached_value
    assert "photos" not in cached_value["data"][0]
    assert "amap-key" not in repr(cached_value)
    assert "private" not in repr(cached_value)


@respx.mock
@pytest.mark.asyncio
async def test_amap_source_updated_at_uses_valid_supplier_time_and_none_when_invalid():
    route = respx.get(f"{BASE}/v3/geocode/geo").mock(side_effect=[
        httpx.Response(200, json={"status": "1", "updateTime": "2026-08-20T10:00:00+08:00", "geocodes": [{"formatted_address": "成都", "location": "1,2", "adcode": "3"}]}),
        httpx.Response(200, json={"status": "1", "update_time": "bad", "geocodes": [{"formatted_address": "成都", "location": "1,2", "adcode": "3"}]}),
    ])
    cache = MemoryCache()
    first = await client(cache=cache).geocode("成都")
    second = await client(cache=MemoryCache()).geocode("成都")
    assert route.call_count == 2
    assert first["source_updated_at"].tzinfo is not None
    assert second["source_updated_at"] is None


@respx.mock
@pytest.mark.asyncio
async def test_amap_401_json_is_controlled_and_records_failure():
    respx.get(f"{BASE}/v3/geocode/geo").mock(return_value=httpx.Response(401, json={"status": "1", "geocodes": [{"formatted_address": "成都", "location": "1,2", "adcode": "3"}]}))
    amap = client()
    with pytest.raises(ExternalServiceUnavailable, match="未返回有效数据"):
        await amap.geocode("成都")
    assert amap.breaker.failure_count == 1


@pytest.mark.asyncio
async def test_amap_structured_cache_keys_avoid_collision_and_cross_key_reuse():
    cache = MemoryCache()
    first = client(cache=cache, api_key="key-one")
    second = client(cache=cache, api_key="key-two")
    assert first._cache_key("route", ["a", "b:c"]) != first._cache_key("route", ["a:b", "c"])
    assert first._cache_key("route", ["a", "b"]) != second._cache_key("route", ["a", "b"])
    assert "key-one" not in first._cache_key("route", ["a", "b"])


@respx.mock
@pytest.mark.asyncio
async def test_geocode_cache_hit_is_cached():
    route = respx.get(f"{BASE}/v3/geocode/geo").mock(return_value=httpx.Response(200, json={"status": "1", "geocodes": [{"formatted_address": "成都", "location": "1,2", "adcode": "3"}]}))
    amap = client()
    first = await amap.geocode("成都")
    second = await amap.geocode("成都")
    assert route.call_count == 1 and first["data_status"] == "realtime" and second["data_status"] == "cached"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,args", [
    ("geocode", (None,)), ("geocode", ([],)), ("geocode", ({},)), ("geocode", (True,)), ("geocode", ("",)),
    ("driving_route", (None, "b")), ("driving_route", ("a", None)), ("driving_route", ("a", [])),
    ("search_poi", (None, "成都")), ("search_poi", ("餐饮", None)), ("search_poi", ("", "成都")),
])
@pytest.mark.asyncio
async def test_amap_runtime_arguments_are_non_empty_text(method, args):
    cache = MemoryCache()
    with pytest.raises(ExternalServiceUnavailable):
        await getattr(client(cache=cache), method)(*args)
    assert cache._entries == {}


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


@pytest.mark.parametrize("bad_url", [
    "http://evil.test",
    "https://evil.test",
    "https://restapi.amap.com/",
    "https://restapi.amap.com/path",
    "https://restapi.amap.com?x=1",
    "https://restapi.amap.com#frag",
    "https://user@restapi.amap.com",
    "https://restapi.amap.com:443",
    "https://RESTAPI.AMAP.COM",
])
def test_rejects_noncanonical_amap_base_url(bad_url):
    with pytest.raises(ExternalServiceUnavailable, match="服务地址不受支持"):
        client(base_url=bad_url)


@pytest.mark.parametrize("attempts", [1, 2, 3])
def test_accepts_amap_attempt_count_bounds(attempts):
    assert client(max_attempts=attempts).max_attempts == attempts


@pytest.mark.parametrize("attempts", [0, 4, True, False])
def test_rejects_amap_attempt_count_out_of_range(attempts):
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


@pytest.mark.parametrize("field", ["name", "address", "location", "type"])
@pytest.mark.parametrize("value", [[], {}, True, ""])
@respx.mock
@pytest.mark.asyncio
async def test_amap_poi_fields_must_be_string_or_none(field, value):
    poi = {"name": "餐厅", "address": "道路", "location": "1,2", "type": "餐饮"}
    poi[field] = value
    respx.get(f"{BASE}/v5/place/text").mock(return_value=httpx.Response(200, json={"status": "1", "pois": [poi]}))
    amap = client()
    with pytest.raises(ExternalServiceUnavailable, match="有效 POI"):
        await amap.search_poi("餐饮", "成都")
    assert amap.breaker.failure_count == 1


@pytest.mark.parametrize("field", ["formatted_address", "location", "adcode"])
@pytest.mark.parametrize("value", [[], {}, True, ""])
@respx.mock
@pytest.mark.asyncio
async def test_amap_geocode_fields_must_be_string_or_none(field, value):
    item = {"formatted_address": "成都", "location": "1,2", "adcode": "3"}
    item[field] = value
    respx.get(f"{BASE}/v3/geocode/geo").mock(return_value=httpx.Response(200, json={"status": "1", "geocodes": [item]}))
    amap = client()
    with pytest.raises(ExternalServiceUnavailable, match="找到地点"):
        await amap.geocode("成都")
    assert amap.breaker.failure_count == 1


@pytest.mark.parametrize("field", ["distance", "duration"])
@pytest.mark.parametrize("value", [True, False, [], {}, "", "坏"])
@respx.mock
@pytest.mark.asyncio
async def test_amap_route_numbers_must_be_strict_integer(field, value):
    path = {"distance": "100", "duration": "60"}
    path[field] = value
    respx.get(f"{BASE}/v5/direction/driving").mock(return_value=httpx.Response(200, json={"status": "1", "route": {"paths": [path]}}))
    amap = client()
    with pytest.raises(ExternalServiceUnavailable, match="有效路线"):
        await amap.driving_route("a", "b")
    assert amap.breaker.failure_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_poi_more_than_ten_results_returns_only_first_ten():
    pois = [
        {"name": f"餐厅{i}", "address": f"道路{i}", "location": f"1,{i}", "type": "餐饮"}
        for i in range(11)
    ]
    respx.get(f"{BASE}/v5/place/text").mock(
        return_value=httpx.Response(200, json={"status": "1", "pois": pois})
    )

    result = await client().search_poi("餐饮", "成都")

    assert len(result) == 10
    assert [item["name"] for item in result] == [f"餐厅{i}" for i in range(10)]


@pytest.mark.parametrize("ttl_name", [
    "geocode_cache_ttl_seconds", "route_cache_ttl_seconds", "poi_cache_ttl_seconds",
])
@pytest.mark.parametrize("ttl", [0, -1, True, False])
def test_amap_rejects_non_positive_cache_ttl(ttl_name, ttl):
    with pytest.raises(ValueError):
        client(**{ttl_name: ttl})


@respx.mock
@pytest.mark.asyncio
async def test_amap_cached_poi_does_not_share_nested_items():
    cache = MemoryCache()
    respx.get(f"{BASE}/v5/place/text").mock(return_value=httpx.Response(200, json={
        "status": "1", "pois": [{"name": "餐厅", "address": "道路", "location": "1,2", "type": "餐饮"}],
    }))
    amap = client(cache=cache)

    first = await amap.search_poi("餐饮", "成都")
    first[0]["name"] = "被修改"
    second = await amap.search_poi("餐饮", "成都")

    assert second[0]["data_status"] == "cached"
    assert second[0]["name"] == "餐厅"
    assert second[0] is not first[0]


@respx.mock
@pytest.mark.asyncio
async def test_amap_unknown_path_is_controlled_and_not_cached():
    cache = MemoryCache()
    respx.get(f"{BASE}/v5/unknown").mock(return_value=httpx.Response(200, json={
        "status": "1", "pois": [{"name": "餐厅", "address": "道路", "location": "1,2", "type": "餐饮"}],
    }))
    amap = client(cache=cache)

    with pytest.raises(ExternalServiceUnavailable, match="未返回有效数据"):
        await amap._get("unknown", ["x"], "/v5/unknown", {}, 60)

    assert cache._entries == {}
    assert amap.breaker.failure_count == 1


@pytest.mark.parametrize("field", ["distance", "duration"])
@respx.mock
@pytest.mark.asyncio
async def test_amap_route_negative_measurements_are_controlled(field):
    path = {"distance": "100", "duration": "60"}
    path[field] = -1
    respx.get(f"{BASE}/v5/direction/driving").mock(
        return_value=httpx.Response(200, json={"status": "1", "route": {"paths": [path]}})
    )
    amap = client()

    with pytest.raises(ExternalServiceUnavailable, match="有效路线"):
        await amap.driving_route("a", "b")

    assert amap.breaker.failure_count == 1
