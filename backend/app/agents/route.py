from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.models.travel import (
    AgentResult,
    AgentStatus,
    DailyArea,
    DailyItinerary,
    DailyWeather,
    DataStatus,
    PoiCandidate,
    RouteEstimate,
    RoutePlanData,
    Source,
    SourceType,
    TimedAttraction,
    TravelPlanRequest,
    WeatherPlanData,
)
from app.services.resilience import ExternalServiceUnavailable


_INDOOR_KEYWORDS = ("博物馆", "美术馆", "展馆")
_ATTRACTION_RADIUS_METERS = 50000
_SLOTS = ("上午", "下午", "傍晚")
_MISSING_WEATHER = "天气待核验，请出行前确认。"
_INDOOR_NOTE = "已优先安排室内文化场所，开放时间与预约条件待核验。"


class RouteAgent:
    """使用高德地理编码、驾车路线和景区 POI 生成逐日路线。"""

    def __init__(self, amap_client: Any) -> None:
        self.amap_client = amap_client

    async def run(
        self,
        request: TravelPlanRequest,
        weather_result: AgentResult[WeatherPlanData] | tuple[str, ...] | list[str],
        ids: dict[str, str] | str | None = None,
        trace_id: str | None = None,
        *,
        request_id: str | None = None,
    ) -> AgentResult[RoutePlanData]:
        request_id, trace_id = self._ids(ids, trace_id, request_id)
        self._validate_ids(request_id, trace_id)
        weather, constraints, weather_missing = self._weather(weather_result)
        legacy_weather = not isinstance(weather_result, AgentResult)
        sources: list[Source] = []
        origin_payload: dict[str, Any] | None = None
        destination_payload: dict[str, Any] | None = None
        outbound: dict[str, Any] | None = None
        inbound: dict[str, Any] | None = None

        try:
            origin_payload = await self.amap_client.geocode(request.origin)
            self._append_source(sources, origin_payload)
            destination_payload = await self.amap_client.geocode(request.destination)
            self._append_source(sources, destination_payload)
            outbound = await self.amap_client.driving_route(
                origin_payload["location"], destination_payload["location"]
            )
            self._append_source(sources, outbound)
            if not legacy_weather:
                inbound = await self.amap_client.driving_route(
                    destination_payload["location"], origin_payload["location"]
                )
                self._append_source(sources, inbound)
            else:
                inbound = outbound
        except (ExternalServiceUnavailable, KeyError, TypeError, ValueError, ValidationError):
            pass

        area = destination_payload.get("name", request.destination) if destination_payload else request.destination
        if legacy_weather:
            itineraries = tuple(
                DailyItinerary(day=day, weather_reminder="景区行程待生成，请以路线规划结果为准。", attractions=(), missing_fields=("attractions",))
                for day in range(1, request.days + 1)
            )
            poi_sources, missing_fields = [], ["attractions"]
        else:
            itineraries, poi_sources, missing_fields = await self._build_itineraries(
                request, weather, area, destination_payload.get("location") if destination_payload else None
            )
        for source in poi_sources:
            self._append_source(sources, source)

        round_trip = None
        if outbound is not None and inbound is not None:
            try:
                round_trip = RouteEstimate(
                    distance_meters=(outbound["distance_meters"] if legacy_weather else outbound["distance_meters"] + inbound["distance_meters"]),
                    duration_minutes=(outbound["duration_minutes"] if legacy_weather else outbound["duration_minutes"] + inbound["duration_minutes"]),
                )
            except (KeyError, TypeError, ValueError, ValidationError):
                round_trip = None

        if round_trip is None:
            missing_fields.insert(0, "route_estimate")
        missing_fields[0:0] = list(weather_missing)
        data = RoutePlanData(
            origin=request.origin,
            destination=request.destination,
            round_trip=round_trip,
            daily_areas=tuple(DailyArea(day=day, area=area) for day in range(1, request.days + 1)),
            daily_itineraries=itineraries,
            weather_adjusted=any(item.indoor_preferred for item in weather) or bool(constraints),
        )
        unique_missing = tuple(dict.fromkeys(missing_fields))
        has_attractions = any(item.attractions for item in itineraries)
        if not has_attractions and legacy_weather:
            unique_missing = tuple(field for field in unique_missing if not field.startswith("route_day_"))
            unique_missing = tuple(dict.fromkeys(("route_estimate", "attractions", *unique_missing))) if round_trip is None else ("attractions",)

        if not has_attractions:
            status = AgentStatus.degraded
            summary = "未获得真实景区 POI，已保留路线核验结果。"
        elif unique_missing:
            status = AgentStatus.partial
            summary = "已生成真实景区路线，部分交通或景点信息待核验。"
        else:
            status = AgentStatus.success
            summary = "已生成真实景区逐日路线。"
        return AgentResult[RoutePlanData](
            agent="route",
            status=status,
            summary=summary,
            data=data,
            constraints=constraints,
            sources=tuple(sources),
            warnings=("部分路线或景区信息待出行前核验。",) if unique_missing else (),
            missing_fields=unique_missing or (("attractions",) if not has_attractions else ()),
            request_id=request_id,
            trace_id=trace_id,
        )

    async def _build_itineraries(
        self, request: TravelPlanRequest, weather: tuple[DailyWeather, ...], area: str, location: str | None
    ) -> tuple[tuple[DailyItinerary, ...], list[Source], list[str]]:
        sources: list[Source] = []
        missing: list[str] = []
        seen: set[tuple[str, str | None]] = set()
        itineraries: list[DailyItinerary] = []
        for day in range(1, request.days + 1):
            daily_weather = next((item for item in weather if item.date == date.fromordinal(request.departure_date.toordinal() + day - 1)), None)
            indoor = daily_weather.indoor_preferred if daily_weather else False
            keywords = _INDOOR_KEYWORDS if indoor else ("风景名胜",)
            day_candidates: list[tuple[dict[str, Any], PoiCandidate]] = []
            day_seen: set[tuple[str, str | None]] = set()
            if not isinstance(location, str) or not location.strip():
                missing.append("attractions")
                itineraries.append(DailyItinerary(day=day, weather_reminder=daily_weather.travel_reminder if daily_weather else _MISSING_WEATHER, attractions=(), missing_fields=("attractions",)))
                continue
            for keyword in keywords:
                try:
                    raw_pois = await self.amap_client.search_nearby_poi(keyword, location, _ATTRACTION_RADIUS_METERS)
                except (ExternalServiceUnavailable, KeyError, TypeError, ValueError, ValidationError):
                    missing.append(f"route_day_{day}_attraction_query_{keyword}")
                    raw_pois = []
                for item in raw_pois if isinstance(raw_pois, list) else []:
                    if not isinstance(item, dict) or not self._matches_category(item.get("category"), keyword, indoor):
                        continue
                    candidate_location = item.get("location")
                    if candidate_location is not None and (not isinstance(candidate_location, str) or not candidate_location.strip()):
                        continue
                    try:
                        validated_poi = PoiCandidate(name=item["name"], address=item.get("address"), location=candidate_location, category=item["category"], tags=tuple(item.get("tags") or ()), source_ids=("amap:attraction",))
                    except (KeyError, TypeError, ValueError, ValidationError):
                        continue
                    key = (validated_poi.name, validated_poi.location)
                    if key in seen or key in day_seen:
                        continue
                    day_seen.add(key)
                    try:
                        self._append_source(sources, item, poi=True)
                    except (KeyError, TypeError, ValueError, ValidationError):
                        missing.append(f"route_day_{day}_attraction_source_{keyword}")
                    day_candidates.append((item, validated_poi))
            day_items: list[TimedAttraction] = []
            day_missing: list[str] = []
            assigned_keys: set[tuple[str, str | None]] = set()
            for slot_index, slot in enumerate(_SLOTS, 1):
                if slot_index > len(day_candidates):
                    day_missing.append(f"route_day_{day}_attraction_{slot_index}")
                    continue
                selected = next((candidate for candidate in day_candidates if (candidate[1].name, candidate[1].location) not in assigned_keys), None)
                item, validated_poi = selected if selected is not None else (None, None)
                if item is None:
                    day_missing.append(f"route_day_{day}_attraction_{slot_index}")
                    continue
                try:
                    poi = validated_poi
                    day_items.append(TimedAttraction(time_slot=slot, poi=poi, suggested_duration_minutes=120, activity_note=_INDOOR_NOTE if indoor else None))
                    assigned_key = (poi.name, poi.location)
                    assigned_keys.add(assigned_key)
                    seen.add(assigned_key)
                except (KeyError, TypeError, ValueError, ValidationError):
                    day_missing.append(f"route_day_{day}_attraction_{slot_index}")
            for index in range(len(day_items) - 1):
                previous, following = day_items[index], day_items[index + 1]
                travel = None
                if previous.poi.location and following.poi.location:
                    try:
                        route = await self.amap_client.driving_route(previous.poi.location, following.poi.location)
                        self._append_source(sources, route)
                        travel = RouteEstimate(distance_meters=route["distance_meters"], duration_minutes=route["duration_minutes"])
                    except (ExternalServiceUnavailable, KeyError, TypeError, ValueError, ValidationError):
                        pass
                if travel is None:
                    field = f"route_day_{day}_travel_{index + 1}"
                    day_missing.append(field)
                    missing.append(field)
                day_items[index] = previous.model_copy(update={"travel_to_next": travel})
            for field in day_missing:
                missing.append(field)
            itineraries.append(DailyItinerary(day=day, weather_reminder=daily_weather.travel_reminder if daily_weather else _MISSING_WEATHER, attractions=tuple(day_items), missing_fields=tuple(day_missing)))
        return tuple(itineraries), sources, missing

    @staticmethod
    def _weather(value: AgentResult[WeatherPlanData] | tuple[str, ...] | list[str]) -> tuple[tuple[DailyWeather, ...], tuple[str, ...], tuple[str, ...]]:
        if isinstance(value, AgentResult):
            missing = tuple(f"weather_{field}" for field in value.missing_fields)
            if value.status is not AgentStatus.success and not missing:
                missing = ("weather",)
            if isinstance(value.data, WeatherPlanData):
                return value.data.daily, value.constraints, missing
            return (), (), missing
        return (), tuple(item for item in value if isinstance(item, str) and item.strip()), ()

    @staticmethod
    def _matches_category(category: object, keyword: str, indoor: bool) -> bool:
        if not isinstance(category, str):
            return False
        for group in category.split("|"):
            parts = [part.strip() for part in group.split(";")]
            if parts and ((parts[0] == keyword) if not indoor else keyword in parts):
                return True
        return False

    @staticmethod
    def _append_source(sources: list[Source], result: dict[str, Any] | Source, poi: bool = False) -> None:
        if isinstance(result, Source):
            source = result
        else:
            source = Source(
                name="高德地图", type=SourceType.poi_api if poi else SourceType.map_api,
                data_status=DataStatus(result["data_status"]), source_updated_at=result.get("source_updated_at"),
                retrieved_at=result["retrieved_at"],
            )
        key = (
            source.name,
            source.type,
            source.data_status,
            source.source_updated_at,
            str(source.url) if source.url is not None else None,
            source.knowledge_version,
        )
        existing_keys = {
            (
                item.name,
                item.type,
                item.data_status,
                item.source_updated_at,
                str(item.url) if item.url is not None else None,
                item.knowledge_version,
            )
            for item in sources
        }
        if key not in existing_keys:
            sources.append(source)

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
            request_uuid, trace_uuid = UUID(request_id), UUID(trace_id)
            if request_uuid.version not in {1, 2, 3, 4, 5} or trace_uuid.version not in {1, 2, 3, 4, 5} or request_uuid != trace_uuid:
                raise ValueError
        except (TypeError, ValueError, AttributeError):
            raise ValueError("请求追踪标识无效") from None
