from datetime import date

from app.agents.route import RouteAgent
from app.agents.summary import SummaryAgent
from app.models.travel import AgentGuidance, PreferenceItem, RouteGuidance, TravelPlanRequest, TravelPreferenceProfile


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


def test_summary_renders_model_preference_response_and_verification_notes():
    profile = TravelPreferenceProfile(
        summary="亲子摄影友好行程",
        preferences=(
            PreferenceItem(
                category="experience",
                priority="prefer",
                instruction="优先亲子互动体验",
                verification_required=True,
            ),
        ),
        agent_guidance=AgentGuidance(),
        verification_notes=("向商家确认活动年龄限制。",),
    )

    lines = SummaryAgent._profile_section(profile)

    assert "## 用户偏好响应" in lines
    assert "优先亲子互动体验" in "\n".join(lines)
    assert "向商家确认活动年龄限制。" in "\n".join(lines)
