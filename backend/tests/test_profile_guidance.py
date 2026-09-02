from datetime import date

from app.agents.route import RouteAgent
from app.models.travel import AgentGuidance, RouteGuidance, TravelPlanRequest, TravelPreferenceProfile


def test_route_uses_model_daily_primary_limit_without_fixed_persona_rules():
    request = TravelPlanRequest(
        origin="北京",
        destination="成都",
        departure_date=date(2026, 9, 10),
        travelers=3,
        profile=TravelPreferenceProfile(
            agent_guidance=AgentGuidance(
                route=RouteGuidance(daily_primary_limit=2)
            )
        ),
    )

    assert RouteAgent._slots(request) == ("上午", "下午")
