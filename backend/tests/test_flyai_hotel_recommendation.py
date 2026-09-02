from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.flyai_hotel import FlyAIHotel, FlyAIHotelSearchRequest
from app.services.flyai_hotel_client import FlyAIHotelError
from app.services.flyai_hotel_recommendation import (
    FlyAIHotelRecommendationService,
    HotelRecommendationResults,
)
from app.services.resilience import ExternalServiceUnavailable


class FakeFlyAIClient:
    def __init__(self, hotels=None, error=None):
        self.hotels = hotels or []
        self.error = error
        self.requests = []

    async def search_hotels(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.hotels


class FakeAmapClient:
    def __init__(self, pois=None, error=None):
        self.pois = pois or []
        self.error = error
        self.calls = []

    async def search_poi(self, keywords, city):
        self.calls.append((keywords, city))
        if self.error:
            raise self.error
        return self.pois


def request():
    check_in = date.today() + timedelta(days=1)
    return FlyAIHotelSearchRequest(
        city_name="杭州",
        check_in=check_in,
        check_out=check_in + timedelta(days=1),
    )


def flyai(name, hotel_id, price=None, *, score=4.5):
    return FlyAIHotel(
        hotel_id=hotel_id,
        name=name,
        price=price,
        score=score,
        star=4,
        main_pic="https://example.com/main.jpg",
        detail_url="https://example.com/hotel",
    )


def amap(name, address, location="120.1,30.2", retrieved_at=None):
    return {
        "name": name,
        "address": address,
        "location": location,
        "category": "住宿服务",
        "retrieved_at": retrieved_at or datetime(2026, 8, 25, tzinfo=timezone.utc),
    }


@pytest.mark.asyncio
async def test_recommendation_merges_strict_name_match_and_calls_expected_poi_query():
    flyai_client = FakeFlyAIClient([flyai("西湖饭店", "f1", 280)])
    amap_client = FakeAmapClient([amap("西湖饭店。", "西湖边")])

    result = await FlyAIHotelRecommendationService(flyai_client, amap_client).recommend(request())

    assert isinstance(result, HotelRecommendationResults)
    assert result[0].match_status == "matched"
    assert result[0].flyai_price == Decimal("280")
    assert result[0].amap_address == "西湖边"
    assert result[0].amap_location == "120.1,30.2"
    assert result[0].price_source == "flyai"
    assert result[0].poi_source == "amap"
    assert amap_client.calls == [("住宿服务", "杭州")]


@pytest.mark.asyncio
async def test_matched_result_with_only_flyai_identity_keeps_real_poi_without_fabricating_fields():
    flyai_client = FakeFlyAIClient([FlyAIHotel(hotel_id="f1", name="仅名称酒店")])
    amap_client = FakeAmapClient([amap("仅名称酒店", "真实地址")])

    result = await FlyAIHotelRecommendationService(flyai_client, amap_client).recommend(request())

    item = result[0]
    assert item.match_status == "matched"
    assert item.hotel_name == "仅名称酒店"
    assert item.amap_address == "真实地址"
    assert item.poi_source == "amap"
    assert item.flyai_price is None
    assert item.flyai_score is None
    assert item.flyai_star is None
    assert item.flyai_main_pic is None
    assert item.detail_url is None
    assert item.price_source is None


@pytest.mark.asyncio
async def test_service_uses_only_injected_flyai_and_amap_clients_not_top_client():
    flyai_client = FakeFlyAIClient([flyai("酒店", "f1", 280)])
    amap_client = FakeAmapClient([amap("酒店", "地址")])

    class TopClientThatMustNotBeCalled:
        def __getattr__(self, name):
            raise AssertionError(f"不应调用 TOP client: {name}")

    service = FlyAIHotelRecommendationService(flyai_client, amap_client)
    assert not hasattr(service, "_top_client")
    await service.recommend(request())
    assert flyai_client.requests and amap_client.calls


@pytest.mark.asyncio
async def test_unmatched_results_do_not_copy_fields_between_sources():
    flyai_client = FakeFlyAIClient([flyai("飞猪酒店", "f1", 280)])
    amap_client = FakeAmapClient([amap("高德酒店", "高德地址")])

    result = await FlyAIHotelRecommendationService(flyai_client, amap_client).recommend(request())

    assert result[0].match_status == "flyai_only"
    assert result[0].flyai_price == Decimal("280")
    assert result[0].amap_address is None
    assert result[0].poi_source is None
    assert result[1].match_status == "poi_only"
    assert result[1].amap_address == "高德地址"
    assert result[1].flyai_price is None
    assert result[1].price_source is None


@pytest.mark.asyncio
async def test_scores_sort_descending_with_missing_scores_last():
    # 高分酒店定价更高，旧逻辑按价格升序会得到相反顺序，用于区分排序依据。
    flyai_client = FakeFlyAIClient([
        flyai("无评分", "f0", score=None),
        flyai("低分便宜", "f1", 100, score=4.0),
        flyai("高分贵", "f2", 500, score=4.9),
    ])
    amap_client = FakeAmapClient([])

    result = await FlyAIHotelRecommendationService(flyai_client, amap_client).recommend(request())

    assert [item.hotel_name for item in result] == ["高分贵", "低分便宜", "无评分"]


@pytest.mark.asyncio
async def test_amap_failure_keeps_flyai_results_without_fabricating_poi():
    flyai_client = FakeFlyAIClient([flyai("酒店", "f1", 280)])
    amap_client = FakeAmapClient(error=ExternalServiceUnavailable("上游不可用"))

    result = await FlyAIHotelRecommendationService(flyai_client, amap_client).recommend(request())

    assert result[0].match_status == "flyai_only"
    assert result[0].amap_address is None
    assert result[0].amap_location is None
    assert result[0].flyai_price == Decimal("280")


@pytest.mark.asyncio
async def test_flyai_failure_keeps_amap_results_without_fake_flyai_fields():
    flyai_error = FlyAIHotelError("TIMEOUT")
    service = FlyAIHotelRecommendationService(
        FakeFlyAIClient(error=flyai_error), FakeAmapClient([amap("酒店", "地址")])
    )

    result = await service.recommend(request())

    assert result[0].match_status == "poi_only"
    assert result[0].hotel_name == "酒店"
    assert result[0].amap_address == "地址"
    assert result[0].flyai_price is None


@pytest.mark.asyncio
async def test_source_query_times_are_retained_separately():
    amap_time = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
    flyai_client = FakeFlyAIClient([flyai("酒店", "f1", 280)])
    amap_client = FakeAmapClient([amap("酒店", "地址", retrieved_at=amap_time)])

    result = await FlyAIHotelRecommendationService(flyai_client, amap_client).recommend(request())

    assert result.flyai_retrieved_at.tzinfo == timezone.utc
    assert result.amap_retrieved_at == amap_time
