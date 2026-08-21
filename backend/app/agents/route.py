from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.models.travel import (
    AgentResult,
    AgentStatus,
    DataStatus,
    DailyArea,
    RouteEstimate,
    RoutePlanData,
    Source,
    SourceType,
    TravelPlanRequest,
)
from app.services.resilience import ExternalServiceUnavailable


class RouteAgent:
    """使用高德地理编码和驾车估算生成路线结果。"""

    def __init__(self, amap_client: Any) -> None:
        self.amap_client = amap_client

    async def run(
        self,
        request: TravelPlanRequest,
        weather_constraints: tuple[str, ...] | list[str],
        ids: dict[str, str] | str | None = None,
        trace_id: str | None = None,
        *,
        request_id: str | None = None,
    ) -> AgentResult[RoutePlanData]:
        request_id, trace_id = self._ids(ids, trace_id, request_id)
        self._validate_ids(request_id, trace_id)
        constraints = tuple(weather_constraints)
        sources: list[Source] = []
        try:
            origin = await self.amap_client.geocode(request.origin)
            self._append_source(sources, origin)
            destination = await self.amap_client.geocode(request.destination)
            self._append_source(sources, destination)
            route = await self.amap_client.driving_route(
                origin["location"], destination["location"]
            )
            self._append_source(sources, route)
            data = RoutePlanData(
                origin=request.origin,
                destination=request.destination,
                round_trip=RouteEstimate(
                    distance_meters=route["distance_meters"],
                    duration_minutes=route["duration_minutes"],
                ),
                daily_areas=tuple(
                    DailyArea(day=day, area=destination["name"])
                    for day in range(1, request.days + 1)
                ),
                weather_adjusted=bool(constraints),
            )
            return AgentResult[RoutePlanData](
                agent="route",
                status=AgentStatus.success,
                summary="已生成往返与每日活动区域建议。",
                data=data,
                constraints=constraints,
                sources=tuple(sources),
                warnings=(),
                request_id=request_id,
                trace_id=trace_id,
            )
        except (ExternalServiceUnavailable, KeyError, TypeError, ValueError, ValidationError):
            data = RoutePlanData(
                origin=request.origin,
                destination=request.destination,
                round_trip=None,
                daily_areas=tuple(
                    DailyArea(day=day, area=request.destination)
                    for day in range(1, request.days + 1)
                ),
                weather_adjusted=bool(constraints),
            )
            return AgentResult[RoutePlanData](
                agent="route",
                status=AgentStatus.degraded,
                summary="路线服务暂不可用，已改为区域化建议。",
                data=data,
                constraints=constraints,
                sources=tuple(sources),
                warnings=("未获得精确路线与通行时间，请使用地图应用再次核验。",),
                missing_fields=("route_estimate",),
                request_id=request_id,
                trace_id=trace_id,
            )

    @staticmethod
    def _ids(ids: dict[str, str] | str | None, trace_id: str | None, request_id: str | None = None) -> tuple[str, str]:
        if request_id is not None:
            return request_id, trace_id or request_id
        if isinstance(ids, dict):
            if "request_id" not in ids or "trace_id" not in ids:
                raise ValueError("请求追踪标识无效")
            return ids["request_id"], ids["trace_id"]
        if not isinstance(ids, str):
            raise ValueError("请求追踪标识无效")
        return ids, trace_id or ids

    @staticmethod
    def _validate_ids(request_id: str, trace_id: str) -> None:
        try:
            request_uuid = UUID(request_id)
            trace_uuid = UUID(trace_id)
            if request_uuid.version not in {1, 2, 3, 4, 5} or trace_uuid.version not in {1, 2, 3, 4, 5} or request_uuid != trace_uuid:
                raise ValueError
        except (TypeError, ValueError, AttributeError):
            raise ValueError("请求追踪标识无效") from None

    @staticmethod
    def _append_source(sources: list[Source], result: dict[str, Any]) -> None:
        source = Source(
            name="高德地图",
            type=SourceType.map_api,
            data_status=DataStatus(result["data_status"]),
            source_updated_at=result.get("source_updated_at"),
            retrieved_at=result["retrieved_at"],
        )
        if source not in sources:
            sources.append(source)
