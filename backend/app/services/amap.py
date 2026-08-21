from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.services.cache import MemoryCache
from app.services.resilience import (
    CircuitBreaker,
    ExternalServiceUnavailable,
    request_with_retry,
)


class AmapClient:
    """高德地理编码、驾车路线和文本 POI 的受控只读客户端。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://restapi.amap.com",
        cache: MemoryCache | None = None,
        breaker: CircuitBreaker | None = None,
        max_attempts: int = 3,
        geocode_cache_ttl_seconds: float = 604800,
        route_cache_ttl_seconds: float = 900,
        poi_cache_ttl_seconds: float = 3600,
        timeout: httpx.Timeout | float = 10.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.cache = cache or MemoryCache()
        self.breaker = breaker or CircuitBreaker(failure_threshold=3, open_seconds=60)
        self.max_attempts = max_attempts
        self.geocode_cache_ttl_seconds = geocode_cache_ttl_seconds
        self.route_cache_ttl_seconds = route_cache_ttl_seconds
        self.poi_cache_ttl_seconds = poi_cache_ttl_seconds
        self.timeout = timeout

    async def geocode(self, address: str) -> dict[str, Any]:
        envelope = await self._get(
            "/v3/geocode/geo", {"address": address}, f"geocode:{address}", self.geocode_cache_ttl_seconds
        )
        items = envelope["payload"].get("geocodes")
        if not isinstance(items, list) or not items or not items[0].get("location"):
            raise ExternalServiceUnavailable("高德地图未找到地点")
        item = items[0]
        return {
            "name": item.get("formatted_address") or address,
            "location": item["location"],
            "adcode": item.get("adcode"),
            **self._metadata(envelope),
        }

    async def driving_route(self, origin: str, destination: str) -> dict[str, Any]:
        envelope = await self._get(
            "/v5/direction/driving",
            {"origin": origin, "destination": destination},
            f"route:{origin}:{destination}",
            self.route_cache_ttl_seconds,
        )
        paths = envelope["payload"].get("route", {}).get("paths", [])
        if not isinstance(paths, list) or not paths:
            raise ExternalServiceUnavailable("高德地图未返回有效路线")
        path = paths[0]
        try:
            result = {
                "distance_meters": int(path["distance"]),
                "duration_minutes": round(int(path["duration"]) / 60),
            }
        except (KeyError, TypeError, ValueError):
            raise ExternalServiceUnavailable("高德地图未返回有效路线") from None
        return {**result, **self._metadata(envelope)}

    async def search_poi(self, keywords: str, city: str) -> list[dict[str, Any]]:
        envelope = await self._get(
            "/v5/place/text",
            {"keywords": keywords, "city": city, "citylimit": "true"},
            f"poi:{keywords}:{city}",
            self.poi_cache_ttl_seconds,
        )
        pois = envelope["payload"].get("pois", [])
        if not isinstance(pois, list):
            raise ExternalServiceUnavailable("高德地图未返回有效 POI")
        return [
            {
                "name": item.get("name"),
                "address": item.get("address"),
                "location": item.get("location"),
                "category": item.get("type"),
                **self._metadata(envelope),
            }
            for item in pois[:10]
        ]

    async def _get(
        self,
        path: str,
        params: dict[str, str],
        cache_key: str,
        ttl_seconds: float,
    ) -> dict[str, Any]:
        if not self.api_key.strip():
            raise ExternalServiceUnavailable("高德地图 API 密钥未配置")
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
                        f"{self.base_url}{path}", params={**params, "key": self.api_key}
                    ),
                    max_attempts=self.max_attempts,
                )
                payload = response.json()
            if not isinstance(payload, dict) or payload.get("status") != "1":
                raise ExternalServiceUnavailable("高德地图未返回有效数据")
        except ExternalServiceUnavailable:
            self.breaker.record_failure()
            raise
        except (ValueError, TypeError, KeyError):
            self.breaker.record_failure()
            raise ExternalServiceUnavailable("高德地图未返回有效数据") from None

        source_updated_at = _source_time(payload)
        envelope = {
            "payload": payload,
            "data_status": "realtime",
            "source_updated_at": source_updated_at,
            "retrieved_at": datetime.now(timezone.utc),
        }
        self.cache.set(cache_key, envelope, ttl_seconds=ttl_seconds)
        self.breaker.record_success()
        return envelope

    @staticmethod
    def _metadata(envelope: dict[str, Any]) -> dict[str, Any]:
        return {
            "data_status": envelope["data_status"],
            "source_updated_at": envelope["source_updated_at"],
            "retrieved_at": envelope["retrieved_at"],
        }


def _source_time(payload: dict[str, Any]) -> datetime:
    for key in ("updateTime", "update_time", "info"):
        value = payload.get(key)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return datetime.now(timezone.utc)
