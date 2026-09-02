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

    def __init__(self, client: DeepSeekClient, *, today: date | None = None) -> None:
        self.client = client
        self.today = today or date.today()

    async def parse(self, query: str) -> TravelQueryParseResponse:
        try:
            content = await self.client.chat_completion(
                self._system_prompt,
                json.dumps({"query": query, "fields": ["origin", "destination", "departure_date", "travelers", "days", "budget", "preferences", "preference_profile"], "preference_profile_schema": {"summary": "string|null", "companions": [{"type": "string", "count": "integer"}], "preferences": [{"category": "string", "priority": "must|prefer|avoid", "instruction": "string", "exclude_terms": ["string"], "verification_required": "boolean"}], "agent_guidance": {"route": {"instructions": ["string"], "daily_primary_limit": "integer|null", "priority_terms": ["string"]}, "food": {"instructions": ["string"], "exclude_terms": ["string"], "verification_notes": ["string"]}, "lodging": ["string"], "summary": ["string"]}, "verification_notes": ["string"]}}, ensure_ascii=False),
            )
            payload = self._json_payload(content)
            profile = self._profile(payload.pop("preference_profile", None))
            model_values = self._model_values(payload)
        except Exception as error:
            logger.warning("旅行需求大模型解析失败，返回缺失字段: %s", error)
            profile = self._fallback_profile()
            model_values = {}
        values = {
            name: model_values.get(name)
            for name in self._required_fields
        }
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
