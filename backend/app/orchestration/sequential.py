from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.models.travel import AgentResult, DailyArea, DailyItinerary, ErrorDetail, RoutePlanData


class SequentialTravelOrchestrator:
    """按天气、路线、住宿、餐饮顺序执行旅行规划。"""

    def __init__(self, weather: Any, route: Any, lodging: Any, food: Any, summary: Any) -> None:
        self.weather = weather
        self.route = route
        self.lodging = lodging
        self.food = food
        self.summary = summary

    async def run(self, request: Any, request_id: str, trace_id: str) -> Any:
        weather = await self._safe_agent_call(
            "weather", lambda: self.weather.run(request, request_id, trace_id), request_id, trace_id
        )
        route = await self._safe_agent_call(
            "route",
            lambda: self.route.run(request, weather, request_id, trace_id),
            request_id,
            trace_id,
        )
        route_data_for_downstream = getattr(route, "data", None)
        if route_data_for_downstream is None:
            route_data_for_downstream = RoutePlanData(
                origin=request.origin,
                destination=request.destination,
                daily_areas=tuple(
                    DailyArea(day=day, area=request.destination)
                    for day in range(1, request.days + 1)
                ),
                daily_itineraries=tuple(
                    DailyItinerary(
                        day=day,
                        weather_reminder="路线待核验。",
                        attractions=(),
                        missing_fields=("attractions",),
                    )
                    for day in range(1, request.days + 1)
                ),
                weather_adjusted=False,
            )
        daily_areas = route_data_for_downstream.daily_areas
        daily_itineraries = route_data_for_downstream.daily_itineraries
        lodging = await self._safe_agent_call(
            "lodging",
            lambda: self.lodging.run(request, daily_areas, request_id, trace_id),
            request_id,
            trace_id,
        )
        food = await self._safe_agent_call(
            "food",
            lambda: self.food.run(request, daily_itineraries, request_id, trace_id),
            request_id,
            trace_id,
        )
        return self.summary.run(weather, route, lodging, food, request_id, trace_id)

    @staticmethod
    async def _safe_agent_call(
        agent_name: str,
        runner: Callable[[], Awaitable[Any]],
        request_id: str,
        trace_id: str,
    ) -> Any:
        try:
            return await runner()
        except Exception:
            return AgentResult(
                agent=agent_name,
                status="failed",
                summary="专业 Agent 执行失败，已继续生成其余规划。",
                missing_fields=(f"{agent_name}_result",),
                error=ErrorDetail(
                    code="agent_execution_failed",
                    message="专业 Agent 执行失败，请稍后重试。",
                    retryable=True,
                ),
                request_id=request_id,
                trace_id=trace_id,
            )
