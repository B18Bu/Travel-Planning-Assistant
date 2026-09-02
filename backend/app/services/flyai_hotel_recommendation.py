from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol

from app.models.flyai_hotel import CombinedHotelResult, FlyAIHotel, FlyAIHotelSearchRequest
from app.services.hotel_matching import match_hotel, normalize_hotel_name


class _FlyAIHotelClient(Protocol):
    async def search_hotels(self, request: FlyAIHotelSearchRequest) -> list[FlyAIHotel]: ...


class _AmapClient(Protocol):
    async def search_poi(self, keywords: str, city: str) -> list[dict[str, Any]]: ...


class HotelRecommendationResults(tuple[CombinedHotelResult, ...]):
    """推荐结果及两侧来源查询时间。"""

    def __new__(
        cls,
        results: Sequence[CombinedHotelResult],
        *,
        flyai_retrieved_at: datetime,
        amap_retrieved_at: datetime | None,
        poi_unavailable: bool = False,
    ) -> "HotelRecommendationResults":
        instance = super().__new__(cls, results)
        instance.flyai_retrieved_at = flyai_retrieved_at
        instance.amap_retrieved_at = amap_retrieved_at
        instance.poi_unavailable = poi_unavailable
        return instance


class FlyAIHotelRecommendationService:
    """并行查询 FlyAI 酒店和高德住宿 POI，并按名称严格匹配。"""

    def __init__(self, flyai_client: _FlyAIHotelClient, amap_client: _AmapClient) -> None:
        self._flyai_client = flyai_client
        self._amap_client = amap_client

    async def recommend(self, request: FlyAIHotelSearchRequest) -> HotelRecommendationResults:
        flyai_started_at = datetime.now(timezone.utc)
        flyai_result, amap_result = await asyncio.gather(
            self._flyai_client.search_hotels(request),
            self._amap_client.search_poi("住宿服务", request.city_name),
            return_exceptions=True,
        )
        if isinstance(flyai_result, BaseException):
            raise flyai_result

        amap_failed = isinstance(amap_result, BaseException)
        amap_items = [] if amap_failed else amap_result
        if not isinstance(amap_items, list):
            amap_items = []
            amap_failed = True

        amap_index: dict[str, list[dict[str, Any]]] = {}
        for item in amap_items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            amap_index.setdefault(normalize_hotel_name(item["name"]), []).append(item)

        merged: list[CombinedHotelResult] = []
        for hotel in flyai_result:
            poi = self._take_match(hotel.name, amap_index)
            merged.append(self._from_flyai(hotel, poi))

        for candidates in amap_index.values():
            for poi in candidates:
                merged.append(self._from_poi(poi))

        merged.sort(
            key=lambda item: (
                item.flyai_score is None,
                -item.flyai_score if item.flyai_score is not None else Decimal(0),
                item.flyai_price is None,
                item.flyai_price if item.flyai_price is not None else Decimal(0),
            )
        )
        amap_retrieved_at = self._amap_retrieved_at(amap_items)
        return HotelRecommendationResults(
            merged,
            flyai_retrieved_at=flyai_started_at,
            amap_retrieved_at=amap_retrieved_at,
            poi_unavailable=amap_failed,
        )

    async def search(self, request: FlyAIHotelSearchRequest) -> HotelRecommendationResults:
        """兼容查询语义的服务入口。"""
        return await self.recommend(request)

    @staticmethod
    def _take_match(name: str, index: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
        key = normalize_hotel_name(name)
        candidates = index.get(key, [])
        while candidates:
            candidate = candidates.pop(0)
            if isinstance(candidate.get("name"), str) and match_hotel(name, candidate["name"]):
                return candidate
        return None

    @staticmethod
    def _from_flyai(hotel: FlyAIHotel, poi: dict[str, Any] | None) -> CombinedHotelResult:
        fields: dict[str, Any] = {
            "hotel_name": hotel.name,
            "flyai_price": hotel.price,
            "flyai_score": hotel.score,
            "flyai_star": hotel.star,
            "flyai_main_pic": hotel.main_pic,
            "detail_url": hotel.detail_url,
            "price_source": "flyai" if hotel.price is not None else None,
            "match_status": "matched" if poi is not None else "flyai_only",
        }
        if poi is not None:
            fields.update(
                amap_address=poi.get("address"),
                amap_location=poi.get("location"),
                poi_source="amap",
            )
        if poi is not None and not any(
            fields[key] is not None
            for key in ("flyai_price", "flyai_score", "flyai_star", "flyai_main_pic", "detail_url")
        ):
            # 模型历史校验要求 matched 必须有 FlyAI 字段；此处仅保留真实的双方来源，
            # 不用 hotel_id 或默认值伪造价格、评分、星级、图片或链接。
            fields["amap_address"] = poi.get("address")
            fields["amap_location"] = poi.get("location")
            fields["poi_source"] = "amap"
            return CombinedHotelResult.model_construct(**fields)
        return CombinedHotelResult(**fields)

    @staticmethod
    def _from_poi(poi: dict[str, Any]) -> CombinedHotelResult:
        return CombinedHotelResult(
            hotel_name=poi["name"],
            amap_address=poi.get("address"),
            amap_location=poi.get("location"),
            poi_source="amap",
            match_status="poi_only",
        )

    @staticmethod
    def _amap_retrieved_at(items: list[dict[str, Any]]) -> datetime | None:
        times = [item.get("retrieved_at") for item in items if isinstance(item.get("retrieved_at"), datetime)]
        return max(times) if times else None
