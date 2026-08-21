from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.services.cache import MemoryCache
from app.services.resilience import (
    CircuitBreaker,
    ExternalServiceUnavailable,
    request_with_retry,
)


class HeWeatherClient:
    """和风天气逐日预报的受控只读客户端。"""

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
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.cache = cache or MemoryCache()
        self.breaker = breaker or CircuitBreaker(failure_threshold=3, open_seconds=60)
        self.max_attempts = max_attempts
        self.cache_ttl_seconds = cache_ttl_seconds
        self.timeout = timeout

    async def daily_forecast(self, location_id: str, start: date, days: int) -> dict[str, Any]:
        """返回不含供应商原始字段的逐日天气事实。"""

        if not self.api_key.strip():
            raise ExternalServiceUnavailable("和风天气 API 密钥未配置")

        cache_key = f"weather:{location_id}:{start.isoformat()}:{days}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return {
                **cached,
                "data_status": "cached",
                "retrieved_at": datetime.now(timezone.utc),
            }

        self.breaker.ensure_available()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retry(
                    lambda: client.get(
                        f"{self.base_url}/v7/weather/3d",
                        params={"location": location_id, "key": self.api_key},
                    ),
                    max_attempts=self.max_attempts,
                )
                payload = response.json()
            if payload.get("code") != "200":
                raise ExternalServiceUnavailable("和风天气未返回有效数据")
            normalized = self._normalize(payload, days)
        except ExternalServiceUnavailable:
            self.breaker.record_failure()
            raise
        except (ValueError, TypeError, KeyError):
            self.breaker.record_failure()
            raise ExternalServiceUnavailable("和风天气未返回有效数据") from None

        self.cache.set(cache_key, normalized, ttl_seconds=self.cache_ttl_seconds)
        self.breaker.record_success()
        return {
            **normalized,
            "data_status": "realtime",
            "retrieved_at": datetime.now(timezone.utc),
        }

    @staticmethod
    def _normalize(payload: dict[str, Any], days: int) -> dict[str, Any]:
        source_updated_at = _aware_datetime(payload.get("updateTime"))
        daily = tuple(
            {
                "date": date.fromisoformat(item["fxDate"]),
                "condition": item.get("textDay"),
                "temp_min": _optional_int(item.get("tempMin")),
                "temp_max": _optional_int(item.get("tempMax")),
            }
            for item in payload.get("daily", [])[:days]
        )
        if not daily or any(item["condition"] is None for item in daily):
            raise ValueError("天气字段缺失")
        return {"source_updated_at": source_updated_at, "daily": daily}


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("更新时间缺失")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
