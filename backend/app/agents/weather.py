from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.models.travel import (
    AgentResult,
    AgentStatus,
    DailyWeather,
    DataStatus,
    Source,
    SourceType,
    TravelPlanRequest,
    WeatherPlanData,
    WeatherRiskLevel,
)
from app.services.resilience import ExternalServiceUnavailable


_RISK_WORDS = ("暴雨", "台风", "强对流", "高温")


class WeatherAgent:
    """使用高德地点与和风逐日预报生成天气结果。"""

    def __init__(self, weather_client: Any, amap_client: Any) -> None:
        if hasattr(weather_client, "geocode") and hasattr(amap_client, "daily_forecast"):
            weather_client, amap_client = amap_client, weather_client
        self.weather_client = weather_client
        self.amap_client = amap_client

    async def run(
        self, request: TravelPlanRequest, request_id: str, trace_id: str
    ) -> AgentResult[WeatherPlanData]:
        self._validate_ids(request_id, trace_id)
        sources: list[Source] = []
        try:
            location = await self.amap_client.geocode(request.destination)
            sources.append(self._source(location, "高德地图", SourceType.map_api))
            location_id = location["adcode"]
            forecast = await self.weather_client.daily_forecast(
                location_id, request.departure_date, request.days
            )
            raw_daily = forecast.get("daily", ())
            daily = tuple(self._daily_item(item) for item in raw_daily)
            sources.append(self._source(forecast, "和风天气", SourceType.weather_api))
            data = WeatherPlanData(
                destination=request.destination,
                daily=daily,
                constraints=self._constraints(daily),
            )
            if not daily:
                return self._degraded(
                    request_id, trace_id, data, ("daily_forecast",), tuple(sources)
                )
            missing_fields = self._missing_fields(request.days, len(daily))
            status = AgentStatus.partial if missing_fields else AgentStatus.success
            return AgentResult[WeatherPlanData](
                agent="weather",
                status=status,
                summary="已获取目的地天气与活动建议。",
                data=data,
                constraints=data.constraints,
                sources=tuple(sources),
                warnings=self._warnings(daily),
                missing_fields=missing_fields,
                request_id=request_id,
                trace_id=trace_id,
            )
        except (ExternalServiceUnavailable, KeyError, TypeError, ValueError, ValidationError):
            data = WeatherPlanData(destination=request.destination, daily=())
            return self._degraded(
                request_id, trace_id, data, ("daily_forecast",), tuple(sources)
            )

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
    def _daily_item(item: dict[str, Any]) -> DailyWeather:
        condition = item["condition"]
        risk_level = (
            WeatherRiskLevel.high
            if any(word in condition for word in _RISK_WORDS)
            else WeatherRiskLevel.low
        )
        return DailyWeather(
            date=item["date"],
            condition=condition,
            temp_min=item.get("temp_min"),
            temp_max=item.get("temp_max"),
            risk_level=risk_level,
        )

    @staticmethod
    def _missing_fields(request_days: int, actual_days: int) -> tuple[str, ...]:
        if actual_days >= request_days:
            return ()
        end = "N" if request_days > 3 else str(request_days)
        return (f"daily_forecast_days_{actual_days + 1}_to_{end}",)

    @staticmethod
    def _constraints(daily: tuple[DailyWeather, ...]) -> tuple[str, ...]:
        return tuple(
            f"第 {index} 天避免长时间户外活动或高温时段优先室内。"
            for index, item in enumerate(daily, 1)
            if item.risk_level is WeatherRiskLevel.high
        )

    @staticmethod
    def _warnings(daily: tuple[DailyWeather, ...]) -> tuple[str, ...]:
        return tuple(
            f"第 {index} 天预报为{item.condition}，请关注官方预警。"
            for index, item in enumerate(daily, 1)
            if item.risk_level is WeatherRiskLevel.high
        )

    @staticmethod
    def _source(result: dict[str, Any], name: str, source_type: SourceType) -> Source:
        status = DataStatus(result["data_status"])
        return Source(
            name=name,
            type=source_type,
            data_status=status,
            source_updated_at=result.get("source_updated_at"),
            retrieved_at=result["retrieved_at"],
        )

    @staticmethod
    def _degraded(
        request_id: str,
        trace_id: str,
        data: WeatherPlanData,
        missing_fields: tuple[str, ...],
        sources: tuple[Source, ...],
    ) -> AgentResult[WeatherPlanData]:
        return AgentResult[WeatherPlanData](
            agent="weather",
            status=AgentStatus.degraded,
            summary="天气服务暂不可用。",
            data=data,
            sources=sources,
            missing_fields=missing_fields,
            warnings=("天气数据暂不可用，请出行前再次核验。",),
            request_id=request_id,
            trace_id=trace_id,
        )
