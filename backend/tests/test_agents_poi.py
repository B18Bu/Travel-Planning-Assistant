from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.agents.food import FoodAgent
from app.agents.lodging import LodgingAgent
from app.models.travel import AgentStatus, DailyArea, DataStatus, SourceType, TravelPlanRequest
from app.services.resilience import ExternalServiceUnavailable


REQUEST_ID = str(uuid4())


def request(days=3):
    return TravelPlanRequest(
        origin="上海",
        destination="杭州",
        departure_date=date(2026, 9, 1),
        travelers=2,
        days=days,
    )


def areas(days=3):
    return tuple(DailyArea(day=i, area=f"杭州{i}日区域") for i in range(1, days + 1))


def poi(name="西湖酒店", category="住宿服务", **extra):
    return {
        "name": name,
        "address": "西湖边",
        "location": "120.1,30.2",
        "category": category,
        "tags": ["亲子", "便利"],
        "data_status": "realtime",
        "source_updated_at": None,
        "retrieved_at": datetime(2026, 8, 21, tzinfo=timezone.utc),
        **extra,
    }


class FakePoiClient:
    def __init__(self, results=None, error=None):
        self.results = results or {}
        self.error = error
        self.calls = []

    async def search_poi(self, keywords, area):
        self.calls.append((keywords, area))
        if self.error:
            raise self.error
        return self.results.get((keywords, area), [])


@pytest.mark.asyncio
async def test_lodging_maps_only_whitelisted_poi_facts_and_limits_ten():
    client = FakePoiClient({("住宿服务", "杭州1日区域"): [poi(name=f"酒店{i}") for i in range(12)]})
    result = await LodgingAgent(client).run(request(), areas(), REQUEST_ID, REQUEST_ID)

    assert result.status is AgentStatus.success
    assert len(result.data.candidates) == 10
    candidate = result.data.candidates[0]
    assert candidate.poi.name == "酒店0"
    assert candidate.poi.address == "西湖边"
    assert candidate.poi.location == "120.1,30.2"
    assert candidate.poi.category == "住宿服务"
    assert candidate.poi.tags == ("亲子", "便利")
    assert candidate.poi.source_ids == ("amap:lodging",)
    assert set(candidate.model_fields_set) <= {"poi", "facilities", "suitable_for", "commute_note", "recommendation_reason"}
    assert result.sources[0].name == "高德地图"
    assert result.sources[0].type is SourceType.poi_api
    assert result.sources[0].data_status is DataStatus.realtime
    assert result.sources[0].retrieved_at is not None


@pytest.mark.asyncio
async def test_lodging_empty_poi_degrades_without_fabricating_businesses():
    result = await LodgingAgent(FakePoiClient()).run(request(), areas(), REQUEST_ID, REQUEST_ID)

    assert result.status is AgentStatus.degraded
    assert result.data.candidates == ()
    assert result.data.filter_suggestions
    assert result.missing_fields == ("lodging_candidates",)
    assert any("官方" in warning or "授权" in warning for warning in result.warnings)
    assert "酒店" not in "".join(candidate.poi.name for candidate in result.data.candidates)


@pytest.mark.asyncio
async def test_lodging_external_or_malformed_payload_is_controlled_degradation():
    client = FakePoiClient(error=ExternalServiceUnavailable("upstream detail"))
    result = await LodgingAgent(client).run(request(), areas(), REQUEST_ID, REQUEST_ID)

    assert result.status is AgentStatus.degraded
    assert result.data.candidates == ()
    assert "upstream detail" not in result.model_dump_json()

    malformed = FakePoiClient({("住宿服务", "杭州1日区域"): [{"name": "坏数据"}]})
    result = await LodgingAgent(malformed).run(request(), areas(), REQUEST_ID, REQUEST_ID)
    assert result.status is AgentStatus.degraded
    assert result.data.candidates == ()


@pytest.mark.asyncio
async def test_food_calls_each_area_in_order_and_keeps_empty_days():
    client = FakePoiClient({
        ("餐饮服务", "杭州1日区域"): [poi(name="杭帮菜馆", category="餐饮服务")],
        ("餐饮服务", "杭州3日区域"): [poi(name="素食馆", category="餐饮服务")],
    })
    result = await FoodAgent(client).run(request(), areas(), REQUEST_ID, REQUEST_ID)

    assert client.calls == [("餐饮服务", "杭州1日区域"), ("餐饮服务", "杭州2日区域"), ("餐饮服务", "杭州3日区域")]
    assert result.status is AgentStatus.partial
    assert [item.day for item in result.data.daily_food] == [1, 2, 3]
    assert result.data.daily_food[1].candidates == ()
    assert result.data.daily_food[1].filter_suggestions
    assert result.missing_fields == ("food_day_2_candidates",)
    assert all("price" not in item.model_dump_json() for item in result.data.daily_food)


@pytest.mark.asyncio
async def test_food_all_empty_degrades_with_all_days_present():
    result = await FoodAgent(FakePoiClient()).run(request(days=2), areas(days=2), REQUEST_ID, REQUEST_ID)

    assert result.status is AgentStatus.degraded
    assert len(result.data.daily_food) == 2
    assert result.missing_fields == ("food_day_1_candidates", "food_day_2_candidates")


@pytest.mark.asyncio
async def test_poi_agents_preserve_request_and_trace_ids_and_reject_mismatch():
    valid = str(uuid4())
    result = await LodgingAgent(FakePoiClient()).run(request(), areas(), valid, valid)
    assert result.request_id == valid
    assert result.trace_id == valid
    with pytest.raises(ValueError, match="请求追踪标识无效"):
        await FoodAgent(FakePoiClient()).run(request(), areas(), valid, str(uuid4()))
