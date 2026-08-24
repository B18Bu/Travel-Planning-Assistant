from datetime import date, datetime, timezone
from uuid import uuid4
from typing import get_type_hints

import pytest

from app.models.travel import (
    AgentResult,
    AgentStatus,
    DataStatus,
    ErrorDetail,
    DailyArea,
    DailyWeather,
    RoutePlanData,
    SourceType,
    WeatherPlanData,
    WeatherRiskLevel,
)
from app.services.resilience import ExternalServiceUnavailable
from app.agents.route import RouteAgent
from app.agents.weather import WeatherAgent


class FakeWeatherClient:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def daily_forecast(self, location_id, start, days):
        self.calls.append((location_id, start, days))
        return self.result


class FakeAmapClient:
    def __init__(self, geocodes=None, route=None, routes=None, nearby_results=None, nearby_errors=None, text_results=None, error=None):
        self.geocodes = geocodes or {}
        self.route = route
        self.routes = routes or {}
        self.nearby_results = nearby_results or {}
        self.nearby_errors = nearby_errors or {}
        self.text_results = text_results or {}
        self.error = error
        self.calls = []
        self.nearby_calls = []

    async def geocode(self, address):
        self.calls.append(("geocode", address))
        if self.error:
            raise self.error
        return self.geocodes[address]

    async def driving_route(self, origin, destination):
        self.calls.append(("driving_route", origin, destination))
        if self.error:
            raise self.error
        return self.routes.get((origin, destination), self.route)

    async def search_poi(self, keywords, city):
        self.calls.append(("search_poi", keywords, city))
        if self.error:
            raise self.error
        return self.text_results.get((keywords, city), [])

    async def search_nearby_poi(self, keywords, location, radius):
        self.calls.append(("search_nearby_poi", keywords, location, radius))
        self.nearby_calls.append((keywords, location, radius))
        if self.error:
            raise self.error
        nearby_error = self.nearby_errors.get((keywords, location, radius))
        if nearby_error:
            raise nearby_error
        return self.nearby_results.get((keywords, location, radius), [])


class DualCapabilityClient(FakeWeatherClient, FakeAmapClient):
    def __init__(self, result, geocodes):
        FakeWeatherClient.__init__(self, result)
        FakeAmapClient.__init__(self, geocodes=geocodes)


def request(days=3):
    from app.models.travel import TravelPlanRequest

    return TravelPlanRequest(
        origin="上海",
        destination="杭州",
        departure_date=date(2026, 9, 1),
        travelers=2,
        days=days,
    )


def source_metadata(source_type, status="realtime", updated=None):
    return {
        "data_status": status,
        "source_updated_at": updated,
        "retrieved_at": datetime(2026, 8, 21, tzinfo=timezone.utc),
    }


def weather_payload(days=3, condition="晴", status="realtime", updated=None):
    return {
        **source_metadata(SourceType.weather_api, status, updated),
        "daily": tuple(
            {
                "date": date(2026, 9, day),
                "condition": condition,
                "temp_min": 20,
                "temp_max": 30,
            }
            for day in range(1, days + 1)
        ),
    }


def ids():
    value = str(uuid4())
    return {"request_id": value, "trace_id": value}


def attraction(name, category="风景名胜", location="120,30"):
    return {
        "name": name,
        "address": f"{name}地址",
        "location": location,
        "category": category,
        **source_metadata(SourceType.poi_api),
    }


def weather_result(days=3, conditions=None):
    conditions = conditions or ["晴"] * days
    request_ids = ids()
    daily = tuple(
        DailyWeather(
            date=date(2026, 9, day),
            condition=conditions[day - 1],
            temp_min=20,
            temp_max=30,
            risk_level=WeatherRiskLevel.high if conditions[day - 1] == "高温" else WeatherRiskLevel.low,
            travel_reminder="高温优先室内文化场所" if conditions[day - 1] == "高温" else "天气适宜出行",
            indoor_preferred=conditions[day - 1] == "高温",
        )
        for day in range(1, days + 1)
    )
    return AgentResult(
        agent="weather", status=AgentStatus.success, summary="天气规划结果",
        data=WeatherPlanData(destination="杭州", daily=daily),
        request_id=request_ids["request_id"], trace_id=request_ids["trace_id"],
    )


