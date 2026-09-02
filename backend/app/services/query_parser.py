from __future__ import annotations

import json
import re
from typing import Any

from app.models.planning import TravelQueryParseResponse
from app.services.deepseek import DeepSeekClient


class TravelQueryParser:
    """使用大模型将自然语言旅行需求转换为受控结构。"""

    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    async def parse(self, query: str) -> TravelQueryParseResponse:
        content = await self.client.chat_completion(
            "你是旅行需求信息抽取器。只输出 JSON，不要 Markdown 或解释。日期使用 YYYY-MM-DD。无法确定的字段填 null。",
            json.dumps({"query": query, "fields": ["origin", "destination", "departure_date", "travelers", "days", "budget", "preferences"]}, ensure_ascii=False),
        )
        payload = self._json_payload(content)
        result = TravelQueryParseResponse.model_validate(payload)
        required = {
            "origin": result.origin,
            "destination": result.destination,
            "departure_date": result.departure_date,
            "travelers": result.travelers,
            "days": result.days,
        }
        missing = tuple(dict.fromkeys((*result.missing_fields, *(name for name, value in required.items() if value is None))))
        return result.model_copy(update={"missing_fields": missing})

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

