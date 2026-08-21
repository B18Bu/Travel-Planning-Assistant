from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.cache import MemoryCache
from app.services.resilience import CircuitBreaker, ExternalServiceUnavailable, request_with_retry


class HeWeatherClient:
    """和风天气逐日预报的受控只读客户端。"""

    _allowed_host = "devapi.qweather.com"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://devapi.qweather.com",
        cache: MemoryCache | None = None,
        breaker: CircuitBreaker | None = None,
        max_attempts: int = 3,
        cache_ttl_seconds: float = 1800,
        timeout: httpx.Timeout | float = 10.0,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or parsed.hostname != self._allowed_host or parsed.path not in ("", "/"):
            raise ExternalServiceUnavailable("和风天气服务地址不受支持")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts 必须在 1 到 3 之间")
        self.api_key = api_key
        self.base_url = f"https://{self._allowed_host}"
        self.cache = cache or MemoryCache()
        self.breaker = breaker or CircuitBreaker(failure_threshold=3, open_seconds=60)
        self.max_attempts = max_attempts
        self.cache_ttl_seconds = cache_ttl_seconds
        self.timeout = timeout

    async def daily_forecast(self, location_id: str, start: date, days: int) -> dict[str, Any]:
        if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
            raise ExternalServiceUnavailable("和风天气请求天数无效")
        cache_key = f"weather:{location_id}:{start.isoformat()}:{days}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return {**cached, "data_status": "cached", "retrieved_at": datetime.now(timezone.utc)}
        if not self.api_key.strip():
            raise ExternalServiceUnavailable("和风天气 API 密钥未配置")
        self.breaker.ensure_available()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retry(
                    lambda: client.get(f"{self.base_url}/v7/weather/3d", params={"location": location_id, "key": self.api_key}),
                    max_attempts=self.max_attempts,
                )
                payload = response.json()
            normalized = self._normalize(payload, start, days)
        except ExternalServiceUnavailable:
            self.breaker.record_failure()
            raise
        except (ValueError, TypeError, KeyError, AttributeError):
            self.breaker.record_failure()
            raise ExternalServiceUnavailable("和风天气未返回有效数据") from None
        self.cache.set(cache_key, normalized, ttl_seconds=self.cache_ttl_seconds)
        self.breaker.record_success()
        return {**normalized, "data_status": "realtime", "retrieved_at": datetime.now(timezone.utc)}

    @staticmethod
    def _normalize(payload: object, start: date, days: int) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("code") != "200":
            raise ExternalServiceUnavailable("和风天气未返回有效数据")
        source_updated_at = _aware_datetime(payload.get("updateTime"))
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
            daily.append({
                "date": item_date,
                "condition": item.get("textDay"),
                "temp_min": _optional_int(item.get("tempMin")),
                "temp_max": _optional_int(item.get("tempMax")),
            })
        daily.sort(key=lambda item: item["date"])
        daily = daily[: min(days, 3)]
        if not daily or any(item["condition"] is None for item in daily):
            raise ValueError("天气日期无匹配")
        return {"source_updated_at": source_updated_at, "daily": tuple(daily)}


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("更新时间缺失")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
