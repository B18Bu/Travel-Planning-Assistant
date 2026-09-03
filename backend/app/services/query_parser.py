from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from pydantic import ValidationError

from app.models.planning import TravelQueryParseResponse
from app.models.travel import TravelPreferenceProfile
from app.services.deepseek import DeepSeekClient

logger = logging.getLogger(__name__)


class TravelQueryParser:
    """使用大模型将自然语言旅行需求转换为受控结构。"""

    _system_prompt = (
        "你是旅行需求信息抽取器。只输出 JSON，不要 Markdown 或解释。日期使用 YYYY-MM-DD。"
        "无法确定的字段填 null。对于硬性饮食限制，preference_profile.preferences 的 exclude_terms "
        "必须使用可匹配餐饮 POI 名称、标签和菜系的词。若用户明确不吃辣或禁辣，"
        "对应 preference 的 priority 必须为 must。"
        "除辣、麻辣、辣椒、红油外，还要包含无法确认清淡做法的高辣菜系标签，例如川菜、湘菜、火锅。"
    )
    _required_fields = ("origin", "destination", "departure_date", "travelers", "days")
    _model_fields = (*_required_fields, "budget", "preferences", "ambiguous_fields")
    _explicit_route_pattern = re.compile(
        r"从\s*(?P<origin>[\u4e00-\u9fff]{2,4})\s*(?:到|至|去往)\s*(?P<destination>[\u4e00-\u9fff]{2,4})(?=(?:玩|游|旅|[,，。；;]|$))"
    )
    _traveler_pattern = re.compile(
        r"(?P<count>\d{1,2}|[一二两俩三四五六七八九十]{1,3})\s*(?:位|个|名)?\s*(?:成人|大人|小孩|孩子|儿童|小朋友|老人|老年人|长者)"
    )
    _chinese_numbers = {"一": 1, "二": 2, "两": 2, "俩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

    def __init__(self, client: DeepSeekClient, *, today: date | None = None) -> None:
        self.client = client
        self.today = today or date.today()

    async def parse(self, query: str) -> TravelQueryParseResponse:
        model_succeeded = False
        model_provided_fields: frozenset[str] = frozenset()
        try:
            content = await self.client.chat_completion(
                self._system_prompt,
                json.dumps({"query": query, "fields": ["origin", "destination", "departure_date", "travelers", "days", "budget", "preferences", "preference_profile"], "preference_profile_schema": {"summary": "string|null", "companions": [{"type": "string", "count": "integer"}], "preferences": [{"category": "string", "priority": "must|prefer|avoid", "instruction": "string", "exclude_terms": ["string"], "verification_required": "boolean"}], "agent_guidance": {"route": {"instructions": ["string"], "daily_primary_limit": "integer|null", "priority_terms": ["string"]}, "food": {"instructions": ["string"], "exclude_terms": ["string"], "verification_notes": ["string"]}, "lodging": ["string"], "summary": ["string"]}, "verification_notes": ["string"]}}, ensure_ascii=False),
            )
            payload = self._json_payload(content)
            profile = self._profile(payload.pop("preference_profile", None))
            model_provided_fields = frozenset(payload)
            model_values = self._model_values(payload)
            model_succeeded = True
        except Exception as error:
            logger.warning("旅行需求大模型解析失败，返回缺失字段: %s", error)
            profile = self._fallback_profile()
            model_values = {}
        values = {
            name: model_values.get(name)
            for name in self._required_fields
        }
        if model_succeeded:
            origin, destination = self._explicit_route_locations(query)
            if "origin" not in model_provided_fields and values["origin"] is None:
                values["origin"] = origin
            if "destination" not in model_provided_fields and values["destination"] is None:
                values["destination"] = destination
            departure_date = self._current_year_date(query)
            if "departure_date" not in model_provided_fields and departure_date is not None:
                values["departure_date"] = departure_date
            if "travelers" not in model_provided_fields and values["travelers"] is None:
                values["travelers"] = self._traveler_count(query)
        preferences = tuple(dict.fromkeys(model_values.get("preferences", ())))
        return TravelQueryParseResponse(
            **values,
            budget=model_values.get("budget"),
            preferences=preferences,
            profile=profile,
            missing_fields=self._missing_fields(values),
            ambiguous_fields=model_values.get("ambiguous_fields", ()),
        )

    @staticmethod
    def _fallback_profile() -> TravelPreferenceProfile:
        return TravelPreferenceProfile(
            verification_notes=("偏好理解暂不可用，请在生成方案前核验偏好要求。",)
        )

    @classmethod
    def _profile(cls, payload: object) -> TravelPreferenceProfile:
        if payload is None:
            return cls._fallback_profile()
        try:
            return TravelPreferenceProfile.model_validate(payload)
        except (ValidationError, TypeError, ValueError):
            return cls._fallback_profile()

    @classmethod
    def _model_values(cls, payload: dict[str, Any]) -> dict[str, Any]:
        """逐字段校验模型结果，忽略无关或格式错误字段。"""

        values: dict[str, Any] = {}
        for name in cls._model_fields:
            if name not in payload:
                continue
            try:
                parsed = TravelQueryParseResponse.model_validate({name: payload[name]})
            except (ValidationError, TypeError, ValueError):
                continue
            values[name] = getattr(parsed, name)
        return values

    @staticmethod
    def _missing_fields(values: dict[str, object]) -> tuple[str, ...]:
        return tuple(name for name in TravelQueryParser._required_fields if values.get(name) is None)

    @classmethod
    def _explicit_route_locations(cls, query: str) -> tuple[str | None, str | None]:
        match = cls._explicit_route_pattern.search(query)
        if match is None:
            return None, None
        return match.group("origin"), match.group("destination")

    def _current_year_date(self, query: str) -> date | None:
        match = re.search(r"(?<!\d{4}年)(?P<month>\d{1,2})月(?P<day>\d{1,2})日", query)
        if match is None:
            return None
        try:
            return date(self.today.year, int(match.group("month")), int(match.group("day")))
        except ValueError:
            return None

    @classmethod
    def _traveler_count(cls, query: str) -> int | None:
        counts = [cls._number_value(match.group("count")) for match in cls._traveler_pattern.finditer(query)]
        if not counts or any(count is None for count in counts):
            return None
        total = sum(counts)
        return total if 1 <= total <= 20 else None

    @classmethod
    def _number_value(cls, value: str) -> int | None:
        if value.isdigit():
            return int(value)
        if value in cls._chinese_numbers:
            return cls._chinese_numbers[value]
        if len(value) == 2 and value[0] == "十" and value[1] in cls._chinese_numbers:
            return 10 + cls._chinese_numbers[value[1]]
        if len(value) == 2 and value[1] == "十" and value[0] in cls._chinese_numbers:
            return cls._chinese_numbers[value[0]] * 10
        if len(value) == 3 and value[1] == "十" and value[0] in cls._chinese_numbers and value[2] in cls._chinese_numbers:
            return cls._chinese_numbers[value[0]] * 10 + cls._chinese_numbers[value[2]]
        return None

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
