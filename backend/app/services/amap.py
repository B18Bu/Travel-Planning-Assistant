from __future__ import annotations

from copy import deepcopy
import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

import httpx

from app.services.cache import MemoryCache
from app.services.resilience import CircuitBreaker, ExternalServiceUnavailable, request_with_retry


class AmapClient:
    """高德地理编码、驾车路线和文本 POI 的受控只读客户端。"""

    _base_url = "https://restapi.amap.com"

    def __init__(self, api_key: str, base_url: str = _base_url, cache: MemoryCache | None = None, breaker: CircuitBreaker | None = None, max_attempts: int = 3, geocode_cache_ttl_seconds: int = 604800, route_cache_ttl_seconds: int = 900, poi_cache_ttl_seconds: int = 3600, timeout: httpx.Timeout | float = 10.0) -> None:
        if base_url != self._base_url:
            raise ExternalServiceUnavailable("高德地图服务地址不受支持")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts 必须在 1 到 3 之间")
        for ttl in (geocode_cache_ttl_seconds, route_cache_ttl_seconds, poi_cache_ttl_seconds):
            if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= 0:
                raise ValueError("缓存 TTL 必须为正整数")
        self.api_key = api_key
        self.cache = cache or MemoryCache()
        self.breaker = breaker or CircuitBreaker(3, 60)
        self.max_attempts = max_attempts
        self.geocode_cache_ttl_seconds = geocode_cache_ttl_seconds
        self.route_cache_ttl_seconds = route_cache_ttl_seconds
        self.poi_cache_ttl_seconds = poi_cache_ttl_seconds
        self.timeout = timeout

    async def geocode(self, address: str) -> dict[str, Any]:
        self._require_text(address, "高德地图请求地址无效")
        result = await self._get("geocode", [address], "/v3/geocode/geo", {"address": address}, self.geocode_cache_ttl_seconds)
        item = result["data"]
        if not isinstance(item, dict) or not _non_empty_text(item.get("name")) or not _optional_text(item.get("location")) or not _optional_text(item.get("adcode")):
            raise ExternalServiceUnavailable("高德地图未找到地点")
        return {**deepcopy(item), **self._metadata(result)}

    async def driving_route(self, origin: str, destination: str) -> dict[str, Any]:
        self._require_text(origin, "高德地图请求起点无效")
        self._require_text(destination, "高德地图请求终点无效")
        result = await self._get("route", [origin, destination], "/v3/direction/driving", {"origin": origin, "destination": destination}, self.route_cache_ttl_seconds)
        item = result["data"]
        if not isinstance(item, dict) or not _non_negative_int(item.get("distance_meters")) or not _non_negative_int(item.get("duration_minutes")):
            raise ExternalServiceUnavailable("高德地图未返回有效路线")
        return {**deepcopy(item), **self._metadata(result)}

    async def search_poi(self, keywords: str, city: str) -> list[dict[str, Any]]:
        self._require_text(keywords, "高德地图请求关键词无效")
        self._require_text(city, "高德地图请求城市无效")
        result = await self._get("poi", [keywords, city], "/v5/place/text", {"keywords": keywords, "region": city, "city_limit": "true"}, self.poi_cache_ttl_seconds)
        pois = result["data"]
        if not isinstance(pois, list):
            raise ExternalServiceUnavailable("高德地图未返回有效 POI")
        for item in pois:
            if not isinstance(item, dict) or not _non_empty_text(item.get("name")) or not _non_empty_text(item.get("category")) or not _optional_text(item.get("address")) or not _optional_text(item.get("location")):
                raise ExternalServiceUnavailable("高德地图未返回有效 POI")
        return [{**deepcopy(item), **self._metadata(result)} for item in pois]

    async def search_nearby_poi(self, keywords: str, location: str, radius_meters: int) -> list[dict[str, Any]]:
        self._require_text(keywords, "高德地图请求关键词无效")
        self._require_text(location, "高德地图请求位置无效")
        if not isinstance(radius_meters, int) or isinstance(radius_meters, bool) or radius_meters <= 0:
            raise ExternalServiceUnavailable("高德地图请求半径无效")
        result = await self._get(
            "nearby_poi",
            [keywords, location, str(radius_meters)],
            "/v5/place/around",
            {"keywords": keywords, "location": location, "radius": str(radius_meters)},
            self.poi_cache_ttl_seconds,
        )
        pois = result["data"]
        if not isinstance(pois, list):
            raise ExternalServiceUnavailable("高德地图未返回有效 POI")
        for item in pois:
            if not isinstance(item, dict) or not _non_empty_text(item.get("name")) or not _non_empty_text(item.get("category")) or not _optional_text(item.get("address")) or not _optional_text(item.get("location")):
                raise ExternalServiceUnavailable("高德地图未返回有效 POI")
        return [{**deepcopy(item), **self._metadata(result)} for item in pois]

    async def _get(self, operation: str, args: list[str], path: str, params: dict[str, str], ttl_seconds: float) -> dict[str, Any]:
        self._require_key()
        cache_key = self._cache_key(operation, args)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.breaker.record_cache_hit()
            return {**deepcopy(cached), "data_status": "cached", "retrieved_at": datetime.now(timezone.utc)}
        token = self.breaker.ensure_available()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retry(lambda: client.get(f"{self._base_url}{path}", params={**params, "key": self.api_key}), max_attempts=self.max_attempts)
                if not 200 <= response.status_code < 300:
                    raise ExternalServiceUnavailable("高德地图未返回有效数据")
                payload = response.json()
            if not isinstance(payload, dict) or payload.get("status") != "1":
                raise ExternalServiceUnavailable("高德地图未返回有效数据")
            mapped = self._project(path, payload)
        except ExternalServiceUnavailable:
            self.breaker.record_failure(token)
            raise
        except (ValueError, TypeError, KeyError, AttributeError):
            self.breaker.record_failure(token)
            raise ExternalServiceUnavailable("高德地图未返回有效数据") from None
        self.cache.set(cache_key, {"data": deepcopy(mapped), "data_status": "realtime", "source_updated_at": _source_updated_at(payload), "retrieved_at": datetime.now(timezone.utc)}, ttl_seconds=ttl_seconds)
        self.breaker.record_success(token)
        return deepcopy(self.cache.get(cache_key))

    def _cache_key(self, operation: str, args: list[str]) -> str:
        fingerprint = sha256(self.api_key.encode("utf-8")).hexdigest()[:16]
        return json.dumps(["amap", fingerprint, operation, args], ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _project(path: str, payload: dict[str, Any]) -> object:
        if path == "/v3/geocode/geo":
            items = payload.get("geocodes")
            if not isinstance(items, list) or not items or not isinstance(items[0], dict):
                raise ExternalServiceUnavailable("高德地图未找到地点")
            item = items[0]
            mapped = {"name": item.get("formatted_address"), "location": item.get("location"), "adcode": item.get("adcode")}
            if not _non_empty_text(mapped["name"]) or not _optional_text(mapped["location"]) or not _optional_text(mapped["adcode"]):
                raise ExternalServiceUnavailable("高德地图未找到地点")
            return mapped
        if path == "/v3/direction/driving":
            route = payload.get("route")
            paths = route.get("paths") if isinstance(route, dict) else None
            if not isinstance(paths, list) or not paths or not isinstance(paths[0], dict):
                raise ExternalServiceUnavailable("高德地图未返回有效路线")
            path_item = paths[0]
            if not _strict_int_string(path_item.get("distance")) or not _strict_int_string(path_item.get("duration")) or int(path_item["distance"]) < 0 or int(path_item["duration"]) < 0:
                raise ExternalServiceUnavailable("高德地图未返回有效路线")
            return {"distance_meters": int(path_item["distance"]), "duration_minutes": round(int(path_item["duration"]) / 60)}
        if path not in {"/v5/place/text", "/v5/place/around"}:
            raise ExternalServiceUnavailable("高德地图未返回有效数据")
        pois = payload.get("pois", [])
        if not isinstance(pois, list):
            raise ExternalServiceUnavailable("高德地图未返回有效 POI")
        mapped = []
        for item in pois[:10]:
            if not isinstance(item, dict):
                raise ExternalServiceUnavailable("高德地图未返回有效 POI")
            candidate = {
                "name": item.get("name"),
                "address": item.get("address"),
                "location": item.get("location"),
                "category": item.get("type"),
                "tags": _normalize_tags(item.get("tags")),
            }
            if not _non_empty_text(candidate["name"]) or not _non_empty_text(candidate["category"]) or not _optional_text(candidate["address"]) or not _optional_text(candidate["location"]):
                raise ExternalServiceUnavailable("高德地图未返回有效 POI")
            mapped.append(candidate)
        return mapped

    def _require_key(self) -> None:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ExternalServiceUnavailable("高德地图 API 密钥未配置")

    @staticmethod
    def _require_text(value: object, message: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ExternalServiceUnavailable(message)

    @staticmethod
    def _metadata(result: dict[str, Any]) -> dict[str, Any]:
        return {"data_status": result["data_status"], "source_updated_at": result.get("source_updated_at"), "retrieved_at": result["retrieved_at"]}


def _normalize_tags(value: object) -> tuple[str, ...]:
    """将高德 tags 规整为非空字符串元组，去重并限长。"""
    if not isinstance(value, (list, tuple)):
        return ()
    collected: list[str] = []
    for tag in value:
        if not isinstance(tag, str):
            continue
        text = tag.strip()
        if not text or len(text) > 100 or text in collected:
            continue
        collected.append(text)
        if len(collected) >= 10:
            break
    return tuple(collected)


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _optional_text(value: object) -> bool:
    return value is None or _non_empty_text(value)


def _strict_int_string(value: object) -> bool:
    if isinstance(value, bool) or isinstance(value, float) or isinstance(value, (list, dict)):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and value.strip().lstrip("-").isdigit()


def _non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _source_updated_at(payload: dict[str, Any]) -> datetime | None:
    for key in ("updateTime", "update_time"):
        value = payload.get(key)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                return None
    return None
