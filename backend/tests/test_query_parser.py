from datetime import date

import pytest

from app.services.query_parser import TravelQueryParser


class StaticClient:
    async def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        return '{"preferences": []}'


class FailingClient:
    async def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        raise RuntimeError("模型不可用")


class ProfileClient:
    async def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        return '''{
          "preferences": [],
          "preference_profile": {
            "summary": "适合亲子摄影的舒缓行程",
            "companions": [{"type": "child", "count": 1}],
            "preferences": [
              {"category": "experience", "priority": "prefer", "instruction": "优先亲子互动体验", "exclude_terms": [], "verification_required": false},
              {"category": "experience", "priority": "prefer", "instruction": "摄影友好", "exclude_terms": [], "verification_required": false}
            ],
            "agent_guidance": {"route": {"instructions": ["每日安排两个主要时段"], "daily_primary_limit": 2, "priority_terms": ["亲子", "摄影"]}, "food": {"instructions": [], "exclude_terms": [], "verification_notes": []}, "lodging": [], "summary": ["说明摄影偏好如何被响应"]},
            "verification_notes": []
          }
        }'''


class ProfileWithInvalidBaseFieldClient:
    async def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        return '''{
          "travelers": "2位成人加1个孩子",
          "preferences": ["不吃辣"],
          "verification_notes": ["不应放在顶层"],
          "preference_profile": {
            "summary": "适合亲子的轻松行程",
            "companions": [{"type": "child", "count": 1}],
            "preferences": [
              {"category": "diet", "priority": "must", "instruction": "不吃辣", "exclude_terms": ["麻辣"], "verification_required": true}
            ],
            "agent_guidance": {"route": {"instructions": ["每日安排两个主要时段"], "daily_primary_limit": 2, "priority_terms": ["亲子"]}, "food": {"instructions": ["优先清淡、儿童友好餐饮"], "exclude_terms": ["麻辣"], "verification_notes": ["确认口味"]}, "lodging": [], "weather": [], "summary": []},
            "verification_notes": ["确认餐厅口味与儿童餐"]
          }
        }'''


class PromptRecordingClient:
    def __init__(self):
        self.system_prompt = ""

    async def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        return '{"preferences": []}'


class CompleteFieldsClient:
    async def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        return '{"origin":"北京","destination":"成都","departure_date":"2026-09-10","travelers":3,"days":3,"preferences":[]}'


class NonTemplateLocationClient:
    async def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        return '{"origin":"北京","destination":"三亚","departure_date":"2026-09-10","travelers":3,"days":3,"preferences":[]}'


class ModelAuthoritativeClient:
    async def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        return '{"origin":"广州","destination":"三亚","departure_date":"2026-09-10","travelers":3,"days":3,"preferences":[]}'


class MissingOriginClient:
    async def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        return '{"destination":"成都","departure_date":"2026-09-10","travelers":3,"days":3,"preferences":[]}'


@pytest.mark.asyncio
async def test_parse_extracts_complete_travel_fields_without_year():
    parser = TravelQueryParser(CompleteFieldsClient(), today=date(2026, 9, 2))

    result = await parser.parse(
        "2位成人带1个孩子，9月10日从北京到成都玩3天,不吃辣，行程节奏不要太赶。"
    )

    assert result.origin == "北京"
    assert result.destination == "成都"
    assert result.departure_date == date(2026, 9, 10)
    assert result.travelers == 3
    assert result.days == 3
    assert result.preferences == ()
    assert result.profile.verification_notes == ("偏好理解暂不可用，请在生成方案前核验偏好要求。",)
    assert result.missing_fields == ()


@pytest.mark.asyncio
async def test_parse_uses_model_for_non_template_location_phrase():
    parser = TravelQueryParser(NonTemplateLocationClient(), today=date(2026, 9, 2))

    result = await parser.parse("两个成人带一个孩子，9月10日从北京去往三亚游玩3天")

    assert result.origin == "北京"
    assert result.destination == "三亚"
    assert result.missing_fields == ()


@pytest.mark.asyncio
async def test_parse_treats_model_fields_as_authoritative():
    parser = TravelQueryParser(ModelAuthoritativeClient(), today=date(2026, 9, 2))

    result = await parser.parse("两个成人带一个孩子，9月10日从北京到三亚玩3天")

    assert result.origin == "广州"


@pytest.mark.asyncio
async def test_parse_fills_missing_model_origin_from_explicit_route_phrase():
    parser = TravelQueryParser(MissingOriginClient(), today=date(2026, 9, 2))

    result = await parser.parse("2位成人带1个孩子，9月10日从天津到成都玩3天，不吃辣，多安排亲子项目环节")

    assert result.origin == "天津"
    assert result.destination == "成都"
    assert result.missing_fields == ()


@pytest.mark.asyncio
async def test_parse_does_not_guess_locations_when_model_is_unavailable():
    parser = TravelQueryParser(FailingClient(), today=date(2026, 9, 2))

    result = await parser.parse("9月10日从北京去往三亚游玩3天")

    assert result.origin is None
    assert result.destination is None
    assert result.missing_fields == ("origin", "destination", "departure_date", "travelers", "days")


@pytest.mark.asyncio
async def test_parse_preserves_model_extracted_unlisted_preferences_in_profile():
    parser = TravelQueryParser(ProfileClient(), today=date(2026, 9, 2))

    result = await parser.parse(
        "两位成人带一个孩子，9月10日从北京到成都玩3天，想拍照也希望孩子玩得开心。"
    )

    assert result.profile.summary == "适合亲子摄影的舒缓行程"
    assert tuple(item.instruction for item in result.profile.preferences) == (
        "优先亲子互动体验",
        "摄影友好",
    )
    assert result.profile.agent_guidance.route.daily_primary_limit == 2
    assert result.profile.agent_guidance.route.priority_terms == ("亲子", "摄影")


@pytest.mark.asyncio
async def test_parse_returns_all_required_fields_missing_when_model_fails():
    parser = TravelQueryParser(FailingClient(), today=date(2026, 9, 2))

    result = await parser.parse("9月10日从北京到成都玩3天")

    assert result.origin is None
    assert result.destination is None
    assert result.departure_date is None
    assert result.days is None
    assert result.travelers is None
    assert result.missing_fields == ("origin", "destination", "departure_date", "travelers", "days")


@pytest.mark.asyncio
async def test_parse_preserves_profile_when_model_base_field_is_invalid():
    parser = TravelQueryParser(ProfileWithInvalidBaseFieldClient(), today=date(2026, 9, 2))

    result = await parser.parse(
        "2位成人带1个孩子，9月10日从北京到成都玩3天，不吃辣，行程节奏不要太赶。"
    )

    assert result.travelers is None
    assert result.preferences == ("不吃辣",)
    assert result.profile.summary == "适合亲子的轻松行程"
    assert result.profile.preferences[0].instruction == "不吃辣"
    assert result.profile.verification_notes == ("确认餐厅口味与儿童餐",)


@pytest.mark.asyncio
async def test_parse_prompt_requires_poi_exclusion_terms_for_no_spice_preference():
    client = PromptRecordingClient()

    await TravelQueryParser(client, today=date(2026, 9, 2)).parse("9月10日从北京到成都玩3天，不吃辣")

    assert "川菜" in client.system_prompt
    assert "POI" in client.system_prompt
    assert "priority 必须为 must" in client.system_prompt
