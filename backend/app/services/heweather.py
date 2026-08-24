from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import Any

import httpx

from app.services.cache import MemoryCache
from app.services.resilience import CircuitBreaker, ExternalServiceUnavailable, request_with_retry


class HeWeatherClient:
    """和风天气逐日预报的受控只读客户端。"""

    _base_url = "https://pb5ctx5qqr.re.qweatherapi.com"

    def __init__(self, api_key: str, base_url: str = _base_url, cache: MemoryCache | None = None, breaker: CircuitBreaker | None = None, max_attempts: int = 3, cache_ttl_seconds: int = 1800, timeout: httpx.Timeout | float = 10.0) -> None:
        if base_url != self._base_url:
            raise ExternalServiceUnavailable("和风天气服务地址不受支持")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts 必须在 1 到 3 之间")
        if not isinstance(cache_ttl_seconds, int) or isinstance(cache_ttl_seconds, bool) or cache_ttl_seconds <= 0:
            raise ValueError("cache_ttl_seconds 必须为正整数")
        self.api_key = api_key
        self.cache = cache or MemoryCache()
        self.breaker = breaker or CircuitBreaker(3, 60)
        self.max_attempts = max_attempts
        self.cache_ttl_seconds = cache_ttl_seconds
        self.timeout = timeout

    async def daily_forecast(self, location_id: str, start: date, days: int) -> dict[str, Any]:
        self._require_key()
        if not isinstance(location_id, str) or not location_id.strip():
            raise ExternalServiceUnavailable("和风天气请求地点无效")
        if type(start) is not date:
            raise ExternalServiceUnavailable("和风天气请求日期无效")
        if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
            raise ExternalServiceUnavailable("和风天气请求天数无效")
        effective_days = min(days, 15)
        cache_key = self._cache_key(location_id, start, effective_days)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.breaker.record_cache_hit()
            return {
                **deepcopy(cached),
                "data_status": "cached",
                "retrieved_at": datetime.now(timezone.utc),
            }
        token = self.breaker.ensure_available()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retry(lambda: client.get(f"{self._base_url}/v7/weather/15d", params={"location": location_id, "key": self.api_key}), max_attempts=self.max_attempts)
                if not 200 <= response.status_code < 300:
                    raise ExternalServiceUnavailable("和风天气未返回有效数据")
                payload = response.json()
            normalized = self._normalize(payload, start, effective_days)
        except ExternalServiceUnavailable:
            self.breaker.record_failure(token)
            raise
        except (ValueError, TypeError, KeyError, AttributeError):
            self.breaker.record_failure(token)
            raise ExternalServiceUnavailable("和风天气未返回有效数据") from None
        self.cache.set(cache_key, deepcopy(normalized), ttl_seconds=self.cache_ttl_seconds)
        self.breaker.record_success(token)
        return {
            **deepcopy(normalized),
            "data_status": "realtime",
            "retrieved_at": datetime.now(timezone.utc),
        }

    def _require_key(self) -> None:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ExternalServiceUnavailable("和风天气 API 密钥未配置")

    def _cache_key(self, location_id: str, start: date, effective_days: int) -> str:
        fingerprint = sha256(self.api_key.encode("utf-8")).hexdigest()[:16]
        return json.dumps(
            ["weather", fingerprint, location_id, start.isoformat(), effective_days],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _normalize(payload: object, start: date, days: int) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("code") != "200":
            raise ExternalServiceUnavailable("和风天气未返回有效数据")
        source_updated_at = _optional_aware_datetime(payload.get("updateTime"))
        raw_daily = payload.get("daily")
        if not isinstance(raw_daily, list):
            raise ValueError("天气 daily 结构错误")
        daily: list[dict[str, Any]] = []
        for item in raw_daily:
            if not isinstance(item, dict):
                raise ValueError("天气 daily 项结构错误")
            item_date = date.fromisoformat(item["fxDate"])
            if item_date < start:
                continue
            condition = item.get("textDay")
            if not isinstance(condition, str) or not condition.strip():
                raise ValueError("天气状况无效")
            daily.append({"date": item_date, "condition": condition, "temp_min": _optional_int(item.get("tempMin")), "temp_max": _optional_int(item.get("tempMax"))})
        daily.sort(key=lambda item: item["date"])
        daily = daily[:days]
        if not daily:
            raise ValueError("天气日期无匹配")
        return {"source_updated_at": source_updated_at, "daily": tuple(daily)}


def _optional_aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("温度类型无效")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise ValueError("温度类型无效")