@pytest.mark.parametrize(
    ("condition", "reminder_phrases"),
    [
        ("暴雨", ("减少户外暴露", "关注官方预警")),
        ("台风", ("减少户外暴露", "关注官方预警")),
        ("强对流", ("减少户外暴露", "关注官方预警")),
        ("高温", ("防晒补水", "避免长时间户外暴晒")),
    ],
)
def test_weather_agent_generates_specific_guidance_for_each_high_risk(condition, reminder_phrases):
    agent = WeatherAgent(
        weather_client=FakeWeatherClient(weather_payload(days=1, condition=condition)),
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
    )

    result = __import__("asyncio").run(agent.run(request(days=1), **ids()))

    daily = result.data.daily[0]
    assert daily.risk_level is WeatherRiskLevel.high
    assert daily.indoor_preferred is True
    assert all(phrase in daily.travel_reminder for phrase in reminder_phrases)
    assert all(phrase in result.constraints[0] for phrase in reminder_phrases)
    assert all(phrase in result.warnings[0] for phrase in reminder_phrases)


def test_weather_agent_generates_low_risk_weather_change_guidance():
    agent = WeatherAgent(
        weather_client=FakeWeatherClient(weather_payload(days=1, condition="晴")),
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
    )

    result = __import__("asyncio").run(agent.run(request(days=1), **ids()))

    daily = result.data.daily[0]
    assert daily.risk_level is WeatherRiskLevel.low
    assert daily.indoor_preferred is False
    assert "关注天气变化" in daily.travel_reminder
    assert result.constraints == ()
    assert result.warnings == ()


@pytest.mark.parametrize(
    "risk_word, reminder_fragment",
    [
        ("暴雨", "减少户外暴露"),
        ("台风", "减少户外暴露"),
        ("强对流", "减少户外暴露"),
        ("高温", "防晒补水"),
    ],
)
def test_weather_agent_marks_each_required_risk_word_high(risk_word, reminder_fragment):
    agent = WeatherAgent(
        weather_client=FakeWeatherClient(weather_payload(days=1, condition=risk_word)),
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
    )

    result = __import__("asyncio").run(agent.run(request(days=1), **ids()))

    assert result.status is AgentStatus.success
    assert result.data.daily[0].risk_level is WeatherRiskLevel.high
    assert reminder_fragment in result.data.daily[0].travel_reminder
    assert reminder_fragment in result.constraints[0]


def test_weather_agent_marks_heavy_rain_high_and_adds_deterministic_constraint():
    agent = WeatherAgent(
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
        weather_client=FakeWeatherClient(weather_payload(days=1, condition="暴雨")),
    )

    request_ids = ids()
    result = __import__("asyncio").run(agent.run(request(days=1), **request_ids))

    assert result.status is AgentStatus.success
    assert result.request_id == request_ids["request_id"]
    assert result.trace_id == request_ids["trace_id"]
    assert result.data.daily[0].risk_level is WeatherRiskLevel.high
    assert result.constraints == ("第 1 天：减少户外暴露，关注官方预警；当日优先室内文化场所。",)
    assert agent.amap_client.calls == [("geocode", "杭州")]
    assert agent.weather_client.calls == [("120,30", request(days=1).departure_date, request(days=1).days)]


def test_weather_agent_rejects_empty_daily_as_degraded_without_fabricated_weather():
    agent = WeatherAgent(
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
        weather_client=FakeWeatherClient({**source_metadata(SourceType.weather_api), "daily": ()}),
    )

    result = __import__("asyncio").run(agent.run(request(), **ids()))

    assert result.status is AgentStatus.degraded
    assert result.data.daily == ()
    assert result.missing_fields == ("daily_forecast",)


def test_weather_agent_marks_shortfall_days_to_requested_range():
    agent = WeatherAgent(
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
        weather_client=FakeWeatherClient(weather_payload(days=3)),
    )

    result = __import__("asyncio").run(agent.run(request(days=5), **ids()))

    assert result.status is AgentStatus.partial
    assert result.request_id == result.trace_id
    assert len(result.data.daily) == 3
    assert result.missing_fields == ("daily_forecast_days_4_to_5",)
    assert result.sources[0].type is SourceType.map_api
    assert result.sources[1].type is SourceType.weather_api


