from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from app.models.fliggy_hotel import (
    FliggyHotel,
    FliggyHotelSearchRequest,
    FliggyHotelSearchResponse,
    FliggyHotelSource,
)
from app.services.fliggy_hotel_client import (
    FliggyHotelClient,
    FliggyRawHotel,
    FliggyRawSearchResult,
)


class _HotelClient(Protocol):
    async def search_low_price(
        self,
        city_name: str,
        check_in: object,
        check_out: object,
        page_no: int,
        page_size: int,
    ) -> FliggyRawSearchResult: ...


class HotelSearchService:
    """飞猪酒店低价查询服务。"""

    def __init__(self, client: _HotelClient | FliggyHotelClient) -> None:
        self._client = client

    async def search(self, request: FliggyHotelSearchRequest, trace_id: str) -> FliggyHotelSearchResponse:
        raw_result = await self._client.search_low_price(
            request.city_name,
            request.check_in,
            request.check_out,
            request.page_no,
            request.page_size,
        )
        hotels = [
            self._to_hotel(raw_hotel)
            for raw_hotel in raw_result.hotels
            if self._is_valid(raw_hotel)
        ]
        hotels.sort(key=lambda hotel: hotel[0])
        return FliggyHotelSearchResponse(
            source=FliggyHotelSource(retrieved_at=datetime.now(timezone.utc)),
            hotels=tuple(hotel for _, hotel in hotels),
            total=raw_result.total,
            page_no=request.page_no,
            page_size=request.page_size,
            trace_id=trace_id,
        )

    @staticmethod
    def _is_valid(raw_hotel: FliggyRawHotel) -> bool:
        return (
            isinstance(raw_hotel.low_price_cents, int)
            and not isinstance(raw_hotel.low_price_cents, bool)
            and raw_hotel.low_price_cents > 0
            and (
                isinstance(raw_hotel.shid, int)
                and not isinstance(raw_hotel.shid, bool)
                or isinstance(raw_hotel.shid, str)
                and bool(raw_hotel.shid.strip())
            )
            and isinstance(raw_hotel.name, str)
            and bool(raw_hotel.name.strip())
        )

    @staticmethod
    def _to_hotel(raw_hotel: FliggyRawHotel) -> tuple[int, FliggyHotel]:
        cents = raw_hotel.low_price_cents
        return cents, FliggyHotel(
            hotel_id=str(raw_hotel.shid),
            name=raw_hotel.name,
            low_price=Decimal(cents) / Decimal(100),
        )
