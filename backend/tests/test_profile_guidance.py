from datetime import date

from app.agents.route import RouteAgent
from app.agents.summary import SummaryAgent
from app.agents.lodging import LodgingAgent
from app.agents.weather import WeatherAgent
from app.models.travel import AgentGuidance, DailyWeather, PreferenceItem, RouteGuidance, TravelPlanRequest, TravelPreferenceProfile, WeatherRiskLevel


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


def test_weather_adds_model_guidance_to_weather_constraints():
    profile = TravelPreferenceProfile(agent_guidance=AgentGuidance(weather=("减少长时间步行",)))
    daily = DailyWeather(
        date=date(2026, 9, 10), condition="晴", risk_level=WeatherRiskLevel.low,
        travel_reminder="天气适宜出行", indoor_preferred=False,
    )

    assert WeatherAgent._constraints((daily,), profile) == ("用户偏好：减少长时间步行",)


def test_lodging_adds_model_guidance_to_filter_suggestions():
    profile = TravelPreferenceProfile(agent_guidance=AgentGuidance(lodging=("优先靠近地铁站",)))

    assert LodgingAgent._filter_suggestions(profile) == (
        "请按活动区域、交通便利性和入住日期筛选。",
        "用户偏好：优先靠近地铁站",
    )