def test_weather_agent_preserves_real_weather_source_metadata():
    updated = datetime(2026, 8, 20, tzinfo=timezone.utc)
    agent = WeatherAgent(
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
        weather_client=FakeWeatherClient(weather_payload(status="cached", updated=updated)),
    )

    result = __import__("asyncio").run(agent.run(request(), **ids()))

    source = result.sources[1]
    assert source.type is SourceType.weather_api
    assert source.data_status is DataStatus.cached
    assert source.source_updated_at == updated
    assert source.retrieved_at == datetime(2026, 8, 21, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_route_agent_queries_real_attractions_and_round_trip_routes():
    amap = FakeAmapClient(
        geocodes={
            "上海": {"name": "上海市", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)},
            "杭州": {"name": "杭州市", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)},
        },
        route={"distance_meters": 1000, "duration_minutes": 10, **source_metadata(SourceType.map_api)},
        routes={
            ("121,31", "120,30"): {"distance_meters": 180000, "duration_minutes": 150, **source_metadata(SourceType.map_api)},
            ("120,30", "121,31"): {"distance_meters": 181000, "duration_minutes": 151, **source_metadata(SourceType.map_api)},
        },
        nearby_results={("风景名胜", "120,30", 50000): [attraction(f"景区{i}", location=f"120.{i},30.{i}") for i in range(6)]},
    )
    request_ids = ids()
    result = await RouteAgent(amap).run(request(days=1), weather_result(1), request_ids)

    assert result.status is AgentStatus.success
    assert result.data.round_trip.distance_meters == 361000
    assert [item.poi.name for itinerary in result.data.daily_itineraries for item in itinerary.attractions] == ["景区0", "景区1", "景区2"]
    assert amap.calls[:4] == [("geocode", "上海"), ("geocode", "杭州"), ("driving_route", "121,31", "120,30"), ("driving_route", "120,30", "121,31")]
    assert amap.nearby_calls == [("风景名胜", "120,30", 50000)]
    assert not any(call[0] == "search_poi" for call in amap.calls)
    assert all(item.poi.source_ids == ("amap:attraction",) for itinerary in result.data.daily_itineraries for item in itinerary.attractions)


@pytest.mark.asyncio
async def test_route_agent_uses_destination_nearby_pois_when_text_search_returns_other_city():
    from app.models.travel import TravelPlanRequest

    destination_request = TravelPlanRequest(
        origin="北京",
        destination="成都",
        departure_date=date(2026, 9, 1),
        travelers=2,
        days=1,
    )
    amap = FakeAmapClient(
        geocodes={
            "北京": {"name": "北京市", "location": "116.4074,39.9042", "adcode": "110000", **source_metadata(SourceType.map_api)},
            "成都": {"name": "成都市", "location": "104.066301,30.572961", "adcode": "510100", **source_metadata(SourceType.map_api)},
        },
        routes={
            ("116.4074,39.9042", "104.066301,30.572961"): {"distance_meters": 1800000, "duration_minutes": 1200, **source_metadata(SourceType.map_api)},
        },
        text_results={("风景名胜", "四川省成都市"): [attraction("北京故宫", location="116.397,39.916")]},
        nearby_results={("风景名胜", "104.066301,30.572961", 50000): [attraction("成都景区", location="104.1,30.6")]},
    )

    result = await RouteAgent(amap).run(destination_request, weather_result(1), ids())

    locations = [item.poi.location for itinerary in result.data.daily_itineraries for item in itinerary.attractions]
    assert locations == ["104.1,30.6"]
    assert all(not location.startswith("116.") for location in locations if location)
    assert amap.nearby_calls == [("风景名胜", "104.066301,30.572961", 50000)]
    assert not any(call[0] == "search_poi" for call in amap.calls)


@pytest.mark.asyncio
async def test_route_agent_high_risk_queries_indoor_categories_in_order_and_notes_segments():
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}, ("120,30", "121,31"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={("博物馆", "120,30", 50000): [attraction("博物馆", "科教文化服务;博物馆;博物馆")], ("美术馆", "120,30", 50000): [], ("展馆", "120,30", 50000): []},
    )
    result = await RouteAgent(amap).run(request(days=1), weather_result(1, ["高温"]), ids())

    assert result.status is AgentStatus.partial
    assert amap.nearby_calls == [("博物馆", "120,30", 50000), ("美术馆", "120,30", 50000), ("展馆", "120,30", 50000)]
    assert not any(call[0] == "search_poi" for call in amap.calls)
    assert result.data.daily_itineraries[0].attractions[0].activity_note == "已优先安排室内文化场所，开放时间与预约条件待核验。"


