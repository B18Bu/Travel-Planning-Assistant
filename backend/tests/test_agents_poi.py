from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.agents.food import FoodAgent
from app.agents.lodging import LodgingAgent
from app.models.travel import (
    AgentStatus,
    DailyItinerary,
    DataStatus,
    PoiCandidate,
    SourceType,
    TimedAttraction,
    TravelPlanRequest,
)
from app.services.resilience import ExternalServiceUnavailable

REQUEST_ID = str(uuid4())


def request(days=3):
    return TravelPlanRequest(origin="上海", destination="杭州", departure_date=date(2026, 9, 1), travelers=2, days=days)


def poi(name="西湖酒店", category="住宿服务", **extra):
    return {
        "name": name, "address": "西湖边", "location": "120.1,30.2", "category": category,
        "tags": ["亲子", "便利"], "data_status": "realtime",
        "source_updated_at": None, "retrieved_at": datetime(2026, 8, 21, tzinfo=timezone.utc), **extra,
    }


class FakePoiClient:
    def __init__(self, results=None, error=None, nearby_results=None):
        self.results = results or {}
        self.error = error
        self.calls = []
        self.nearby_results = nearby_results or {}
        self.nearby_calls = []

    async def search_poi(self, keywords, area):
        self.calls.append((keywords, area))
        if self.error:
            raise self.error
        return self.results.get((keywords, area), [])

    async def search_nearby_poi(self, keywords, location, radius):
        self.nearby_calls.append((keywords, location, radius))
        if self.error:
            raise self.error
        return self.nearby_results.get((keywords, location, radius), [])


def attraction(slot, name, location="120.1,30.2", address="景区地址"):
    return TimedAttraction(
        time_slot=slot,
        poi=PoiCandidate(name=name, address=address, location=location, category="旅游景点", tags=(), source_ids=("route",)),
        suggested_duration_minutes=60,
    )


def itinerary(day, *attractions):
    return DailyItinerary(day=day, weather_reminder="注意天气", attractions=tuple(attractions))


@pytest.mark.asyncio
async def test_lodging_accepts_hierarchical_category_and_preserves_source():
    client = FakePoiClient({("住宿服务", "杭州"): [poi(category="住宿服务;宾馆;连锁")]})
    result = await LodgingAgent(client).run(request(), (type("Area", (), {"day": 1, "area": "杭州1日区域"})(),), REQUEST_ID, REQUEST_ID)
    assert result.status is AgentStatus.success
    assert result.data.candidates[0].poi.category == "住宿服务"
    assert result.sources[0].type is SourceType.poi_api
    assert result.sources[0].data_status is DataStatus.realtime


@pytest.mark.asyncio
async def test_lodging_searches_poi_with_destination_not_formatted_area():
    client = FakePoiClient({("住宿服务", "杭州"): [poi()]})
    result = await LodgingAgent(client).run(
        request(),
        (type("Area", (), {"day": 1, "area": "浙江省杭州市"})(),),
        REQUEST_ID, REQUEST_ID,
    )
    assert result.status is AgentStatus.success
    assert client.calls == [("住宿服务", "杭州")]
    assert result.data.recommended_area == "浙江省杭州市"


