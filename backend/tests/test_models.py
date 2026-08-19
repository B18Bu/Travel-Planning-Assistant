from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.models.travel import TravelPlanRequest


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