@pytest.mark.asyncio
async def test_route_agent_marks_failed_high_risk_keyword_query_partial_without_exposing_error():
    indoor_pois = [attraction(f"室内景区{i}", "科教文化服务;美术馆;美术馆", f"120.{i},30.{i}") for i in range(3)]
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={
            ("美术馆", "120,30", 50000): indoor_pois,
            ("展馆", "120,30", 50000): [],
        },
        nearby_errors={("博物馆", "120,30", 50000): ExternalServiceUnavailable("上游异常详情")},
    )

    result = await RouteAgent(amap).run(request(days=1), weather_result(1, ["高温"]), ids())

    assert result.status is AgentStatus.partial
    assert "route_day_1_attraction_query_博物馆" in result.missing_fields
    assert "上游异常详情" not in repr(result)
    assert [item.poi.name for item in result.data.daily_itineraries[0].attractions] == ["室内景区0", "室内景区1", "室内景区2"]


@pytest.mark.asyncio
async def test_route_agent_skips_nearby_query_without_destination_location_and_marks_attractions_missing():
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": None, "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", None): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
    )

    result = await RouteAgent(amap).run(request(days=1), weather_result(1), ids())

    assert result.status is AgentStatus.degraded
    assert result.data.daily_itineraries[0].attractions == ()
    assert "attractions" in result.missing_fields
    assert amap.nearby_calls == []


@pytest.mark.asyncio
async def test_route_agent_does_not_consume_unassigned_candidates_across_days():
    pois = [attraction(f"景区{i}", location=f"120.{i},30.{i}") for i in range(4)]
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={("风景名胜", "120,30", 50000): pois},
    )

    result = await RouteAgent(amap).run(request(days=2), weather_result(2), ids())

    assert [item.poi.name for item in result.data.daily_itineraries[0].attractions] == ["景区0", "景区1", "景区2"]
    assert [item.poi.name for item in result.data.daily_itineraries[1].attractions] == ["景区3"]


@pytest.mark.asyncio
async def test_route_agent_skips_malformed_poi_before_slot_assignment():
    bad = attraction("x" * 101, location="120,30")
    valid = attraction("有效景区", location="121,31")
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={("风景名胜", "120,30", 50000): [bad, valid]},
    )

    result = await RouteAgent(amap).run(request(days=1), weather_result(1), ids())

    attractions = result.data.daily_itineraries[0].attractions
    assert [item.poi.name for item in attractions] == ["有效景区"]
    assert attractions[0].time_slot == "上午"
    assert all("x" * 101 not in item.poi.name for item in attractions)


@pytest.mark.asyncio
async def test_route_agent_keeps_valid_poi_when_source_metadata_is_missing():
    valid_poi = {"name": "无来源景区", "address": "景区地址", "location": "120,30", "category": "风景名胜"}
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={("风景名胜", "120,30", 50000): [valid_poi]},
    )

    result = await RouteAgent(amap).run(request(days=1), weather_result(1), ids())

    assert [item.poi.name for item in result.data.daily_itineraries[0].attractions] == ["无来源景区"]
    assert result.data.daily_itineraries[0].attractions[0].poi.source_ids == ("amap:attraction",)
    assert result.status is AgentStatus.partial
    assert "route_day_1_attraction_source_风景名胜" in result.missing_fields


def test_route_agent_weather_type_marks_missing_fields_as_strings():
    annotation = get_type_hints(RouteAgent._weather)["return"]
    assert "tuple[str, ...]" in str(annotation)


@pytest.mark.asyncio
async def test_route_agent_skips_malformed_location_types_before_seen_key():
    malformed_list = attraction("列表坐标", location="120,30")
    malformed_list["location"] = [120, 30]
    malformed_dict = attraction("字典坐标", location="121,31")
    malformed_dict["location"] = {"lng": 121, "lat": 31}
    valid = attraction("有效坐标", location="122,32")
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={("风景名胜", "120,30", 50000): [malformed_list, malformed_dict, valid]},
    )

    result = await RouteAgent(amap).run(request(days=1), weather_result(1), ids())

    assert [item.poi.name for item in result.data.daily_itineraries[0].attractions] == ["有效坐标"]
    assert result.data.daily_itineraries[0].attractions[0].time_slot == "上午"