@pytest.mark.asyncio
async def test_lodging_empty_poi_degrades_without_fabricating_businesses():
    result = await LodgingAgent(FakePoiClient()).run(request(), (type("Area", (), {"day": 1, "area": "杭州"})(),), REQUEST_ID, REQUEST_ID)
    assert result.status is AgentStatus.degraded
    assert result.data.candidates == ()
    assert result.data.filter_suggestions
    assert any("官方" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_lodging_external_failure_is_controlled():
    result = await LodgingAgent(FakePoiClient(error=ExternalServiceUnavailable("upstream"))).run(
        request(), (type("Area", (), {"day": 1, "area": "杭州"})(),), REQUEST_ID, REQUEST_ID
    )
    assert result.status is AgentStatus.degraded
    assert "upstream" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_food_uses_morning_and_evening_attraction_coordinates():
    client = FakePoiClient(nearby_results={
        ("餐饮服务", "120.1,30.2", 2000): [poi(name="午餐馆", category="餐饮服务")],
        ("餐饮服务", "121.2,31.2", 2000): [poi(name="晚餐馆", category="餐饮服务")],
    })
    daily = itinerary(1, attraction("上午", "上午景区", "120.1,30.2"), attraction("傍晚", "傍晚景区", "121.2,31.2"))
    result = await FoodAgent(client).run(request(days=1), (daily,), REQUEST_ID, REQUEST_ID)
    assert client.nearby_calls == [("餐饮服务", "120.1,30.2", 2000), ("餐饮服务", "121.2,31.2", 2000)]
    assert [(item.meal_period, item.nearby_attraction_name) for item in result.data.daily_food] == [("午餐", "上午景区"), ("晚餐", "傍晚景区")]
    assert [item.candidates[0].poi.name for item in result.data.daily_food] == ["午餐馆", "晚餐馆"]
    assert [item.area for item in result.data.daily_food] == ["景区地址", "景区地址"]


@pytest.mark.asyncio
async def test_food_long_attraction_address_does_not_fail_and_keeps_candidate_address():
    long_address = "景区地址" * 40
    client = FakePoiClient(nearby_results={
        ("餐饮服务", "120.1,30.2", 2000): [poi(name="长地址餐馆", category="餐饮服务")],
    })
    result = await FoodAgent(client).run(
        request(days=1), (itinerary(1, attraction("上午", "上午景区", address=long_address)),), REQUEST_ID, REQUEST_ID
    )
    assert result.status is AgentStatus.partial
    lunch = result.data.daily_food[0]
    assert lunch.area == request().destination
    assert lunch.candidates[0].poi.address == "西湖边"


@pytest.mark.asyncio
async def test_food_long_external_attraction_name_is_controlled():
    long_name = "超长餐馆名称" * 30
    client = FakePoiClient(nearby_results={
        ("餐饮服务", "120.1,30.2", 2000): [poi(name=long_name, category="餐饮服务")],
    })
    result = await FoodAgent(client).run(
        request(days=1), (itinerary(1, attraction("上午", "景区")),), REQUEST_ID, REQUEST_ID
    )
    assert result.status is AgentStatus.partial
    assert len(result.data.daily_food[0].candidates[0].poi.name) <= 100
    assert len(result.data.daily_food[0].nearby_attraction_name) <= 100
    assert "food_day_1_lunch_candidate_name" in result.missing_fields


@pytest.mark.asyncio
async def test_food_dinner_falls_back_to_afternoon():
    client = FakePoiClient(nearby_results={("餐饮服务", "120.1,30.2", 2000): [poi(name="晚餐馆", category="餐饮服务")]})
    result = await FoodAgent(client).run(request(days=1), (itinerary(1, attraction("上午", "上午景区", "120.1,30.2"), attraction("下午", "下午景区", "120.1,30.2")),), REQUEST_ID, REQUEST_ID)
    assert client.nearby_calls == [("餐饮服务", "120.1,30.2", 2000), ("餐饮服务", "120.1,30.2", 2000)]
    assert result.data.daily_food[1].nearby_attraction_name == "下午景区"


@pytest.mark.asyncio
async def test_food_missing_location_does_not_call_nearby_api():
    client = FakePoiClient()
    result = await FoodAgent(client).run(request(days=1), (itinerary(1, attraction("上午", "上午景区", None)),), REQUEST_ID, REQUEST_ID)
    assert client.nearby_calls == []
    assert result.data.daily_food[0].candidates == ()
    assert {"food_day_1_dinner_attraction", "food_day_1_dinner_location", "food_day_1_dinner_candidates"}.issubset(result.missing_fields)
    assert {"food_day_1_lunch_location", "food_day_1_lunch_candidates"}.issubset(result.missing_fields)


@pytest.mark.asyncio
async def test_food_filters_non_food_and_keeps_first_valid_candidate():
    client = FakePoiClient(nearby_results={("餐饮服务", "120.1,30.2", 2000): [
        poi(name="商场", category="购物服务"), poi(name="真实餐厅", category="餐饮服务"), poi(name="第二餐厅", category="餐饮服务")
    ]})
    result = await FoodAgent(client).run(request(days=1), (itinerary(1, attraction("上午", "西湖")),), REQUEST_ID, REQUEST_ID)
    candidate = result.data.daily_food[0].candidates[0]
    assert candidate.poi.name == "真实餐厅"
    assert len(result.data.daily_food[0].candidates) == 1
    assert all(term not in result.model_dump_json() for term in ("rating", "score", "recommendation", "招牌菜"))


@pytest.mark.asyncio
async def test_food_nearby_empty_creates_plan_and_official_verification_hint():
    result = await FoodAgent(FakePoiClient()).run(request(days=1), (itinerary(1, attraction("上午", "西湖")),), REQUEST_ID, REQUEST_ID)
    assert result.data.daily_food[0].candidates == ()
    assert result.data.daily_food[0].filter_suggestions
    assert "官方" in result.data.daily_food[0].filter_suggestions[0]
    assert result.status is AgentStatus.degraded


@pytest.mark.asyncio
async def test_food_sources_are_stably_deduplicated():
    client = FakePoiClient(nearby_results={("餐饮服务", "120.1,30.2", 2000): [poi(name="餐厅", category="餐饮服务")]})
    result = await FoodAgent(client).run(request(days=1), (itinerary(1, attraction("上午", "西湖"), attraction("傍晚", "西湖")),), REQUEST_ID, REQUEST_ID)
    assert len(result.sources) == 1
    assert result.sources[0].retrieved_at == datetime(2026, 8, 21, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_food_marks_missing_itinerary_day_without_claiming_success():
    client = FakePoiClient(nearby_results={("餐饮服务", "120.1,30.2", 2000): [poi(name="餐厅", category="餐饮服务")]})
    itineraries = (
        itinerary(1, attraction("上午", "第一天景区"), attraction("傍晚", "第一天景区")),
        itinerary(3, attraction("上午", "第三天景区"), attraction("傍晚", "第三天景区")),
    )

    result = await FoodAgent(client).run(request(days=3), itineraries, REQUEST_ID, REQUEST_ID)

    assert result.status is AgentStatus.partial
    assert "food_day_2_itinerary" in result.missing_fields
    assert {"food_day_2_lunch_itinerary", "food_day_2_dinner_itinerary"}.issubset(result.missing_fields)
    assert [plan.day for plan in result.data.daily_food] == [1, 1, 2, 2, 3, 3]
    assert [(plan.day, plan.meal_period) for plan in result.data.daily_food[2:4]] == [(2, "午餐"), (2, "晚餐")]
    assert all(not plan.candidates for plan in result.data.daily_food[2:4])


@pytest.mark.asyncio
async def test_food_invalid_itineraries_type_is_controlled_degradation():
    result = await FoodAgent(FakePoiClient()).run(request(days=2), 1, REQUEST_ID, REQUEST_ID)
    assert result.status is AgentStatus.degraded
    assert len(result.data.daily_food) == 4
    assert result.missing_fields == ("food_daily_itineraries",)


@pytest.mark.asyncio
async def test_food_empty_itineraries_generates_both_meals_for_each_request_day():
    client = FakePoiClient()
    result = await FoodAgent(client).run(request(days=3), (), REQUEST_ID, REQUEST_ID)
    assert result.status is AgentStatus.degraded
    assert [(plan.day, plan.meal_period) for plan in result.data.daily_food] == [
        (1, "午餐"), (1, "晚餐"), (2, "午餐"), (2, "晚餐"), (3, "午餐"), (3, "晚餐")
    ]
    assert set(result.missing_fields) == {
        "food_day_1_lunch_itinerary", "food_day_1_dinner_itinerary",
        "food_day_2_lunch_itinerary", "food_day_2_dinner_itinerary",
        "food_day_3_lunch_itinerary", "food_day_3_dinner_itinerary",
    }
    assert client.nearby_calls == []


@pytest.mark.asyncio
async def test_food_complete_schedule_success_and_partial_when_one_meal_missing():
    client = FakePoiClient(nearby_results={("餐饮服务", "120.1,30.2", 2000): [poi(name="餐厅", category="餐饮服务")]})
    complete = await FoodAgent(client).run(request(days=1), (itinerary(1, attraction("上午", "西湖"), attraction("傍晚", "西湖")),), REQUEST_ID, REQUEST_ID)
    assert complete.status is AgentStatus.success
    partial = await FoodAgent(client).run(request(days=1), (itinerary(1, attraction("上午", "西湖")),), REQUEST_ID, REQUEST_ID)
    assert partial.status is AgentStatus.partial


@pytest.mark.asyncio
async def test_food_preserves_request_and_trace_ids_and_rejects_mismatch():
    valid = str(uuid4())
    result = await FoodAgent(FakePoiClient()).run(request(), (), valid, valid)
    assert result.request_id == valid and result.trace_id == valid
    with pytest.raises(ValueError, match="请求追踪标识无效"):
        await FoodAgent(FakePoiClient()).run(request(), (), valid, str(uuid4()))
