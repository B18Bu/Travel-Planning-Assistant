from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.travel import (
    DailyArea,
    DailyWeather,
    DataStatus,
    NormalizedLocation,
    PoiCandidate,
    RouteEstimate,
    Source,
    SourceType,
    TravelPlanRequest,
    WeatherRiskLevel,
)


def test_travel_plan_request_applies_defaults_and_derives_nights():
    request = TravelPlanRequest(
        origin=" 上海 ", destination=" 杭州 ", departure_date=date.today(), travelers=2
    )
    assert request.origin == "上海"
    assert request.destination == "杭州"
    assert request.days == 3
    assert request.nights == 2
    assert request.preferences == []


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"origin": " ", "destination": "杭州"}, "origin"),
        ({"origin": "上海", "destination": " "}, "destination"),
        ({"origin": "上海", "destination": "杭州", "travelers": 0}, "travelers"),
        ({"origin": "上海", "destination": "杭州", "days": 15}, "days"),
        (
            {
                "origin": "上海",
                "destination": "杭州",
                "departure_date": date.today() - timedelta(days=1),
            },
            "departure_date",
        ),
        ({"origin": "上海", "destination": "杭州", "preferences": [" "]}, "preferences"),
        ({"origin": "上海", "destination": "杭州", "unexpected": "value"}, "unexpected"),
    ],
)
def test_travel_plan_request_rejects_invalid_or_unknown_input(payload, field):
    payload.setdefault("departure_date", date.today())
    payload.setdefault("travelers", 2)
    with pytest.raises(ValidationError) as exc_info:
        TravelPlanRequest(**payload)
    assert field in str(exc_info.value)


@pytest.mark.parametrize("field", ["origin", "destination"])
def test_travel_plan_request_accepts_text_at_maximum_length(field):
    payload = {
        "origin": "上海",
        "destination": "杭州",
        "departure_date": date.today(),
        "travelers": 2,
    }
    payload[field] = "a" * 100

    request = TravelPlanRequest(**payload)

    assert getattr(request, field) == "a" * 100


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"origin": "a" * 101, "destination": "杭州"}, "origin"),
        ({"origin": "上海", "destination": "a" * 101}, "destination"),
        ({"origin": "上海", "destination": "杭州", "preferences": ["a" * 101]}, "preferences"),
    ],
)
def test_travel_plan_request_rejects_text_exceeding_maximum_length(payload, field):
    payload.setdefault("departure_date", date.today())
    payload.setdefault("travelers", 2)

    with pytest.raises(ValidationError) as exc_info:
        TravelPlanRequest(**payload)

    assert field in str(exc_info.value)


def test_travel_plan_request_accepts_preference_at_maximum_length():
    request = TravelPlanRequest(
        origin="上海",
        destination="杭州",
        departure_date=date.today(),
        travelers=2,
        preferences=["a" * 100],
    )

    assert request.preferences == ["a" * 100]


@pytest.mark.parametrize("travelers", [1, 20])
def test_travel_plan_request_accepts_traveler_boundaries(travelers):
    request = TravelPlanRequest(
        origin="上海", destination="杭州", departure_date=date.today(), travelers=travelers
    )

    assert request.travelers == travelers


def test_travel_plan_request_rejects_travelers_above_maximum():
    with pytest.raises(ValidationError) as exc_info:
        TravelPlanRequest(
            origin="上海", destination="杭州", departure_date=date.today(), travelers=21
        )

    assert "travelers" in str(exc_info.value)


@pytest.mark.parametrize("days", [1, 14])
def test_travel_plan_request_accepts_day_boundaries(days):
    request = TravelPlanRequest(
        origin="上海", destination="杭州", departure_date=date.today(), travelers=2, days=days
    )

    assert request.days == days


@pytest.mark.parametrize("days", [0, 15])
def test_travel_plan_request_rejects_days_outside_allowed_range(days):
    with pytest.raises(ValidationError) as exc_info:
        TravelPlanRequest(
            origin="上海", destination="杭州", departure_date=date.today(), travelers=2, days=days
        )

    assert "days" in str(exc_info.value)


@pytest.mark.parametrize("budget", [None, 0, 200000])
def test_travel_plan_request_accepts_budget_boundaries(budget):
    request = TravelPlanRequest(
        origin="上海", destination="杭州", departure_date=date.today(), travelers=2, budget=budget
    )

    assert request.budget == budget


@pytest.mark.parametrize("budget", [-1, 200001])
def test_travel_plan_request_rejects_budget_outside_allowed_range(budget):
    with pytest.raises(ValidationError) as exc_info:
        TravelPlanRequest(
            origin="上海", destination="杭州", departure_date=date.today(), travelers=2, budget=budget
        )

    assert "budget" in str(exc_info.value)


def test_travel_plan_request_accepts_twelve_preferences():
    preferences = [f"偏好{i}" for i in range(12)]

    request = TravelPlanRequest(
        origin="上海",
        destination="杭州",
        departure_date=date.today(),
        travelers=2,
        preferences=preferences,
    )

    assert request.preferences == preferences


def test_travel_plan_request_rejects_more_than_twelve_preferences():
    with pytest.raises(ValidationError) as exc_info:
        TravelPlanRequest(
            origin="上海",
            destination="杭州",
            departure_date=date.today(),
            travelers=2,
            preferences=[f"偏好{i}" for i in range(13)],
        )

    assert "preferences" in str(exc_info.value)


