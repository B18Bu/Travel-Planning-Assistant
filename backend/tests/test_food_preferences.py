from app.agents.food import FoodAgent
from app.models.travel import AgentGuidance, FoodCandidate, PreferenceItem, PoiCandidate, TravelPreferenceProfile


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
