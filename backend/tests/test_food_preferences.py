from app.agents.food import FoodAgent
from app.models.travel import AgentGuidance, DailyFoodPlan, FoodCandidate, PreferenceItem, PoiCandidate, TravelPreferenceProfile


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


def test_daily_food_plan_keeps_flyai_reference_separate_from_poi_candidates():
    plan = DailyFoodPlan(
        day=1,
        area="成都",
        meal_period="午餐",
        reference_notes=("飞猪 AI 餐饮参考：请向商家确认口味与营业时间。",),
    )

    assert plan.candidates == ()
    assert plan.reference_notes == ("飞猪 AI 餐饮参考：请向商家确认口味与营业时间。",)