@pytest.mark.parametrize("preferences", [None, "亲子", ("亲子",), {"亲子"}])
def test_travel_plan_request_rejects_non_list_preferences_with_validation_error(preferences):
    with pytest.raises(ValidationError) as exc_info:
        TravelPlanRequest(
            origin="上海",
            destination="杭州",
            departure_date=date.today(),
            travelers=2,
            preferences=preferences,
        )

    assert "preferences" in str(exc_info.value)


@pytest.mark.parametrize(("days", "nights"), [(1, 0), (14, 13)])
def test_travel_plan_request_derives_nights_from_days(days, nights):
    request = TravelPlanRequest(
        origin="上海", destination="杭州", departure_date=date.today(), travelers=2, days=days
    )

    assert request.nights == nights


def test_travel_plan_request_nights_is_read_only():
    request = TravelPlanRequest(
        origin="上海", destination="杭州", departure_date=date.today(), travelers=2
    )

    with pytest.raises(AttributeError):
        request.nights = 3


def test_source_accepts_realtime_with_ordered_timestamps():
    source = Source(
        name="天气服务",
        type=SourceType.weather_api,
        data_status=DataStatus.realtime,
        source_updated_at=datetime(2026, 8, 19, 10),
        retrieved_at=datetime(2026, 8, 19, 10, 1),
        url="https://weather.example.com",
    )

    assert source.model_dump()["data_status"] == DataStatus.realtime


@pytest.mark.parametrize("data_status", [DataStatus.realtime, DataStatus.cached])
def test_source_requires_upstream_time_for_realtime_or_cached(data_status):
    with pytest.raises(ValidationError):
        Source(
            name="天气服务",
            type=SourceType.weather_api,
            data_status=data_status,
            retrieved_at=datetime(2026, 8, 19, 10),
        )


def test_source_requires_knowledge_version_for_knowledge_base():
    with pytest.raises(ValidationError):
        Source(
            name="知识库",
            type=SourceType.knowledge_base,
            data_status=DataStatus.knowledge_base,
            retrieved_at=datetime(2026, 8, 19, 10),
        )


def test_source_requires_knowledge_base_status_for_knowledge_source():
    with pytest.raises(ValidationError):
        Source(
            name="知识库",
            type=SourceType.knowledge_base,
            data_status=DataStatus.cached,
            knowledge_version="v1",
            retrieved_at=datetime(2026, 8, 19, 10),
        )


def test_source_rejects_version_on_non_knowledge_source():
    with pytest.raises(ValidationError):
        Source(
            name="地图服务",
            type=SourceType.map_api,
            data_status=DataStatus.realtime,
            source_updated_at=datetime(2026, 8, 19, 10),
            retrieved_at=datetime(2026, 8, 19, 10, 1),
            knowledge_version="v1",
        )


def test_source_rejects_non_https_url():
    with pytest.raises(ValidationError):
        Source(
            name="地图服务",
            type=SourceType.map_api,
            data_status=DataStatus.realtime,
            source_updated_at=datetime(2026, 8, 19, 10),
            retrieved_at=datetime(2026, 8, 19, 10, 1),
            url="http://map.example.com",
        )


def test_domain_fact_models_serialize_successfully():
    location = NormalizedLocation(name="西湖", location="30,120", adcode="330106")
    poi = PoiCandidate(
        name="断桥",
        address="西湖边",
        category="景点",
        tags=["湖景"],
        source_ids=["source-1"],
    )
    weather = DailyWeather(
        date=date(2026, 8, 20),
        condition="晴",
        temp_min=24,
        temp_max=32,
        risk_level=WeatherRiskLevel.low,
        equipment_suggestions=["遮阳伞"],
    )
    route = RouteEstimate(distance_meters=1200, duration_minutes=20)
    area = DailyArea(day=1, area="西湖景区", activity_window="上午")

    assert location.model_dump()["name"] == "西湖"
    assert poi.model_dump()["source_ids"] == ["source-1"]
    assert weather.model_dump()["risk_level"] == WeatherRiskLevel.low
    assert route.model_dump()["is_estimate"] is True
    assert area.model_dump()["day"] == 1


def test_poi_rejects_empty_source_ids():
    with pytest.raises(ValidationError):
        PoiCandidate(name="断桥", category="景点", source_ids=[])


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (RouteEstimate, {"distance_meters": -1, "duration_minutes": 1}),
        (DailyArea, {"day": 0, "area": "西湖景区"}),
    ],
)
def test_domain_fact_models_reject_invalid_bounds(model, payload):
    with pytest.raises(ValidationError):
        model(**payload)


@pytest.mark.parametrize("model", [NormalizedLocation, PoiCandidate, DailyWeather, RouteEstimate, DailyArea])
def test_domain_fact_models_reject_commercial_fields(model):
    payloads = {
        NormalizedLocation: {"name": "西湖"},
        PoiCandidate: {"name": "断桥", "category": "景点", "source_ids": ["source-1"]},
        DailyWeather: {"date": date(2026, 8, 20), "condition": "晴", "risk_level": WeatherRiskLevel.low},
        RouteEstimate: {"distance_meters": 1, "duration_minutes": 1},
        DailyArea: {"day": 1, "area": "西湖景区"},
    }
    with pytest.raises(ValidationError):
        model(**payloads[model], rating=5, price=100)