@pytest.mark.asyncio
async def test_route_agent_deduplicates_same_day_candidates_before_slot_assignment():
    duplicate = attraction("重复景区", location="120,30")
    unique = attraction("后续唯一景区", location="121,31")
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={("风景名胜", "120,30", 50000): [duplicate, duplicate.copy(), unique]},
    )

    result = await RouteAgent(amap).run(request(days=1), weather_result(1), ids())

    assert [item.poi.name for item in result.data.daily_itineraries[0].attractions] == ["重复景区", "后续唯一景区"]
    assert [item.time_slot for item in result.data.daily_itineraries[0].attractions] == ["上午", "下午"]


@pytest.mark.asyncio
async def test_route_agent_shortage_does_not_repeat_and_marks_partial():
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}, ("120,30", "121,31"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={("风景名胜", "120,30", 50000): [attraction("唯一景区")]},
    )
    result = await RouteAgent(amap).run(request(days=2), weather_result(2), ids())

    assert result.status is AgentStatus.partial
    assert [item.poi.name for itinerary in result.data.daily_itineraries for item in itinerary.attractions] == ["唯一景区"]
    assert "route_day_1_attraction_2" in result.missing_fields
    assert "route_day_2_attraction_1" in result.missing_fields


@pytest.mark.asyncio
async def test_route_agent_does_not_keep_untraceable_segment_travel_estimate():
    untraceable_segment = {"distance_meters": 99, "duration_minutes": 9}
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "119,29", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={
            ("119,29", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)},
            ("120,30", "119,29"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)},
            ("120,30", "121,31"): untraceable_segment,
        },
        nearby_results={("风景名胜", "120,30", 50000): [attraction("景区1", location="120,30"), attraction("景区2", location="121,31")]},
    )

    result = await RouteAgent(amap).run(request(days=1), weather_result(1), ids())

    itinerary = result.data.daily_itineraries[0]
    assert itinerary.attractions[0].travel_to_next is None
    assert "route_day_1_travel_1" in result.missing_fields


@pytest.mark.asyncio
async def test_route_agent_commute_failure_keeps_pois_without_fake_duration():
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "119,29", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("119,29", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}, ("120,30", "119,29"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={("风景名胜", "120,30", 50000): [attraction("景区1", location="120,30"), attraction("景区2", location="121,31")]},
    )
    result = await RouteAgent(amap).run(request(days=1), weather_result(1), ids())

    assert result.status is AgentStatus.partial
    assert result.data.daily_itineraries[0].attractions[0].travel_to_next is None
    assert "route_day_1_travel_1" in result.missing_fields


@pytest.mark.asyncio
async def test_route_agent_without_real_attractions_degrades_without_fabricated_poi():
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={("风景名胜", "120,30", 50000): [attraction("商场", "购物服务;商场")]},
    )
    result = await RouteAgent(amap).run(request(days=1), weather_result(1), ids())

    assert result.status is AgentStatus.degraded
    assert result.data.daily_itineraries[0].attractions == ()


@pytest.mark.asyncio
async def test_route_agent_keeps_attraction_without_location_and_marks_adjacent_travel_missing():
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={("风景名胜", "120,30", 50000): [attraction("无坐标景区", location=None), attraction("有坐标景区", location="120,30")]},
    )

    result = await RouteAgent(amap).run(request(days=1), weather_result(1), ids())

    attractions = result.data.daily_itineraries[0].attractions
    assert [item.poi.name for item in attractions] == ["无坐标景区", "有坐标景区"]
    assert attractions[0].poi.location is None
    assert attractions[0].travel_to_next is None
    assert "route_day_1_travel_1" in result.data.daily_itineraries[0].missing_fields
    assert "route_day_1_travel_1" in result.missing_fields
    assert "route_day_1_attraction_1" not in result.missing_fields


