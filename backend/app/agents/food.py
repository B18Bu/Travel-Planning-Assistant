from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.models.travel import (
    AgentResult,
    AgentStatus,
    DailyFoodPlan,
    DataStatus,
    FoodCandidate,
    FoodPlanData,
    PoiCandidate,
    Source,
    SourceType,
    TravelPlanRequest,
)
from app.services.resilience import ExternalServiceUnavailable


class FoodAgent:
    """按每日活动区域获取餐饮 POI，并保留无结果日期。"""

    def __init__(self, amap_client: Any) -> None:
        self.amap_client = amap_client

    async def run(
        self,
        request: TravelPlanRequest,
        daily_areas: tuple[Any, ...] | list[Any],
        request_id: str,
        trace_id: str,
    ) -> AgentResult[FoodPlanData]:
        self._validate_ids(request_id, trace_id)
        daily_plans: list[DailyFoodPlan] = []
        sources: list[Source] = []
        missing_fields: list[str] = []
        for daily_area in daily_areas:
            day, area = self._daily_area(daily_area)
            try:
                raw_pois = await self.amap_client.search_poi("餐饮服务", area)
                if not isinstance(raw_pois, list):
                    raise ValueError("POI 响应格式无效")
                candidates = tuple(
                    FoodCandidate(poi=self._poi(item, "amap:food"))
                    for item in raw_pois[:10]
                )
                self._append_sources(sources, raw_pois)
            except (ExternalServiceUnavailable, KeyError, TypeError, ValueError, ValidationError):
                candidates = ()
            suggestions = () if candidates else ("请按营业时段、菜系与活动区域筛选，并以商家官方信息为准。",)
            if not candidates:
                missing_fields.append(f"food_day_{day}_candidates")
            daily_plans.append(
                DailyFoodPlan(
                    day=day,
                    area=area,
                    meal_period=None,
                    candidates=candidates,
                    filter_suggestions=suggestions,
                )
            )
        data = FoodPlanData(daily_food=tuple(daily_plans))
        if len(missing_fields) == len(daily_plans):
            status = AgentStatus.degraded
        elif missing_fields:
            status = AgentStatus.partial
        else:
            status = AgentStatus.success
        return AgentResult[FoodPlanData](
            agent="food",
            status=status,
            summary="已按每日活动区域提供餐饮建议。",
            data=data,
            sources=tuple(sources),
            warnings=("餐饮营业时间与服务安排请以商家官方信息为准。",) if missing_fields else (),
            missing_fields=tuple(missing_fields),
            request_id=request_id,
            trace_id=trace_id,
        )

    @staticmethod
    def _daily_area(item: Any) -> tuple[int, str]:
        if hasattr(item, "day"):
            return item.day, item.area
        return item["day"], item["area"]

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
    def _append_sources(sources: list[Source], raw_pois: list[dict[str, Any]]) -> None:
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
