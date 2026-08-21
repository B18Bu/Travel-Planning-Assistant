from __future__ import annotations

from typing import Any

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

    def __init__(self, first_client: Any, second_client: Any) -> None:
        if hasattr(first_client, "daily_forecast") and hasattr(second_client, "geocode"):
            self.weather_client = first_client
            self.amap_client = second_client
        else:
            self.amap_client = first_client
            self.weather_client = second_client

    async def run(
        self, request: TravelPlanRequest, request_id: str, trace_id: str
    ) -> AgentResult[WeatherPlanData]:
        try:
            location = await self.amap_client.geocode(request.destination)
            location_id = location["adcode"]
            forecast = await self.weather_client.daily_forecast(
                location_id, request.departure_date, request.days
            )
            raw_daily = forecast.get("daily", ())
            daily = tuple(self._daily_item(item) for item in raw_daily)
            source = self._source(forecast)
            data = WeatherPlanData(
                destination=request.destination,
                daily=daily,
                constraints=self._constraints(daily),
            )
            if not daily:
                return self._degraded(
                    request_id,
                    trace_id,
                    data,
                    ("daily_forecast",),
                    (source,),
                )
            missing_fields = ("daily_forecast_days_4_to_N",) if request.days > 3 else ()
            status = AgentStatus.partial if missing_fields else AgentStatus.success
            return AgentResult[WeatherPlanData](
                agent="weather",
                status=status,
                summary="已获取目的地天气与活动建议。",
                data=data,
                constraints=data.constraints,
                sources=(source,),
                warnings=self._warnings(daily),
                missing_fields=missing_fields,
                request_id=request_id,
                trace_id=trace_id,
            )
        except (ExternalServiceUnavailable, KeyError, TypeError, ValueError):
            data = WeatherPlanData(destination=request.destination, daily=())
            return self._degraded(
                request_id,
                trace_id,
                data,
                ("daily_forecast",),
                (),
            )

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
    def _source(forecast: dict[str, Any]) -> Source:
        status = DataStatus(forecast["data_status"])
        return Source(
            name="和风天气",
            type=SourceType.weather_api,
            data_status=status,
            source_updated_at=forecast.get("source_updated_at"),
            retrieved_at=forecast["retrieved_at"],
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
            error=None,
            request_id=request_id,
            trace_id=trace_id,
        )
