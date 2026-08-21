from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.models.travel import (
    AgentResult,
    AgentStatus,
    DataStatus,
    LodgingCandidate,
    LodgingPlanData,
    PoiCandidate,
    Source,
    SourceType,
    TravelPlanRequest,
)
from app.services.resilience import ExternalServiceUnavailable


class LodgingAgent:
    """按推荐区域获取住宿 POI，并生成不含交易字段的候选。"""

    def __init__(self, amap_client: Any) -> None:
        self.amap_client = amap_client

    async def run(
        self,
        request: TravelPlanRequest,
        daily_areas: tuple[Any, ...] | list[Any],
        request_id: str,
        trace_id: str,
    ) -> AgentResult[LodgingPlanData]:
        self._validate_ids(request_id, trace_id)
        area = self._area(daily_areas, request.destination)
        sources: list[Source] = []
        data = LodgingPlanData(
            nights=request.nights,
            recommended_area=area,
            filter_suggestions=("请按活动区域、交通便利性和入住日期筛选。",),
        )
        try:
            raw_pois = await self.amap_client.search_poi("住宿服务", area)
            if not isinstance(raw_pois, list):
                raise ValueError("POI 响应格式无效")
            candidates = tuple(
                LodgingCandidate(poi=self._poi(item, "amap:lodging"))
                for item in raw_pois[:10]
            )
            sources = self._sources(raw_pois)
            data = LodgingPlanData(
                nights=request.nights,
                recommended_area=area,
                candidates=candidates,
                filter_suggestions=() if candidates else data.filter_suggestions,
            )
            if not candidates:
                return self._degraded(
                    request_id, trace_id, data, sources, "lodging_candidates"
                )
            return AgentResult[LodgingPlanData](
                agent="lodging",
                status=AgentStatus.success,
                summary="已按推荐区域提供住宿位置建议。",
                data=data,
                sources=tuple(sources),
                request_id=request_id,
                trace_id=trace_id,
            )
        except (ExternalServiceUnavailable, KeyError, TypeError, ValueError, ValidationError):
            return self._degraded(
                request_id,
                trace_id,
                data,
                sources,
                "lodging_candidates",
            )

    @staticmethod
    def _area(daily_areas: tuple[Any, ...] | list[Any], destination: str) -> str:
        if daily_areas:
            first = daily_areas[0]
            return first.area if hasattr(first, "area") else first["area"]
        return destination

    @staticmethod
    def _poi(item: dict[str, Any], source_id: str) -> PoiCandidate:
        if not isinstance(item, dict):
            raise TypeError("POI 项格式无效")
        tags = item.get("tags", ())
        if tags is None:
            tags = ()
        if not isinstance(tags, (list, tuple)):
            raise TypeError("POI 标签格式无效")
        return PoiCandidate(
            name=item["name"],
            address=item.get("address"),
            location=item.get("location"),
            category=item["category"],
            tags=tuple(tags),
            source_ids=(source_id,),
        )

    @staticmethod
    def _sources(raw_pois: list[dict[str, Any]]) -> list[Source]:
        sources: list[Source] = []
        for item in raw_pois:
            source = Source(
                name="高德地图",
                type=SourceType.poi_api,
                data_status=DataStatus(item["data_status"]),
                source_updated_at=item.get("source_updated_at"),
                retrieved_at=item["retrieved_at"],
            )
            if source not in sources:
                sources.append(source)
        return sources

    @staticmethod
    def _degraded(
        request_id: str,
        trace_id: str,
        data: LodgingPlanData,
        sources: list[Source],
        missing_field: str,
    ) -> AgentResult[LodgingPlanData]:
        return AgentResult[LodgingPlanData](
            agent="lodging",
            status=AgentStatus.degraded,
            summary="住宿 POI 暂不可用，已保留区域筛选建议。",
            data=data,
            sources=tuple(sources),
            warnings=("请通过商家官方或授权平台核验住宿信息。",),
            missing_fields=(missing_field,),
            request_id=request_id,
            trace_id=trace_id,
        )

    @staticmethod
    def _validate_ids(request_id: str, trace_id: str) -> None:
        try:
            request_uuid = UUID(request_id)
            trace_uuid = UUID(trace_id)
            if (
                request_uuid.version not in {1, 2, 3, 4, 5}
                or trace_uuid.version not in {1, 2, 3, 4, 5}
                or request_uuid != trace_uuid
            ):
                raise ValueError
        except (TypeError, ValueError, AttributeError):
            raise ValueError("请求追踪标识无效") from None