@pytest.mark.asyncio
async def test_route_agent_skips_non_dict_candidates_and_keeps_following_valid_poi():
    valid = attraction("有效景区", location="120,30")
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={("风景名胜", "120,30", 50000): [None, "错误候选", valid]},
    )

    result = await RouteAgent(amap).run(request(days=1), weather_result(1), ids())

    assert result.data.daily_itineraries[0].attractions[0].poi.name == "有效景区"


@pytest.mark.asyncio
async def test_route_agent_deduplicates_sources_by_stable_fields_and_keeps_first():
    first_time = datetime(2026, 8, 21, tzinfo=timezone.utc)
    second_time = datetime(2026, 8, 22, tzinfo=timezone.utc)
    map_first = source_metadata(SourceType.map_api, updated=None)
    map_first["retrieved_at"] = first_time
    map_second = source_metadata(SourceType.map_api, updated=None)
    map_second["retrieved_at"] = second_time
    poi_first = attraction("景区1", location="120,30")
    poi_first["retrieved_at"] = first_time
    poi_second = attraction("景区2", location="121,31")
    poi_second["retrieved_at"] = second_time
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **map_first}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **map_second}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **map_second}},
        nearby_results={("风景名胜", "120,30", 50000): [poi_first, poi_second]},
    )

    result = await RouteAgent(amap).run(request(days=1), weather_result(1), ids())

    assert len([source for source in result.sources if source.type is SourceType.map_api]) == 1
    assert len([source for source in result.sources if source.type is SourceType.poi_api]) == 1
    assert result.sources[0].retrieved_at == first_time


@pytest.mark.asyncio
async def test_route_agent_keeps_mixed_weather_candidates_on_their_own_days():
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={
            ("风景名胜", "120,30", 50000): [attraction("常规景区", "风景名胜", "120,30")],
            ("博物馆", "120,30", 50000): [attraction("室内博物馆", "科教文化服务;博物馆;博物馆", "121,31")],
            ("美术馆", "120,30", 50000): [],
            ("展馆", "120,30", 50000): [],
        },
    )

    result = await RouteAgent(amap).run(request(days=2), weather_result(2, ["晴", "高温"]), ids())

    assert [item.poi.name for item in result.data.daily_itineraries[0].attractions] == ["常规景区"]
    assert [item.poi.name for item in result.data.daily_itineraries[1].attractions] == ["室内博物馆"]
    assert amap.nearby_calls == [("风景名胜", "120,30", 50000), ("博物馆", "120,30", 50000), ("美术馆", "120,30", 50000), ("展馆", "120,30", 50000)]
    assert not any(call[0] == "search_poi" for call in amap.calls)


@pytest.mark.asyncio
async def test_route_agent_propagates_partial_weather_missing_fields():
    weather_ids = ids()
    partial_weather = AgentResult(
        agent="weather", status=AgentStatus.partial, summary="天气部分可用",
        data=WeatherPlanData(destination="杭州", daily=weather_result(1).data.daily),
        missing_fields=("daily_forecast_days_2_to_2",),
        request_id=weather_ids["request_id"], trace_id=weather_ids["trace_id"],
    )
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={("风景名胜", "120,30", 50000): [attraction("景区", location="120,30")]},
    )

    result = await RouteAgent(amap).run(request(days=2), partial_weather, ids())

    assert result.status is AgentStatus.partial
    assert "weather_daily_forecast_days_2_to_2" in result.missing_fields


@pytest.mark.asyncio
async def test_route_agent_partial_weather_stays_partial_with_complete_pois():
    weather_ids = ids()
    partial_weather = AgentResult(
        agent="weather", status=AgentStatus.partial, summary="天气部分可用",
        data=WeatherPlanData(destination="杭州", daily=weather_result(1).data.daily),
        missing_fields=("daily_forecast_days_2_to_2",),
        request_id=weather_ids["request_id"], trace_id=weather_ids["trace_id"],
    )
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={("风景名胜", "120,30", 50000): [attraction("景区0", location="120,30"), attraction("景区1", location="121,31"), attraction("景区2", location="122,32")]},
    )

    result = await RouteAgent(amap).run(request(days=1), partial_weather, ids())

    assert result.status is AgentStatus.partial
    assert "weather_daily_forecast_days_2_to_2" in result.missing_fields


