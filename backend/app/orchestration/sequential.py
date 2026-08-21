from __future__ import annotations

from typing import Any

from app.models.travel import DailyArea


class SequentialTravelOrchestrator:
    """按天气、路线、住宿、餐饮顺序执行旅行规划。"""

    def __init__(self, weather: Any, route: Any, lodging: Any, food: Any, summary: Any) -> None:
        self.weather = weather
        self.route = route
        self.lodging = lodging
        self.food = food
        self.summary = summary

    async def run(self, request: Any, request_id: str, trace_id: str) -> Any:
        weather = await self.weather.run(request, request_id, trace_id)
        constraints = getattr(weather, "constraints", ())
        if constraints is None:
            constraints = ()
        route = await self.route.run(request, constraints, request_id, trace_id)
        route_data = getattr(route, "data", None)
        daily_areas = getattr(route_data, "daily_areas", None)
        if not daily_areas:
            daily_areas = tuple(
                DailyArea(day=day, area=request.destination)
                for day in range(1, request.days + 1)
            )
        lodging = await self.lodging.run(request, daily_areas, request_id, trace_id)
        food = await self.food.run(request, daily_areas, request_id, trace_id)
        return self.summary.run(weather, route, lodging, food, request_id, trace_id)
