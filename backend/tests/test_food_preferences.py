from datetime import date
from uuid import uuid4

import pytest

from app.agents.food import FoodAgent
from app.models.travel import (
    AgentGuidance,
    DailyItinerary,
    DailyFoodPlan,
    FoodCandidate,
    FoodGuidance,
    PoiCandidate,
    PreferenceItem,
    TimedAttraction,
    TravelPlanRequest,
    TravelPreferenceProfile,
)


def test_food_candidate_is_removed_when_model_exclusion_term_matches_any_candidate_text():
    candidate = FoodCandidate(
        poi=PoiCandidate(name="特色餐厅", category="餐饮服务", tags=("本地菜",), source_ids=("test",)),
        specialties=("麻辣牛肉",),
    )
    profile = TravelPreferenceProfile(
        preferences=(
            PreferenceItem(
                category="diet",
                priority="must",
                instruction="不吃辣",
                exclude_terms=("麻辣",),
            ),
        ),
        agent_guidance=AgentGuidance(),
    )

    assert FoodAgent._is_allowed_by_profile(candidate, profile) is False


def test_food_candidate_with_spicy_cuisine_label_is_removed_when_profile_excludes_spice():
    candidate = FoodCandidate(
        poi=PoiCandidate(name="川味馆", category="餐饮服务", source_ids=("test",)),
        specialties=("四川菜(川菜)",),
    )
    profile = TravelPreferenceProfile(
        preferences=(
            PreferenceItem(
                category="diet",
                priority="must",
                instruction="不吃辣",
                exclude_terms=("辣",),
            ),
        ),
        agent_guidance=AgentGuidance(),
    )

    assert FoodAgent._is_allowed_by_profile(candidate, profile) is False


def test_food_candidate_is_removed_when_avoid_preference_has_exclusion_term():
    candidate = FoodCandidate(
        poi=PoiCandidate(name="麻辣小馆", category="餐饮服务", source_ids=("test",)),
    )
    profile = TravelPreferenceProfile(
        preferences=(
            PreferenceItem(
                category="diet",
                priority="avoid",
                instruction="不吃辣",
                exclude_terms=("麻辣",),
            ),
        ),
        agent_guidance=AgentGuidance(),
    )

    assert FoodAgent._is_allowed_by_profile(candidate, profile) is False


def test_daily_food_plan_keeps_flyai_reference_separate_from_poi_candidates():
    plan = DailyFoodPlan(
        day=1,
        area="成都",
        meal_period="午餐",
        reference_notes=("飞猪 AI 餐饮参考：请向商家确认口味与营业时间。",),
    )

    assert plan.candidates == ()
    assert plan.reference_notes == ("飞猪 AI 餐饮参考：请向商家确认口味与营业时间。",)


@pytest.mark.asyncio
async def test_food_uses_flyai_reference_when_amap_has_no_candidates():
    class EmptyAmap:
        async def search_nearby_poi(self, keywords, location, radius):
            return []

    class FakeFlyAI:
        def __init__(self):
            self.calls = []

        async def search_food(self, city_name, nearby_attraction, preferences):
            self.calls.append((city_name, nearby_attraction, preferences))
            return "可优先询问清淡川菜、蒸菜与儿童餐。"

    profile = TravelPreferenceProfile(
        preferences=(
            PreferenceItem(
                category="diet",
                priority="must",
                instruction="不吃辣",
                exclude_terms=("麻辣",),
            ),
        ),
        agent_guidance=AgentGuidance(
            food=FoodGuidance(instructions=("优先清淡、儿童友好餐饮",)),
        ),
    )
    request = TravelPlanRequest(
        origin="北京",
        destination="成都",
        departure_date=date(2026, 9, 10),
        travelers=3,
        days=1,
        profile=profile,
    )
    attraction = TimedAttraction(
        time_slot="上午",
        poi=PoiCandidate(
            name="宽窄巷子",
            address="成都市青羊区",
            location="104.05,30.67",
            category="旅游景点",
            source_ids=("route",),
        ),
        suggested_duration_minutes=60,
    )
    flyai = FakeFlyAI()
    request_id = str(uuid4())

    result = await FoodAgent(EmptyAmap(), flyai_client=flyai).run(
        request,
        (DailyItinerary(day=1, weather_reminder="注意天气", attractions=(attraction,)),),
        request_id,
        request_id,
    )

    lunch = result.data.daily_food[0]
    assert lunch.candidates == ()
    assert lunch.reference_notes == (
        "飞猪 AI 餐饮参考：可优先询问清淡川菜、蒸菜与儿童餐。请向商家确认口味、食材、营业时间等信息。",
    )
    assert flyai.calls == [("成都", "宽窄巷子", ("不吃辣", "优先清淡、儿童友好餐饮"))]
