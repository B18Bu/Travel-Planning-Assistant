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
    """按每日景区行程获取午餐和晚餐餐饮 POI。"""

    def __init__(self, amap_client: Any) -> None:
        self.amap_client = amap_client

    async def run(
        self,
        request: TravelPlanRequest,
        daily_itineraries: tuple[Any, ...] | list[Any],
        request_id: str,
        trace_id: str,
    ) -> AgentResult[FoodPlanData]:
        self._validate_ids(request_id, trace_id)
        sources: list[Source] = []
        missing_fields: list[str] = []
        daily_plans: list[DailyFoodPlan] = []

        if daily_itineraries is not None and not isinstance(daily_itineraries, (tuple, list)):
            return AgentResult[FoodPlanData](
                agent="food",
                status=AgentStatus.degraded,
                summary="每日景区行程格式无效，餐饮建议受控降级。",
                data=FoodPlanData(daily_food=tuple(
                    DailyFoodPlan(day=day, area=request.destination, meal_period=meal_period,
                                  candidates=(), filter_suggestions=("请核验每日景区行程格式，并以商家官方信息为准。",))
                    for day in range(1, request.days + 1)
                    for meal_period in ("午餐", "晚餐")
                )),
                warnings=("每日景区行程格式无效，请先核验路线信息。",),
                missing_fields=("food_daily_itineraries",),
                request_id=request_id,
                trace_id=trace_id,
            )

        if not daily_itineraries:
            fallback_plans = tuple(
                DailyFoodPlan(
                    day=day,
                    area=request.destination,
                    meal_period=meal_period,
                    candidates=(),
                    filter_suggestions=("请先补充每日景区行程，并以商家官方信息为准。",),
                )
                for day in range(1, request.days + 1)
                for meal_period in ("午餐", "晚餐")
            )
            return AgentResult[FoodPlanData](
                agent="food",
                status=AgentStatus.degraded,
                summary="每日景区行程暂不可用，餐饮建议受控降级。",
                data=FoodPlanData(daily_food=fallback_plans),
                warnings=("未获得每日景区行程，请先核验路线信息。",),
                missing_fields=tuple(
                    f"food_day_{day}_{slot}_itinerary"
                    for day in range(1, request.days + 1)
                    for slot in ("lunch", "dinner")
                ),
                request_id=request_id,
                trace_id=trace_id,
            )

        parsed: list[tuple[int, Any]] = []
        for index, itinerary in enumerate(daily_itineraries, 1):
            try:
                day = self._value(itinerary, "day")
                if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= request.days:
                    raise ValueError
            except (AttributeError, KeyError, TypeError, ValueError):
                missing_fields.append(f"food_day_{index}_itinerary")
                continue
            if any(existing_day == day for existing_day, _ in parsed):
                missing_fields.append(f"food_day_{day}_duplicate")
                continue
            parsed.append((day, itinerary))
        parsed.sort(key=lambda item: item[0])
        present_days = {day for day, _ in parsed}
        missing_days = set(range(1, request.days + 1)) - present_days
        missing_fields.extend(
            f"food_day_{day}_itinerary"
            for day in sorted(missing_days)
        )

        for day in sorted(missing_days):
            for meal_period, slot_name in (("午餐", "lunch"), ("晚餐", "dinner")):
                daily_plans.append(DailyFoodPlan(
                    day=day,
                    area=request.destination,
                    meal_period=meal_period,
                    candidates=(),
                    filter_suggestions=("请补充该日路线，并以商家官方信息为准。",),
                ))
                missing_fields.append(f"food_day_{day}_{slot_name}_itinerary")

        for day, itinerary in parsed:
            attractions = self._value(itinerary, "attractions", ())
            if not isinstance(attractions, (tuple, list)):
                attractions = ()
            by_slot = {}
            for attraction in attractions:
                try:
                    slot = self._value(attraction, "time_slot")
                    if slot in {"上午", "下午", "傍晚"} and slot not in by_slot:
                        by_slot[slot] = attraction
                except (AttributeError, KeyError, TypeError):
                    continue
            lunch_attraction = by_slot.get("上午")
            dinner_attraction = by_slot.get("傍晚") or by_slot.get("下午")
            for meal_period, slot_name, attraction in (
                ("午餐", "lunch", lunch_attraction),
                ("晚餐", "dinner", dinner_attraction),
            ):
                plan, fields = await self._plan_meal(
                    request, day, meal_period, slot_name, attraction, sources
                )
                daily_plans.append(plan)
                missing_fields.extend(fields)

        daily_plans.sort(key=lambda plan: (plan.day, 0 if plan.meal_period == "午餐" else 1))
        if not daily_plans:
            daily_plans.append(
                DailyFoodPlan(
                    day=1,
                    area=request.destination,
                    meal_period="午餐",
                    candidates=(),
                    filter_suggestions=("请先补充有效每日景区行程，并以商家官方信息为准。",),
                )
            )
        data = FoodPlanData(daily_food=tuple(daily_plans))
        has_candidates = any(plan.candidates for plan in daily_plans)
        status = (
            AgentStatus.degraded
            if not has_candidates
            else AgentStatus.partial
            if missing_fields
            else AgentStatus.success
        )
        return AgentResult(
            agent="food",
            status=status,
            summary="已按景区坐标提供午餐和晚餐建议。",
            data=data,
            sources=tuple(sources),
            warnings=("餐饮营业时间与服务安排请以商家官方信息为准。",) if missing_fields else (),
            missing_fields=tuple(missing_fields),
            request_id=request_id,
            trace_id=trace_id,
        )

    async def _plan_meal(
        self,
        request: TravelPlanRequest,
        day: int,
        meal_period: str,
        slot_name: str,
        attraction: Any,
        sources: list[Source],
    ) -> tuple[DailyFoodPlan, list[str]]:
        fields: list[str] = []
        poi = None
        if attraction is not None:
            try:
                poi = self._value(attraction, "poi")
            except (AttributeError, KeyError, TypeError):
                poi = None
        name = None
        address = request.destination
        location = None
        if poi is not None:
            try:
                name = self._value(poi, "name")
                address_value = self._value(poi, "address", None)
                if isinstance(address_value, str) and address_value.strip():
                    address = address_value
                location_value = self._value(poi, "location", None)
                if isinstance(location_value, str) and location_value.strip():
                    location = location_value
            except (AttributeError, KeyError, TypeError):
                pass
        if attraction is None or not isinstance(name, str) or not name.strip():
            fields.append(f"food_day_{day}_{slot_name}_attraction")
        if location is None:
            fields.append(f"food_day_{day}_{slot_name}_location")

        candidate = None
        if location is not None:
            try:
                raw_pois = await self.amap_client.search_nearby_poi("餐饮服务", location, 2000)
                if not isinstance(raw_pois, list):
                    raise ValueError("POI 响应格式无效")
                for item in raw_pois:
                    if not isinstance(item, dict) or not self._matches_category(item.get("category"), "餐饮服务"):
                        continue
                    raw_name = item.get("name")
                    poi_item = item
                    if isinstance(raw_name, str) and len(raw_name) > 100:
                        poi_item = dict(item)
                        poi_item["name"] = raw_name[:100]
                    try:
                        candidate = FoodCandidate(poi=self._poi(poi_item, "amap:food", "餐饮服务"))
                    except (KeyError, TypeError, ValueError, ValidationError):
                        continue
                    if isinstance(raw_name, str) and len(raw_name) > 100:
                        fields.append(f"food_day_{day}_{slot_name}_candidate_name")
                    self._append_sources(sources, [item])
                    break
            except (ExternalServiceUnavailable, KeyError, TypeError, ValueError, ValidationError):
                candidate = None
        if candidate is None:
            fields.append(f"food_day_{day}_{slot_name}_candidates")
        plan_area = address if isinstance(address, str) and len(address) <= 100 else request.destination
        if plan_area != address:
            fields.append(f"food_day_{day}_{slot_name}_area")
        plan_name = name if isinstance(name, str) and name.strip() else None
        if plan_name is not None and len(plan_name) > 100:
            plan_name = plan_name[:100]
            fields.append(f"food_day_{day}_{slot_name}_attraction_name")
        plan = DailyFoodPlan(
            day=day,
            area=plan_area,
            meal_period=meal_period,
            nearby_attraction_name=plan_name,
            candidates=(candidate,) if candidate else (),
            filter_suggestions=()
            if candidate
            else ("附近餐饮候选需以商家官方信息核验，请勿以不安全区域文本搜索替代。",),
        )
        return plan, fields

    @staticmethod
    def _value(item: Any, key: str, default: Any = ...):
        if hasattr(item, key):
            return getattr(item, key)
        if isinstance(item, dict):
            if key in item:
                return item[key]
            if default is not ...:
                return default
        if default is not ...:
            return default
        raise KeyError(key)

    @staticmethod
    def _poi(item: dict[str, Any], source_id: str, expected_category: str) -> PoiCandidate:
        tags = item.get("tags", ())
        if tags is None:
            tags = ()
        if not isinstance(tags, (list, tuple)):
            raise TypeError("POI 标签格式无效")
        category = item.get("category")
        if not FoodAgent._matches_category(category, expected_category):
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
    def _matches_category(category: object, expected_category: str) -> bool:
        if not isinstance(category, str):
            return False
        return any(
            group.strip().split(";", 1)[0].strip() == expected_category
            for group in category.split("|")
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
                    existing.name,
                    existing.type,
                    existing.data_status,
                    existing.source_updated_at,
                    str(existing.url) if existing.url is not None else None,
                    existing.knowledge_version,
                )
                == key
                for existing in sources
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
