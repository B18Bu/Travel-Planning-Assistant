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
        self.calls = []

    async def daily_forecast(self, location_id, start, days):
        self.calls.append((location_id, start, days))
        return self.result


class FakeAmapClient:
    def __init__(self, geocodes=None, route=None, error=None):
        self.geocodes = geocodes or {}
        self.route = route
        self.error = error
        self.calls = []

    async def geocode(self, address):
        self.calls.append(("geocode", address))
        if self.error:
            raise self.error
        return self.geocodes[address]

    async def driving_route(self, origin, destination):
        self.calls.append(("driving_route", origin, destination))
        if self.error:
            raise self.error
        return self.route


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


@pytest.mark.parametrize("risk_word", ["暴雨", "台风", "强对流", "高温"])
def test_weather_agent_marks_each_required_risk_word_high(risk_word):
    agent = WeatherAgent(
        weather_client=FakeWeatherClient(weather_payload(days=1, condition=risk_word)),
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
    )

    result = __import__("asyncio").run(agent.run(request(days=1), **ids()))

    assert result.status is AgentStatus.success
    assert result.data.daily[0].risk_level is WeatherRiskLevel.high
    assert result.constraints == ("第 1 天避免长时间户外活动或高温时段优先室内。",)


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
    assert result.constraints == ("第 1 天避免长时间户外活动或高温时段优先室内。",)
    assert agent.amap_client.calls == [("geocode", "杭州")]
    assert agent.weather_client.calls == [("330100", request(days=1).departure_date, request(days=1).days)]


def test_weather_agent_rejects_empty_daily_as_degraded_without_fabricated_weather():
    agent = WeatherAgent(
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
        weather_client=FakeWeatherClient({**source_metadata(SourceType.weather_api), "daily": ()}),
    )

    result = __import__("asyncio").run(agent.run(request(), **ids()))

    assert result.status is AgentStatus.degraded
    assert result.data.daily == ()
    assert result.missing_fields == ("daily_forecast",)


def test_weather_agent_limits_over_three_days_to_partial_with_exact_missing_field():
    agent = WeatherAgent(
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
        weather_client=FakeWeatherClient(weather_payload(days=3)),
    )

    result = __import__("asyncio").run(agent.run(request(days=5), **ids()))

    assert result.status is AgentStatus.partial
    assert result.request_id == result.trace_id
    assert len(result.data.daily) == 3
    assert result.missing_fields == ("daily_forecast_days_4_to_N",)
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

    assert result.status is AgentStatus.success
    assert result.request_id == request_ids["request_id"]
    assert result.trace_id == request_ids["trace_id"]
    assert result.data.weather_adjusted is True
    assert result.constraints == weather_result.constraints
    assert result.data.round_trip.distance_meters == 180000
    assert amap.calls == [("geocode", "上海"), ("geocode", "杭州"), ("driving_route", "121,31", "120,30")]
    assert result.data.daily_areas == (DailyArea(day=1, area="杭州市"), DailyArea(day=2, area="杭州市"))


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
    assert result.missing_fields == ("route_estimate",)
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
    assert result.missing_fields == ("route_estimate",)


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
