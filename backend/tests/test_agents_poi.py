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
    assert len(result.sources) == 1


@pytest.mark.asyncio
async def test_lodging_ignores_bad_source_metadata_after_first_ten_pois():
    pois = [poi(name=f"酒店{i}") for i in range(10)] + [poi(name="尾部坏数据", retrieved_at="not-a-date")]
    result = await LodgingAgent(FakePoiClient({("住宿服务", "杭州1日区域"): pois})).run(
        request(), areas(), REQUEST_ID, REQUEST_ID
    )

    assert result.status is AgentStatus.success
    assert len(result.data.candidates) == 10
    assert len(result.sources) == 1


@pytest.mark.asyncio
async def test_lodging_malformed_area_degrades_without_keyerror():
    result = await LodgingAgent(FakePoiClient()).run(
        request(), ({"day": 1},), REQUEST_ID, REQUEST_ID
    )

    assert result.status is AgentStatus.degraded
    assert result.data.candidates == ()
    assert result.missing_fields == ("lodging_candidates",)


@pytest.mark.asyncio
async def test_lodging_sources_dedupe_by_stable_metadata_and_keep_first_source():
    first = poi(retrieved_at=datetime(2026, 8, 21, tzinfo=timezone.utc))
    second = poi(name="另一家酒店", retrieved_at=datetime(2026, 8, 22, tzinfo=timezone.utc))
    client = FakePoiClient({("住宿服务", "杭州1日区域"): [first, second]})

    result = await LodgingAgent(client).run(request(), areas(), REQUEST_ID, REQUEST_ID)

    assert result.status is AgentStatus.success
    assert len(result.sources) == 1
    assert result.sources[0].retrieved_at == datetime(2026, 8, 21, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_lodging_empty_areas_uses_destination_fallback_area():
    client = FakePoiClient()
    result = await LodgingAgent(client).run(request(), (), REQUEST_ID, REQUEST_ID)

    assert result.status is AgentStatus.degraded
    assert result.data.recommended_area == "杭州"
    assert client.calls == [("住宿服务", "杭州")]


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
@pytest.mark.parametrize("category", ["餐饮服务", "其他", ""])
async def test_lodging_rejects_non_lodging_category(category):
    client = FakePoiClient({("住宿服务", "杭州1日区域"): [poi(category=category)]})

    result = await LodgingAgent(client).run(request(), areas(), REQUEST_ID, REQUEST_ID)

    assert result.status is AgentStatus.degraded
    assert result.data.candidates == ()
    assert result.missing_fields == ("lodging_candidates",)


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["住宿服务", "其他", ""])
async def test_food_rejects_non_food_category(category):
    client = FakePoiClient({("餐饮服务", "杭州1日区域"): [poi(name="餐馆", category=category)]})

    result = await FoodAgent(client).run(request(days=1), areas(days=1), REQUEST_ID, REQUEST_ID)

    if category == "餐饮服务":
        assert result.status is AgentStatus.success
        assert result.data.daily_food[0].candidates
    else:
        assert result.status is AgentStatus.degraded
        assert result.data.daily_food[0].candidates == ()
        assert result.missing_fields == ("food_day_1_candidates",)


@pytest.mark.asyncio
async def test_poi_agents_use_first_area_and_expected_search_arguments():
    client = FakePoiClient({("住宿服务", "杭州1日区域"): [poi()]})

    result = await LodgingAgent(client).run(request(), areas(), REQUEST_ID, REQUEST_ID)

    assert client.calls == [("住宿服务", "杭州1日区域")]
    assert result.data.recommended_area == "杭州1日区域"


@pytest.mark.asyncio
async def test_poi_source_metadata_is_preserved_and_malformed_metadata_degrades():
    updated = datetime(2026, 8, 20, tzinfo=timezone.utc)
    client = FakePoiClient({
        ("住宿服务", "杭州1日区域"): [poi(source_updated_at=updated, data_status="cached")],
    })
    result = await LodgingAgent(client).run(request(), areas(), REQUEST_ID, REQUEST_ID)

    assert result.status is AgentStatus.success
    assert result.sources[0].data_status is DataStatus.cached
    assert result.sources[0].source_updated_at == updated
    assert result.sources[0].retrieved_at == datetime(2026, 8, 21, tzinfo=timezone.utc)

    bad = FakePoiClient({
        ("住宿服务", "杭州1日区域"): [poi(retrieved_at="not-a-date")],
    })
    result = await LodgingAgent(bad).run(request(), areas(), REQUEST_ID, REQUEST_ID)
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
async def test_food_short_daily_areas_is_partial_with_missing_area_day():
    client = FakePoiClient({("餐饮服务", "杭州1日区域"): [poi(name="餐馆", category="餐饮服务")]})

    result = await FoodAgent(client).run(request(days=2), areas(days=1), REQUEST_ID, REQUEST_ID)

    assert result.status is AgentStatus.partial
    assert [item.day for item in result.data.daily_food] == [1]
    assert result.missing_fields == ("food_day_2_area",)
    assert client.calls == [("餐饮服务", "杭州1日区域")]


@pytest.mark.asyncio
async def test_food_empty_daily_areas_is_degraded_with_destination_fallback():
    result = await FoodAgent(FakePoiClient()).run(request(days=2), (), REQUEST_ID, REQUEST_ID)

    assert result.status is AgentStatus.degraded
    assert len(result.data.daily_food) == 1
    assert result.data.daily_food[0].day == 1
    assert result.data.daily_food[0].area == "杭州"
    assert result.data.daily_food[0].candidates == ()
    assert result.missing_fields == ("food_daily_areas",)


@pytest.mark.asyncio
async def test_food_malformed_area_is_controlled_degradation():
    result = await FoodAgent(FakePoiClient()).run(request(), ({"day": 1},), REQUEST_ID, REQUEST_ID)

    assert result.status is AgentStatus.degraded
    assert result.data.daily_food[0].area == "未知区域"
    assert result.data.daily_food[0].candidates == ()
    assert "KeyError" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_poi_agents_preserve_request_and_trace_ids_and_reject_mismatch():
    valid = str(uuid4())
    result = await LodgingAgent(FakePoiClient()).run(request(), areas(), valid, valid)
    assert result.request_id == valid
    assert result.trace_id == valid
    with pytest.raises(ValueError, match="请求追踪标识无效"):
        await FoodAgent(FakePoiClient()).run(request(), areas(), valid, str(uuid4()))
