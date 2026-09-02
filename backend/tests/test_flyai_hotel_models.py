from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.flyai_hotel import (
    CombinedHotelResult,
    FlyAIHotel,
    FlyAIHotelSearchRequest,
)


def valid_dates() -> tuple[str, str]:
    check_in = date.today() + timedelta(days=1)
    return check_in.isoformat(), (check_in + timedelta(days=1)).isoformat()


def test_request_accepts_filters_and_defaults_sort():
    check_in, check_out = valid_dates()
    request = FlyAIHotelSearchRequest(
        city_name=" 杭州 ",
        check_in=check_in,
        check_out=check_out,
        poi_name=" 西湖 ",
        max_price="280.00",
        limit=20,
    )

    assert request.city_name == "杭州"
    assert request.poi_name == "西湖"
    assert request.sort == "rate_desc"
    assert request.max_price == Decimal("280.00")


def test_request_requires_strict_dates_and_valid_range():
    check_in, check_out = valid_dates()
    with pytest.raises(ValidationError):
        FlyAIHotelSearchRequest(
            city_name="杭州",
            check_in=f"{check_in}T00:00:00",
            check_out=check_out,
        )
    with pytest.raises(ValidationError):
        FlyAIHotelSearchRequest(
            city_name="杭州",
            check_in=check_out,
            check_out=check_in,
        )
    with pytest.raises(ValidationError):
        FlyAIHotelSearchRequest(
            city_name="杭州",
            check_in=date.today() - timedelta(days=1),
            check_out=date.today(),
        )


def test_request_rejects_invalid_sort_price_limit_and_unknown_fields():
    check_in, check_out = valid_dates()
    with pytest.raises(ValidationError):
        FlyAIHotelSearchRequest(
            city_name=" ", check_in=check_in, check_out=check_out
        )
    with pytest.raises(ValidationError):
        FlyAIHotelSearchRequest(
            city_name="杭州", check_in=check_in, check_out=check_out,
            sort="random", max_price=-1, limit=21, unexpected="x",
        )


def test_flyai_hotel_projects_only_whitelisted_fields_and_serializes_decimal():
    hotel = FlyAIHotel(
        hotel_id=123,
        name="测试酒店",
        address="西湖边",
        latitude="30.25",
        longitude=120.15,
        price="280.00",
        score="4.5",
        star=4,
        main_pic="https://example.com/main.jpg",
        detail_url="https://example.com/hotel",
    )

    assert hotel.hotel_id == "123"
    assert hotel.price == Decimal("280.00")
    assert hotel.model_dump(mode="json")["price"] == 280
    assert isinstance(hotel.model_dump(mode="json")["price"], int)
    assert set(hotel.model_dump()) == {
        "hotel_id", "name", "address", "latitude", "longitude", "price",
        "score", "star", "main_pic", "detail_url",
    }


def test_flyai_hotel_keeps_missing_price_as_none_not_zero():
    hotel = FlyAIHotel(hotel_id="1", name="无价酒店")
    assert hotel.price is None
    assert hotel.model_dump(mode="json")["price"] is None


def test_flyai_hotel_rejects_non_https_links_and_unknown_fields():
    with pytest.raises(ValidationError):
        FlyAIHotel(hotel_id="1", name="酒店", main_pic="http://example.com/a.jpg")
    with pytest.raises(ValidationError):
        FlyAIHotel(hotel_id="1", name="酒店", detail_url="http://example.com/hotel")
    with pytest.raises(ValidationError):
        FlyAIHotel(hotel_id="1", name="酒店", raw_response={})


def test_combined_result_expresses_matched_sources_without_fabricating_fields():
    result = CombinedHotelResult(
        hotel_name="测试酒店",
        flyai_price=Decimal("280.00"),
        flyai_score=Decimal("4.5"),
        flyai_star=4,
        flyai_main_pic="https://example.com/main.jpg",
        detail_url="https://example.com/hotel",
        amap_address="西湖边",
        amap_location="120.15,30.25",
        price_source="flyai",
        poi_source="amap",
        match_status="matched",
    )

    assert result.flyai_price == Decimal("280.00")
    assert result.model_dump(mode="json")["flyai_price"] == 280


def test_combined_result_keeps_unmatched_fields_empty():
    result = CombinedHotelResult(
        hotel_name="测试酒店",
        flyai_price=Decimal("280.00"),
        detail_url="https://example.com/hotel",
        price_source="flyai",
        match_status="flyai_only",
    )
    assert result.amap_address is None
    assert result.poi_source is None

    with pytest.raises(ValidationError):
        CombinedHotelResult(
            hotel_name="测试酒店",
            amap_address="不应出现在 FlyAI 独有结果",
            poi_source="amap",
            match_status="flyai_only",
        )


def test_combined_result_rejects_inconsistent_sources_and_links():
    with pytest.raises(ValidationError):
        CombinedHotelResult(
            hotel_name="测试酒店", match_status="matched", price_source="flyai"
        )
    with pytest.raises(ValidationError):
        CombinedHotelResult(
            hotel_name="测试酒店",
            match_status="poi_only",
            poi_source="amap",
            detail_url="https://example.com/should-not-exist",
        )
    with pytest.raises(ValidationError):
        CombinedHotelResult(
            hotel_name="测试酒店",
            match_status="matched",
            price_source="amap",
            poi_source="amap",
        )
    with pytest.raises(ValidationError):
        CombinedHotelResult(
            hotel_name="测试酒店",
            match_status="matched",
            flyai_main_pic="http://example.com/a.jpg",
            price_source="flyai",
            poi_source="amap",
        )


def test_models_reject_datetime_as_date_and_are_frozen():
    check_in, check_out = valid_dates()
    with pytest.raises(ValidationError):
        FlyAIHotelSearchRequest(
            city_name="杭州",
            check_in=datetime.fromisoformat(f"{check_in}T00:00:00"),
            check_out=check_out,
        )
    hotel = FlyAIHotel(hotel_id="1", name="酒店")
    with pytest.raises((ValidationError, TypeError)):
        hotel.name = "其他"
