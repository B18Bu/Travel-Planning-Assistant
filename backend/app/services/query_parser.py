from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from app.models.planning import TravelQueryParseResponse
from app.models.travel import TravelPreferenceProfile
from app.services.deepseek import DeepSeekClient


class TravelQueryParser:
    """使用大模型将自然语言旅行需求转换为受控结构。"""

    _required_fields = ("origin", "destination", "departure_date", "travelers", "days")
    _number_values = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    _field_patterns = {
        "origin_destination": re.compile(r"从(?P<origin>[\u4e00-\u9fff]{2,20})到(?P<destination>[\u4e00-\u9fff]{2,20})(?:玩|旅游|出行|，|,|。|$)"),
        "date": re.compile(r"(?:(?P<year>20\d{2})[年./-])?(?P<month>\d{1,2})[月./-](?P<day>\d{1,2})(?:日|号)?"),
        "days": re.compile(r"(?:玩|游|旅行|出行)?\s*(?P<days>\d+)\s*天"),
        "party": re.compile(r"(?P<count>\d+|[一二两三四五六七八九十])\s*(?:位|个|名)?\s*(?:成人|大人|儿童|孩子|小孩|老人|婴儿)"),
    }

    def __init__(self, client: DeepSeekClient, *, today: date | None = None) -> None:
        self.client = client
        self.today = today or date.today()

    async def parse(self, query: str) -> TravelQueryParseResponse:
        rule_values = self._rule_values(query)
        try:
            content = await self.client.chat_completion(
                "你是旅行需求信息抽取器。只输出 JSON，不要 Markdown 或解释。日期使用 YYYY-MM-DD。无法确定的字段填 null。",
                json.dumps({"query": query, "fields": ["origin", "destination", "departure_date", "travelers", "days", "budget", "preferences", "preference_profile"], "preference_profile_schema": {"summary": "string|null", "companions": [{"type": "string", "count": "integer"}], "preferences": [{"category": "string", "priority": "must|prefer|avoid", "instruction": "string", "exclude_terms": ["string"], "verification_required": "boolean"}], "agent_guidance": {"route": ["string"], "food": ["string"], "lodging": ["string"], "summary": ["string"]}, "verification_notes": ["string"]}}, ensure_ascii=False),
            )
            payload = self._json_payload(content)
            profile = payload.pop(
                "preference_profile",
                {"verification_notes": ["偏好理解暂不可用，请在生成方案前核验偏好要求。"]},
            )
            model_result = TravelQueryParseResponse.model_validate({**payload, "profile": profile})
        except Exception:
            model_result = TravelQueryParseResponse(
                profile=TravelPreferenceProfile(
                    verification_notes=("偏好理解暂不可用，请在生成方案前核验偏好要求。",)
                )
            )
        values = {
            name: rule_values[name] if rule_values[name] is not None else getattr(model_result, name)
            for name in self._required_fields
        }
        preferences = tuple(dict.fromkeys(model_result.preferences))
        return TravelQueryParseResponse(
            **values,
            budget=model_result.budget,
            preferences=preferences,
            profile=model_result.profile,
            missing_fields=self._missing_fields(values),
            ambiguous_fields=model_result.ambiguous_fields,
        )

    def _rule_values(self, query: str) -> dict[str, object]:
        values: dict[str, object] = {name: None for name in self._required_fields}
        values["preferences"] = ()
        location = self._field_patterns["origin_destination"].search(query)
        if location:
            values["origin"] = location.group("origin")
            values["destination"] = location.group("destination")
        date_match = self._field_patterns["date"].search(query)
        if date_match:
            values["departure_date"] = self._parse_date(date_match)
        day_match = self._field_patterns["days"].search(query)
        if day_match:
            values["days"] = int(day_match.group("days"))
        party_counts = [self._parse_count(match.group("count")) for match in self._field_patterns["party"].finditer(query)]
        if party_counts and all(count is not None for count in party_counts):
            total = sum(party_counts)
            values["travelers"] = total if 1 <= total <= 20 else None
        return values

    def _parse_date(self, match: re.Match[str]) -> date | None:
        year = int(match.group("year") or self.today.year)
        try:
            parsed = date(year, int(match.group("month")), int(match.group("day")))
            return date(year + 1, parsed.month, parsed.day) if match.group("year") is None and parsed < self.today else parsed
        except ValueError:
            return None

    def _parse_count(self, value: str) -> int | None:
        return int(value) if value.isdigit() else self._number_values.get(value)

    @staticmethod
    def _missing_fields(values: dict[str, object]) -> tuple[str, ...]:
        return tuple(name for name in TravelQueryParser._required_fields if values.get(name) is None)

    @staticmethod
    def _json_payload(content: str) -> dict[str, Any]:
        candidate = content.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", candidate, re.S | re.I)
        if fenced:
            candidate = fenced.group(1)
        payload = json.loads(candidate)
        if not isinstance(payload, dict):
            raise ValueError("模型解析结果必须为对象")
        return payload
