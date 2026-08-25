from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.errors import FliggyHotelUpstreamError
from app.models.fliggy_hotel import FliggyHotelSearchRequest
from app.services.fliggy_hotel import HotelSearchService
from app.services.fliggy_hotel_client import FliggyRawHotel, FliggyRawSearchResult


class FakeHotelClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def search_low_price(self, city_name, check_in, check_out, page_no, page_size):
        self.calls.append((city_name, check_in, check_out, page_no, page_size))
        if self.error is not None:
            raise self.error
        return self.result


def request() -> FliggyHotelSearchRequest:
    return FliggyHotelSearchRequest(
        city_name=" 杭州 ",
        check_in=date(2099, 9, 1),
        check_out=date(2099, 9, 2),
        page_no=2,
        page_size=10,
    )


@pytest.mark.asyncio
async def test_search_filters_invalid_prices_and_fields_and_stably_sorts_by_cents():
    client = FakeHotelClient(
        FliggyRawSearchResult(
            hotels=(
                FliggyRawHotel("first", "同价先", 1200, "供应商"),
                FliggyRawHotel("2", "较低", 1001, "供应商"),
                FliggyRawHotel("second", "同价后", 1200, "供应商"),
                FliggyRawHotel("bad-price", "非正", 0, "供应商"),
                FliggyRawHotel("bad-price-2", "负数", -1, "供应商"),
                FliggyRawHotel("", "空 ID", 500, "供应商"),
                FliggyRawHotel("bad-name", "", 500, "供应商"),
            ),
            total=7,
        )
    )

    response = await HotelSearchService(client).search(request(), str(uuid4()))

    assert [hotel.hotel_id for hotel in response.hotels] == ["2", "first", "second"]
    assert [hotel.name for hotel in response.hotels] == ["较低", "同价先", "同价后"]
    assert [hotel.low_price for hotel in response.hotels] == [Decimal("10.01"), Decimal("12"), Decimal("12")]


@pytest.mark.asyncio
async def test_search_builds_realtime_source_pagination_total_and_preserves_trace_id():
    client = FakeHotelClient(
        FliggyRawSearchResult(
            hotels=(FliggyRawHotel(10076614, "杭州中洲大酒店", 18000, "飞猪"),),
            total=42,
        )
    )
    trace_id = str(uuid4())

    response = await HotelSearchService(client).search(request(), trace_id)

    assert response.status == "realtime"
    assert response.source.provider == "fliggy"
    assert response.source.retrieved_at.tzinfo is not None
    assert response.source.retrieved_at.utcoffset() == timezone.utc.utcoffset(response.source.retrieved_at)
    assert response.total == 42
    assert response.page_no == 2
    assert response.page_size == 10
    assert response.trace_id == trace_id
    assert response.hotels[0].hotel_id == "10076614"
    assert response.hotels[0].currency == "CNY"
    assert response.hotels[0].supplier == "飞猪"
    assert client.calls == [("杭州", date(2099, 9, 1), date(2099, 9, 2), 2, 10)]


@pytest.mark.asyncio
async def test_search_keeps_supplier_total_when_no_valid_hotels_remain():
    client = FakeHotelClient(
        FliggyRawSearchResult(
            hotels=(FliggyRawHotel("bad", "坏数据", 0, "供应商"),),
            total=9,
        )
    )

    response = await HotelSearchService(client).search(request(), str(uuid4()))

    assert response.hotels == ()
    assert response.total == 9


@pytest.mark.asyncio
async def test_search_preserves_safe_client_error_without_other_provider_calls():
    error = FliggyHotelUpstreamError("NETWORK_ERROR", None, True)
    client = FakeHotelClient(error=error)

    with pytest.raises(FliggyHotelUpstreamError) as raised:
        await HotelSearchService(client).search(request(), str(uuid4()))

    assert raised.value is error
    assert client.calls == [("杭州", date(2099, 9, 1), date(2099, 9, 2), 2, 10)]
    assert not hasattr(client, "amap")
    assert "secret" not in str(raised.value)
