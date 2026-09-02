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
        sources: list[Source] = []
        area = request.destination
        data = LodgingPlanData(
            nights=request.nights,
            recommended_area=area,
            filter_suggestions=self._filter_suggestions(request.profile),
        )
        try:
            area = self._area(daily_areas, request.destination, request.days)
            data = LodgingPlanData(
                nights=request.nights,
                recommended_area=area,
                filter_suggestions=self._filter_suggestions(request.profile),
            )
            # 高德 region 需为单一城市名；daily_areas 的 area 可能是「四川省成都市」这类
            # 格式化地址，无法映射城市会绕过 city_limit 导致跨城市返回。
            raw_pois = await self.amap_client.search_poi("住宿服务", request.destination)
            if not isinstance(raw_pois, list):
                raise ValueError("POI 响应格式无效")
            matching_pois = [
                item
                for item in raw_pois
                if isinstance(item, dict)
                and self._matches_category(item.get("category"), "住宿服务")
            ]
            limited_pois = matching_pois[:10]
            candidates = tuple(
                LodgingCandidate(poi=self._poi(item, "amap:lodging", "住宿服务"))
                for item in limited_pois
            )
            sources = self._sources(limited_pois)
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
    def _area(
        daily_areas: tuple[Any, ...] | list[Any], destination: str, max_days: int
    ) -> str:
        if not daily_areas:
            return destination
        first = daily_areas[0]
        day = first.day if hasattr(first, "day") else first["day"]
        area = first.area if hasattr(first, "area") else first["area"]
        if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= max_days:
            raise ValueError("每日区域 day 无效")
        if not isinstance(area, str) or not area.strip():
            raise ValueError("每日区域 area 无效")
        return area

    @staticmethod
    def _filter_suggestions(profile: object | None = None) -> tuple[str, ...]:
        guidance = getattr(getattr(profile, "agent_guidance", None), "lodging", ())
        return (
            "请按活动区域、交通便利性和入住日期筛选。",
            *(f"用户偏好：{item}" for item in guidance),
        )

    @staticmethod
    def _poi(item: dict[str, Any], source_id: str, expected_category: str) -> PoiCandidate:
        if not isinstance(item, dict):
            raise TypeError("POI 项格式无效")
        tags = item.get("tags", ())
        if tags is None:
            tags = ()
        if not isinstance(tags, (list, tuple)):
            raise TypeError("POI 标签格式无效")
        category = item.get("category")
        if not isinstance(category, str):
            raise ValueError("POI 分类不匹配")
        if not LodgingAgent._matches_category(category, expected_category):
            raise ValueError("POI 分类不匹配")
        category = expected_category
        return PoiCandidate(
            name=item["name"],
            address=item.get("address"),
            location=item.get("location"),
            category=expected_category,
            tags=tuple(tags),
            source_ids=(source_id,),
        )

    @staticmethod
    def _matches_category(category: object, expected_category: str) -> bool:
        if not isinstance(category, str):
            return False
        return any(
            group.strip().split(";", 1)[0].strip() == expected_category
            for group in category.split("|")
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
            key = (
                source.name,
                source.type,
                source.data_status,
                source.source_updated_at,
                str(source.url) if source.url is not None else None,
                source.knowledge_version,
            )
            if not any(
                (
                    item.name,
                    item.type,
                    item.data_status,
                    item.source_updated_at,
                    str(item.url) if item.url is not None else None,
                    item.knowledge_version,
                ) == key
                for item in sources
            ):
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
