from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.fliggy_hotel import (
    FliggyHotel,
    FliggyHotelSearchRequest,
    FliggyHotelSearchResponse,
    FliggyHotelSource,
)


def test_request_strips_city_and_accepts_valid_dates():
    request = FliggyHotelSearchRequest(
        city_name=" 杭州 ",
        check_in=date.today(),
        check_out=date.today() + timedelta(days=1),
    )

    assert request.city_name == "杭州"
    assert request.page_no == 1
    assert request.page_size == 20


def test_request_rejects_invalid_date_range_page_and_unknown_field():
    with pytest.raises(ValidationError):
        FliggyHotelSearchRequest(
            city_name="杭州",
            check_in=date.today() + timedelta(days=1),
            check_out=date.today(),
            page_no=0,
            unexpected="x",
        )


def test_request_rejects_blank_city_and_page_size_outside_bounds():
    with pytest.raises(ValidationError):
        FliggyHotelSearchRequest(
            city_name="  ",
            check_in=date.today(),
            check_out=date.today() + timedelta(days=1),
            page_size=51,
        )


def test_request_rejects_datetime_strings_instead_of_date_only_strings():
    with pytest.raises(ValidationError):
        FliggyHotelSearchRequest(
            city_name="杭州",
            check_in=f"{date.today().isoformat()}T00:00:00",
            check_out=(date.today() + timedelta(days=1)).isoformat(),
        )


def test_price_is_decimal_in_memory_but_numeric_in_json_contract():
    hotel = FliggyHotel(
        hotel_id="1", name="测试酒店", low_price=Decimal("180.25")
    )

    assert isinstance(hotel.low_price, Decimal)
    assert hotel.model_dump()["low_price"] == Decimal("180.25")
    assert hotel.model_dump(mode="json")["low_price"] == 180.25
    assert isinstance(hotel.model_dump(mode="json")["low_price"], (int, float))


@pytest.mark.parametrize("hotel_id", [None, "", "  ", 1.5, object()])
def test_hotel_id_rejects_none_empty_and_unsupported_values(hotel_id):
    with pytest.raises(ValidationError):
        FliggyHotel(
            hotel_id=hotel_id,
            name="测试酒店",
            low_price=Decimal("180.00"),
        )


def test_models_are_frozen_and_response_has_fixed_realtime_metadata():
    trace_id = str(uuid4())
    response = FliggyHotelSearchResponse(
        status="realtime",
        source=FliggyHotelSource(
            provider="fliggy",
            retrieved_at=datetime.now(timezone.utc),
        ),
        hotels=(
            FliggyHotel(
                hotel_id=10076614,
                name="杭州中洲大酒店",
                low_price=Decimal("180.00"),
            ),
        ),
        total=1,
        page_no=1,
        page_size=20,
        trace_id=trace_id,
    )

    assert response.hotels[0].hotel_id == "10076614"
    assert response.hotels[0].low_price == Decimal("180.00")
    assert response.hotels[0].currency == "CNY"
    assert response.hotels[0].supplier == "飞猪"
    assert response.model_dump(mode="json")["hotels"][0]["hotel_id"] == "10076614"
    with pytest.raises((ValidationError, TypeError)):
        response.page_no = 2


def test_response_rejects_non_v1_to_v5_trace_id_and_unknown_fields():
    with pytest.raises(ValidationError):
        FliggyHotelSearchResponse(
            status="realtime",
            source={
                "provider": "fliggy",
                "retrieved_at": datetime.now(timezone.utc),
            },
            hotels=(),
            total=0,
            page_no=1,
            page_size=20,
            trace_id=str(uuid4()),
            extra_field="must-not-be-accepted",
        )