@pytest.mark.asyncio
async def test_route_agent_handles_failed_weather_result_without_throwing():
    weather_ids = ids()
    failed_weather = AgentResult(
        agent="weather", status=AgentStatus.failed, summary="天气服务不可用", data=None,
        missing_fields=("daily_forecast",),
        error=ErrorDetail(code="WEATHER_UNAVAILABLE", message="天气服务暂不可用", retryable=True),
        request_id=weather_ids["request_id"], trace_id=weather_ids["trace_id"],
    )
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        routes={("121,31", "120,30"): {"distance_meters": 1, "duration_minutes": 1, **source_metadata(SourceType.map_api)}},
        nearby_results={("风景名胜", "120,30", 50000): []},
    )

    result = await RouteAgent(amap).run(request(days=1), failed_weather, ids())

    assert result.status is AgentStatus.degraded
    assert "weather_daily_forecast" in result.missing_fields
    assert "weather" not in result.missing_fields
    assert result.data.daily_itineraries[0].weather_reminder == "天气待核验，请出行前确认。"


def test_route_agent_consumes_weather_constraints_and_marks_adjusted():
    amap = FakeAmapClient(
        geocodes={
            "上海": {"name": "上海市", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)},
            "杭州": {"name": "杭州市", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)},
        },
        route={"distance_meters": 180000, "duration_minutes": 150, **source_metadata(SourceType.map_api)},
    )
    agent = RouteAgent(amap)
    weather_agent = WeatherAgent(
        weather_client=FakeWeatherClient(weather_payload(days=2, condition="暴雨")),
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
    )
    request_ids = ids()
    weather_result = __import__("asyncio").run(weather_agent.run(request(days=2), **request_ids))

    result = __import__("asyncio").run(
        agent.run(request(days=2), weather_result.constraints, request_ids)
    )

    assert result.status is AgentStatus.degraded
    assert result.request_id == request_ids["request_id"]
    assert result.trace_id == request_ids["trace_id"]
    assert result.data.weather_adjusted is True
    assert result.missing_fields == ("attractions",)
    assert result.constraints == weather_result.constraints
    assert result.data.round_trip.distance_meters == 180000
    assert amap.calls == [("geocode", "上海"), ("geocode", "杭州"), ("driving_route", "121,31", "120,30")]
    assert result.data.daily_areas == (DailyArea(day=1, area="杭州市"), DailyArea(day=2, area="杭州市"))
    assert len(result.data.daily_itineraries) == 2


def test_route_agent_fallback_has_no_estimate_and_keeps_daily_areas():
    amap = FakeAmapClient(error=ExternalServiceUnavailable("外部服务暂不可用"))
    agent = RouteAgent(amap)

    result = __import__("asyncio").run(agent.run(request(days=3), (), ids()))

    assert result.status is AgentStatus.degraded
    assert result.request_id == result.trace_id
    assert result.data.round_trip is None
    assert result.data.daily_areas == (
        DailyArea(day=1, area="杭州"),
        DailyArea(day=2, area="杭州"),
        DailyArea(day=3, area="杭州"),
    )
    assert result.missing_fields == ("route_estimate", "attractions")
    assert "distance_meters" not in repr(result.data)


def test_agent_results_do_not_expose_transactional_fields():
    assert not {"price", "inventory", "rating", "queue"} & set(WeatherPlanData.model_fields)
    assert not {"price", "inventory", "rating", "queue"} & set(RoutePlanData.model_fields)


def test_weather_constructor_does_not_swap_dual_capability_clients():
    first = DualCapabilityClient(
        weather_payload(days=1),
        {"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
    )
    second = DualCapabilityClient(
        weather_payload(days=1),
        {"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
    )

    agent = WeatherAgent(first, second)

    assert agent.weather_client is first
    assert agent.amap_client is second


@pytest.mark.parametrize("forecast", [None, []])
def test_weather_non_dict_forecast_is_controlled_degraded(forecast):
    agent = WeatherAgent(
        weather_client=FakeWeatherClient(forecast),
        amap_client=FakeAmapClient(
            geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}
        ),
    )

    result = __import__("asyncio").run(agent.run(request(), **ids()))

    assert result.status is AgentStatus.degraded
    assert result.data.daily == ()
    assert result.missing_fields == ("daily_forecast",)


def test_weather_forecast_without_daily_is_controlled_degraded():
    agent = WeatherAgent(
        weather_client=FakeWeatherClient(source_metadata(SourceType.weather_api)),
        amap_client=FakeAmapClient(
            geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}
        ),
    )

    result = __import__("asyncio").run(agent.run(request(), **ids()))

    assert result.status is AgentStatus.degraded
    assert result.data.daily == ()
    assert result.missing_fields == ("daily_forecast",)


