from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.models.travel import (
    AgentStatus,
    DataStatus,
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

    async def daily_forecast(self, location_id, start, days):
        return self.result


class FakeAmapClient:
    def __init__(self, geocodes=None, route=None, error=None):
        self.geocodes = geocodes or {}
        self.route = route
        self.error = error

    async def geocode(self, address):
        if self.error:
            raise self.error
        return self.geocodes[address]

    async def driving_route(self, origin, destination):
        if self.error:
            raise self.error
        return self.route


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


def test_weather_agent_marks_heavy_rain_high_and_adds_deterministic_constraint():
    agent = WeatherAgent(
        FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100"}}),
        FakeWeatherClient(weather_payload(days=1, condition="暴雨")),
    )

    result = __import__("asyncio").run(agent.run(request(), **ids()))

    assert result.status is AgentStatus.success
    assert result.data.daily[0].risk_level is WeatherRiskLevel.high
    assert result.constraints == ("第 1 天避免长时间户外活动或高温时段优先室内。",)


def test_weather_agent_rejects_empty_daily_as_degraded_without_fabricated_weather():
    agent = WeatherAgent(
        FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100"}}),
        FakeWeatherClient({**source_metadata(SourceType.weather_api), "daily": ()}),
    )

    result = __import__("asyncio").run(agent.run(request(), **ids()))

    assert result.status is AgentStatus.degraded
    assert result.data.daily == ()
    assert result.missing_fields == ("daily_forecast",)


def test_weather_agent_limits_over_three_days_to_partial_with_exact_missing_field():
    agent = WeatherAgent(
        FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100"}}),
        FakeWeatherClient(weather_payload(days=3)),
    )

    result = __import__("asyncio").run(agent.run(request(days=5), **ids()))

    assert result.status is AgentStatus.partial
    assert len(result.data.daily) == 3
    assert result.missing_fields == ("daily_forecast_days_4_to_N",)


def test_weather_agent_preserves_real_weather_source_metadata():
    updated = datetime(2026, 8, 20, tzinfo=timezone.utc)
    agent = WeatherAgent(
        FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100"}}),
        FakeWeatherClient(weather_payload(status="cached", updated=updated)),
    )

    result = __import__("asyncio").run(agent.run(request(), **ids()))

    source = result.sources[0]
    assert source.type is SourceType.weather_api
    assert source.data_status is DataStatus.cached
    assert source.source_updated_at == updated
    assert source.retrieved_at == datetime(2026, 8, 21, tzinfo=timezone.utc)


def test_route_agent_consumes_weather_constraints_and_marks_adjusted():
    amap = FakeAmapClient(
        geocodes={
            "上海": {"name": "上海市", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)},
            "杭州": {"name": "杭州市", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)},
        },
        route={"distance_meters": 180000, "duration_minutes": 150, **source_metadata(SourceType.map_api)},
    )
    agent = RouteAgent(amap)

    result = __import__("asyncio").run(
        agent.run(request(days=2), ("第 1 天避免长时间户外活动或高温时段优先室内。",), ids())
    )

    assert result.status is AgentStatus.success
    assert result.data.weather_adjusted is True
    assert result.data.round_trip.distance_meters == 180000
    assert result.data.daily_areas == (DailyArea(day=1, area="杭州市"), DailyArea(day=2, area="杭州市"))


def test_route_agent_fallback_has_no_estimate_and_keeps_daily_areas():
    amap = FakeAmapClient(error=ExternalServiceUnavailable("外部服务暂不可用"))
    agent = RouteAgent(amap)

    result = __import__("asyncio").run(agent.run(request(days=3), (), ids()))

    assert result.status is AgentStatus.degraded
    assert result.data.round_trip is None
    assert result.data.daily_areas == (
        DailyArea(day=1, area="杭州"),
        DailyArea(day=2, area="杭州"),
        DailyArea(day=3, area="杭州"),
    )
    assert result.missing_fields == ("route_estimate",)
    assert "distance_meters" not in repr(result.data)


def test_agent_results_do_not_expose_transactional_fields():
    assert not {"price", "inventory", "rating", "queue"} & set(WeatherPlanData.model_fields)
    assert not {"price", "inventory", "rating", "queue"} & set(RoutePlanData.model_fields)
