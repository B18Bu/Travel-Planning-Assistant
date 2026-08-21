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
        if not daily_areas:
            fallback = DailyFoodPlan(
                day=1,
                area=request.destination,
                meal_period=None,
                candidates=(),
                filter_suggestions=("请先补充每日活动区域，再按区域筛选餐饮。",),
            )
            return AgentResult[FoodPlanData](
                agent="food",
                status=AgentStatus.degraded,
                summary="餐饮活动区域暂不可用。",
                data=FoodPlanData(daily_food=(fallback,)),
                warnings=("未获得每日活动区域，请先核验路线区域。",),
                missing_fields=("food_daily_areas",),
                request_id=request_id,
                trace_id=trace_id,
            )
        parsed_areas: list[tuple[int, str]] = []
        duplicate_fields: list[str] = []
        invalid_fields: list[str] = []
        for index, daily_area in enumerate(daily_areas, 1):
            try:
                day, area = self._daily_area(daily_area, request.days)
            except (AttributeError, KeyError, TypeError, ValueError, ValidationError):
                invalid_fields.append(f"food_day_{index}_area")
                continue
            if day in {item[0] for item in parsed_areas}:
                duplicate_fields.append(f"food_day_{day}_duplicate")
                continue
            parsed_areas.append((day, area))
        parsed_areas.sort(key=lambda item: item[0])
        out_of_range = set()
        for daily_area in daily_areas:
            try:
                raw_day = daily_area.day if hasattr(daily_area, "day") else daily_area["day"]
                if isinstance(raw_day, int) and not isinstance(raw_day, bool) and not 1 <= raw_day <= request.days:
                    out_of_range.add(raw_day)
            except (AttributeError, KeyError, TypeError):
                pass
        invalid_fields.extend(f"food_day_{day}_out_of_range" for day in sorted(out_of_range))
        missing_fields.extend(duplicate_fields)
        missing_fields.extend(invalid_fields)
        for index, (day, area) in enumerate(parsed_areas, 1):
            try:
                raw_pois = await self.amap_client.search_poi("餐饮服务", area)
                if not isinstance(raw_pois, list):
                    raise ValueError("POI 响应格式无效")
                limited_pois = raw_pois[:10]
                candidates = tuple(
                    FoodCandidate(poi=self._poi(item, "amap:food", "餐饮服务"))
                    for item in limited_pois
                )
                self._append_sources(sources, limited_pois)
            except (ExternalServiceUnavailable, KeyError, TypeError, ValueError, ValidationError):
                candidates = ()
            suggestions = () if candidates else ("请按营业时段、菜系与活动区域筛选，并以商家官方信息为准。",)
            if not candidates:
                missing_fields.append(f"food_day_{day}_candidates")
            try:
                daily_plans.append(
                    DailyFoodPlan(
                        day=day,
                        area=area,
                        meal_period=None,
                        candidates=candidates,
                        filter_suggestions=suggestions,
                    )
                )
            except (TypeError, ValueError, ValidationError):
                missing_fields.append(f"food_day_{day}_area")
        expected_days = request.days
        existing_days = {item.day for item in daily_plans}
        missing_fields.extend(
            f"food_day_{day}_area"
            for day in range(1, expected_days + 1)
            if day not in existing_days
        )
        if not daily_plans:
            fallback_area = "未知区域" if daily_areas else request.destination
            fallback = DailyFoodPlan(
                day=1,
                area=fallback_area,
                meal_period=None,
                candidates=(),
                filter_suggestions=("请先补充有效每日活动区域，再按区域筛选餐饮。",),
            )
            daily_plans.append(fallback)
            if "food_daily_areas" not in missing_fields:
                missing_fields.append("food_daily_areas")
        data = FoodPlanData(daily_food=tuple(daily_plans))
        has_candidates = any(item.candidates for item in daily_plans)
        if not daily_plans or not has_candidates:
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
    def _daily_area(item: Any, max_days: int) -> tuple[int, str]:
        try:
            day = item.day if hasattr(item, "day") else item["day"]
            area = item.area if hasattr(item, "area") else item["area"]
        except (AttributeError, KeyError, TypeError) as exc:
            raise ValueError("每日区域字段缺失") from exc
        if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= max_days:
            raise ValueError("每日区域 day 无效")
        if not isinstance(area, str) or not area.strip():
            raise ValueError("每日区域 area 无效")
        return day, area

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
        category = category.strip()
        if category != expected_category:
            raise ValueError("POI 分类不匹配")
        return PoiCandidate(
            name=item["name"],
            address=item.get("address"),
            location=item.get("location"),
            category=expected_category,
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
