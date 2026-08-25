from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from app.errors import FliggyHotelUpstreamError
from app.services.fliggy_hotel_client import (
    FliggyHotelClient,
    FliggyRawHotel,
    FliggyRawSearchResult,
)

URL = "https://eco.taobao.com/router/rest"


def client(**kwargs):
    return FliggyHotelClient(
        app_key="app-key", app_secret="app-secret", sub_channel="channel-1", **kwargs
    )


@pytest.mark.asyncio
@respx.mock
async def test_posts_fixed_signed_request_and_projects_official_envelope():
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "alitrip_btrip_hotel_distribution_search_low_price_response": {
                    "result": {
                        "module": {
                            "hotels": [
                                {
                                    "shid": 10076614,
                                    "name": "杭州中洲大酒店",
                                    "low_price": 18000,
                                    "supplier_name": "飞猪",
                                    "private": "discard",
                                }
                            ],
                            "total": 1,
                        }
                    }
                }
            },
        )
    )
    result = await client().search_low_price("杭州", date(2026, 9, 1), date(2026, 9, 2), 2, 10)

    assert route.called
    request = route.calls[0].request
    assert request.url == URL
    assert request.method == "POST"
    fields = dict(httpx.QueryParams(request.content.decode()))
    assert fields["method"] == "alitrip.btrip.hotel.distribution.search.low.price"
    assert "sign" in fields
    business = httpx.QueryParams(request.content.decode())["param_hotel_search_list_r_q"]
    import json
    payload = json.loads(business)
    assert payload == {
        "city_name": "杭州",
        "check_in": "2026-09-01",
        "check_out": "2026-09-02",
        "page_no": 2,
        "page_size": 10,
        "sub_channel": "channel-1",
        "order": 2,
        "dir": 1,
    }
    assert result == FliggyRawSearchResult(
        hotels=(FliggyRawHotel("10076614", "杭州中洲大酒店", 18000, "飞猪"),), total=1
    )


@pytest.mark.asyncio
@respx.mock
async def test_empty_result_is_returned_without_cache():
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(200, json={"alitrip_btrip_hotel_distribution_search_low_price_response": {"result": {"module": {"hotels": [], "total": 0}}}}),
            httpx.Response(200, json={"alitrip_btrip_hotel_distribution_search_low_price_response": {"result": {"module": {"hotels": [], "total": 0}}}}),
        ]
    )
    first = await client().search_low_price("杭州", "2026-09-01", "2026-09-02", 1, 20)
    second = await client().search_low_price("杭州", "2026-09-01", "2026-09-02", 1, 20)
    assert first.hotels == second.hotels == ()
    assert route.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("responses", [[httpx.Response(503), httpx.Response(429), httpx.Response(200, json={"alitrip_btrip_hotel_distribution_search_low_price_response": {"result": {"module": {"hotels": [], "total": 0}}}})]])
@respx.mock
async def test_retries_429_and_5xx(responses):
    route = respx.post(URL).mock(side_effect=responses)
    await client().search_low_price("杭州", "2026-09-01", "2026-09-02", 1, 20)
    assert route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_maps_provider_auth_permission_and_channel_errors_without_sensitive_data():
    cases = [
        ({"error_response": {"code": "401", "msg": "authentication failed"}}, "AUTH_ERROR"),
        ({"error_response": {"code": "403", "msg": "permission denied"}}, "PERMISSION_ERROR"),
        ({"error_response": {"code": "CHANNEL_INVALID", "msg": "bad channel"}}, "CHANNEL_ERROR"),
    ]
    for body, code in cases:
        respx.post(URL).mock(return_value=httpx.Response(200, json=body))
        with pytest.raises(FliggyHotelUpstreamError) as exc:
            await client().search_low_price("杭州", "2026-09-01", "2026-09-02", 1, 20)
        assert exc.value.code == code
        assert "app-secret" not in str(exc.value)
        assert "authentication failed" not in str(exc.value)
        respx.reset()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, text="not-json"), httpx.Response(200, json={"unexpected": {}}), httpx.Response(200, json={"alitrip_btrip_hotel_distribution_search_low_price_response": {"result": {"module": {"hotels": [{"shid": 1, "name": "坏价格", "low_price": -1, "supplier_name": "飞猪"}], "total": 1}}}})],
)
async def test_invalid_json_structure_and_price_are_controlled(response):
    respx.post(URL).mock(return_value=response)
    with pytest.raises(FliggyHotelUpstreamError) as exc:
        await client().search_low_price("杭州", "2026-09-01", "2026-09-02", 1, 20)
    assert exc.value.code == "INVALID_RESPONSE"
    assert "app-secret" not in repr(exc.value)


@pytest.mark.asyncio
@respx.mock
async def test_timeout_is_classified_separately_from_transport_failure():
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("secret.internal/path"))
    with pytest.raises(FliggyHotelUpstreamError) as exc:
        await client(max_attempts=1).search_low_price("杭州", "2026-09-01", "2026-09-02", 1, 20)
    assert exc.value.code == "TIMEOUT"
    assert exc.value.retryable is True
    assert "secret.internal" not in repr(exc.value)


@pytest.mark.asyncio
@respx.mock
async def test_mixed_retry_failure_uses_final_timeout_classification():
    respx.post(URL).mock(side_effect=[httpx.Response(503), httpx.ReadTimeout("private timeout")])
    with pytest.raises(FliggyHotelUpstreamError) as exc:
        await client(max_attempts=2).search_low_price("杭州", "2026-09-01", "2026-09-02", 1, 20)
    assert exc.value.code == "TIMEOUT"
    assert exc.value.retryable is True


@pytest.mark.asyncio
@respx.mock
async def test_transport_failure_is_controlled_and_does_not_expose_details():
    respx.post(URL).mock(side_effect=httpx.ConnectError("secret.internal/path"))
    with pytest.raises(FliggyHotelUpstreamError) as exc:
        await client(max_attempts=1).search_low_price("杭州", "2026-09-01", "2026-09-02", 1, 20)
    assert exc.value.code == "NETWORK_ERROR"
    assert exc.value.retryable is True
    assert "secret.internal" not in repr(exc.value)


def test_canonical_url_is_not_overridable_and_raw_models_are_immutable():
    with pytest.raises(ValueError):
        FliggyHotelClient("app", "secret", "channel", base_url="http://evil.example")
    raw = FliggyRawHotel("1", "酒店", 100, "飞猪")
    with pytest.raises((AttributeError, TypeError)):
        raw.name = "改名"
    assert Decimal(raw.low_price_cents) == Decimal("100")