def test_agents_accept_named_client_constructor_arguments():
    weather = WeatherAgent(
        weather_client=FakeWeatherClient(weather_payload(days=1)),
        amap_client=FakeAmapClient(
            geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}
        ),
    )
    route = RouteAgent(amap_client=FakeAmapClient(error=ExternalServiceUnavailable("不可用")))

    assert weather.weather_client is not None
    assert route.amap_client is not None


def test_route_run_accepts_legacy_request_and_trace_keywords():
    agent = RouteAgent(amap_client=FakeAmapClient(error=ExternalServiceUnavailable("不可用")))
    request_ids = ids()

    result = __import__("asyncio").run(
        agent.run(
            request(),
            (),
            request_id=request_ids["request_id"],
            trace_id=request_ids["trace_id"],
        )
    )

    assert result.status is AgentStatus.degraded


def test_weather_keeps_amap_geocode_and_weather_sources():
    agent = WeatherAgent(
        weather_client=FakeWeatherClient(weather_payload(days=1)),
        amap_client=FakeAmapClient(
            geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}
        ),
    )

    request_ids = ids()
    result = __import__("asyncio").run(agent.run(request(days=1), **request_ids))

    assert result.status is AgentStatus.success
    assert result.request_id == request_ids["request_id"]
    assert result.trace_id == request_ids["trace_id"]
    assert {source.type for source in result.sources} == {SourceType.map_api, SourceType.weather_api}


def test_weather_marks_actual_missing_days_as_partial():
    agent = WeatherAgent(
        weather_client=FakeWeatherClient(weather_payload(days=2)),
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
    )

    result = __import__("asyncio").run(agent.run(request(days=3), **ids()))

    assert result.status is AgentStatus.partial
    assert result.missing_fields == ("daily_forecast_days_3_to_3",)


def test_route_degrades_when_downstream_payload_is_malformed():
    amap = FakeAmapClient(
        geocodes={
            "上海": {"name": "上海市", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)},
            "杭州": {"name": "杭州市", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)},
        },
        route={"distance_meters": "not-a-number", "duration_minutes": 10, **source_metadata(SourceType.map_api)},
    )

    result = __import__("asyncio").run(RouteAgent(amap_client=amap).run(request(), (), ids()))

    assert result.status is AgentStatus.degraded
    assert result.data.round_trip is None
    assert result.missing_fields == ("route_estimate", "attractions")


def test_route_degrades_when_source_metadata_is_invalid_instead_of_returning_success():
    amap = FakeAmapClient(
        geocodes={
            "上海": {"name": "上海市", "location": "121,31", "adcode": "310000"},
            "杭州": {"name": "杭州市", "location": "120,30", "adcode": "330100"},
        },
        route={"distance_meters": 100, "duration_minutes": 10},
    )

    result = __import__("asyncio").run(RouteAgent(amap_client=amap).run(request(), (), ids()))

    assert result.status is AgentStatus.degraded
    assert result.data.round_trip is None


def test_weather_rejects_invalid_tracking_ids_at_input_boundary():
    agent = WeatherAgent(
        weather_client=FakeWeatherClient(weather_payload(days=1)),
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
    )

    with pytest.raises(ValueError, match="请求追踪标识无效"):
        __import__("asyncio").run(agent.run(request(), "not-a-uuid", "not-a-uuid"))


def test_route_rejects_missing_or_mismatched_tracking_ids_at_input_boundary():
    agent = RouteAgent(amap_client=FakeAmapClient(error=ExternalServiceUnavailable("不可用")))
    valid = str(uuid4())

    with pytest.raises(ValueError, match="请求追踪标识无效"):
        __import__("asyncio").run(agent.run(request(), (), {}))
    with pytest.raises(ValueError, match="请求追踪标识无效"):
        __import__("asyncio").run(agent.run(request(), (), {"request_id": valid, "trace_id": str(uuid4())}))
