from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.cache import MemoryCache
from app.services.resilience import CircuitBreaker, ExternalServiceUnavailable, request_with_retry


class AmapClient:
    """高德地理编码、驾车路线和文本 POI 的受控只读客户端。"""

    _allowed_host = "restapi.amap.com"

    def __init__(self, api_key: str, base_url: str = "https://restapi.amap.com", cache: MemoryCache | None = None, breaker: CircuitBreaker | None = None, max_attempts: int = 3, geocode_cache_ttl_seconds: float = 604800, route_cache_ttl_seconds: float = 900, poi_cache_ttl_seconds: float = 3600, timeout: httpx.Timeout | float = 10.0) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or parsed.hostname != self._allowed_host or parsed.path not in ("", "/"):
            raise ExternalServiceUnavailable("高德地图服务地址不受支持")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts 必须在 1 到 3 之间")
        self.api_key = api_key
        self.base_url = f"https://{self._allowed_host}"
        self.cache = cache or MemoryCache()
        self.breaker = breaker or CircuitBreaker(3, 60)
        self.max_attempts = max_attempts
        self.geocode_cache_ttl_seconds = geocode_cache_ttl_seconds
        self.route_cache_ttl_seconds = route_cache_ttl_seconds
        self.poi_cache_ttl_seconds = poi_cache_ttl_seconds
        self.timeout = timeout

    async def geocode(self, address: str) -> dict[str, Any]:
        result = await self._get("/v3/geocode/geo", {"address": address}, f"geocode:{address}", self.geocode_cache_ttl_seconds)
        item = result["data"].get("geocode")
        if not isinstance(item, dict) or not item.get("location"):
            raise ExternalServiceUnavailable("高德地图未找到地点")
        return {"name": item.get("name") or address, "location": item["location"], "adcode": item.get("adcode"), **self._metadata(result)}

    async def driving_route(self, origin: str, destination: str) -> dict[str, Any]:
        result = await self._get("/v5/direction/driving", {"origin": origin, "destination": destination}, f"route:{origin}:{destination}", self.route_cache_ttl_seconds)
        route = result["data"].get("route")
        if not isinstance(route, dict) or not isinstance(route.get("distance_meters"), int) or not isinstance(route.get("duration_minutes"), int):
            raise ExternalServiceUnavailable("高德地图未返回有效路线")
        return {**route, **self._metadata(result)}

    async def search_poi(self, keywords: str, city: str) -> list[dict[str, Any]]:
        result = await self._get("/v5/place/text", {"keywords": keywords, "city": city, "citylimit": "true"}, f"poi:{keywords}:{city}", self.poi_cache_ttl_seconds)
        pois = result["data"].get("pois", [])
        if not isinstance(pois, list) or any(not isinstance(item, dict) for item in pois):
            raise ExternalServiceUnavailable("高德地图未返回有效 POI")
        return [{**item, **self._metadata(result)} for item in pois]

    async def _get(self, path: str, params: dict[str, str], cache_key: str, ttl_seconds: float) -> dict[str, Any]:
        if not self.api_key.strip():
            raise ExternalServiceUnavailable("高德地图 API 密钥未配置")
        cached = self.cache.get(cache_key)
        if cached is not None:
            return {**cached, "data_status": "cached", "retrieved_at": datetime.now(timezone.utc)}
        self.breaker.ensure_available()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retry(lambda: client.get(f"{self.base_url}{path}", params={**params, "key": self.api_key}), max_attempts=self.max_attempts)
                payload = response.json()
            if not isinstance(payload, dict) or payload.get("status") != "1":
                raise ExternalServiceUnavailable("高德地图未返回有效数据")
            envelope = {"data": payload, "data_status": "realtime", "source_updated_at": None, "retrieved_at": datetime.now(timezone.utc)}
            mapped = self._project_cache(path, envelope)
        except ExternalServiceUnavailable:
            self.breaker.record_failure()
            raise
        except (ValueError, TypeError, KeyError, AttributeError):
            self.breaker.record_failure()
            raise ExternalServiceUnavailable("高德地图未返回有效数据") from None
        self.cache.set(cache_key, mapped, ttl_seconds=ttl_seconds)
        self.breaker.record_success()
        return mapped

    @staticmethod
    def _project_cache(path: str, envelope: dict[str, Any]) -> dict[str, Any]:
        payload = envelope["data"]
        metadata = {"data_status": "realtime", "source_updated_at": None, "retrieved_at": envelope["retrieved_at"]}
        if path == "/v3/geocode/geo":
            items = payload.get("geocodes")
            if not isinstance(items, list) or not items or not isinstance(items[0], dict) or not items[0].get("location"):
                raise ExternalServiceUnavailable("高德地图未找到地点")
            item = items[0]
            return {"data": {"geocode": {"name": item.get("formatted_address"), "location": item.get("location"), "adcode": item.get("adcode")}}, **metadata}
        if path == "/v5/direction/driving":
            route = payload.get("route")
            paths = route.get("paths") if isinstance(route, dict) else None
            if not isinstance(paths, list) or not paths or not isinstance(paths[0], dict):
                raise ExternalServiceUnavailable("高德地图未返回有效路线")
            try:
                data = {"distance_meters": int(paths[0]["distance"]), "duration_minutes": round(int(paths[0]["duration"]) / 60)}
            except (KeyError, TypeError, ValueError):
                raise ExternalServiceUnavailable("高德地图未返回有效路线") from None
            return {"data": {"route": data}, **metadata}
        pois = payload.get("pois", [])
        if not isinstance(pois, list) or any(not isinstance(item, dict) for item in pois[:10]):
            raise ExternalServiceUnavailable("高德地图未返回有效 POI")
        return {"data": {"pois": [{"name": item.get("name"), "address": item.get("address"), "location": item.get("location"), "category": item.get("type")} for item in pois[:10]]}, **metadata}

    @staticmethod
    def _metadata(result: dict[str, Any]) -> dict[str, Any]:
        return {"data_status": result["data_status"], "source_updated_at": None, "retrieved_at": result["retrieved_at"]}
