from datetime import date

import pytest

from app.services.query_parser import TravelQueryParser


class StaticClient:
    async def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        return '{"preferences": []}'


class FailingClient:
    async def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        raise RuntimeError("模型不可用")


@pytest.mark.asyncio
async def test_parse_extracts_complete_travel_fields_without_year():
    parser = TravelQueryParser(StaticClient(), today=date(2026, 9, 2))

    result = await parser.parse(
        "2位成人带1个孩子，9月10日从北京到成都玩3天,不吃辣，行程节奏不要太赶。"
    )

    assert result.origin == "北京"
    assert result.destination == "成都"
    assert result.departure_date == date(2026, 9, 10)
    assert result.travelers == 3
    assert result.days == 3
    assert result.preferences == ("不吃辣", "行程不要太赶")
    assert result.missing_fields == ()


@pytest.mark.asyncio
async def test_parse_preserves_rule_values_when_model_fails():
    parser = TravelQueryParser(FailingClient(), today=date(2026, 9, 2))

    result = await parser.parse("9月10日从北京到成都玩3天")

    assert result.origin == "北京"
    assert result.destination == "成都"
    assert result.departure_date == date(2026, 9, 10)
    assert result.days == 3
    assert result.travelers is None
    assert result.missing_fields == ("travelers",)
