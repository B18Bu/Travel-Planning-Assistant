from __future__ import annotations

import re
from uuid import UUID

from app.models.travel import (
    AgentResult,
    AgentStatus,
    TravelPlanData,
    TravelPlanDocument,
)


class SummaryAgent:
    """将四个专业结果聚合为合同校验过的确定性行程文档。"""

    def run(
        self,
        weather: AgentResult,
        route: AgentResult,
        lodging: AgentResult,
        food: AgentResult,
        request_id: str,
        trace_id: str,
    ) -> TravelPlanDocument:
        self._validate_ids(request_id, trace_id)
        itinerary = TravelPlanData(
            weather=weather,
            route=route,
            lodging=lodging,
            food=food,
        )
        results = (weather, route, lodging, food)
        sources = self._sources(results)
        warnings = tuple(warning for result in results for warning in result.warnings)
        degraded_agents = tuple(
            result.agent for result in results if result.status is AgentStatus.degraded
        )
        if any(result.status is AgentStatus.failed for result in results):
            status = AgentStatus.failed
        elif any(
            result.status in {AgentStatus.degraded, AgentStatus.partial}
            for result in results
        ):
            status = AgentStatus.degraded
        else:
            status = AgentStatus.success
        return TravelPlanDocument(
            request_id=request_id,
            trace_id=trace_id,
            status=status,
            itinerary=itinerary,
            markdown=self._markdown(itinerary, warnings, degraded_agents),
            sources=sources,
            warnings=warnings,
            degraded_agents=degraded_agents,
        )

    @staticmethod
    def _sources(results: tuple[AgentResult, ...]) -> tuple:
        collected = []
        seen: set[tuple[object, ...]] = set()
        for result in results:
            for source in result.sources:
                key = (
                    source.name,
                    source.type,
                    source.data_status,
                    source.source_updated_at,
                    str(source.url) if source.url is not None else None,
                    source.knowledge_version,
                )
                if key not in seen:
                    seen.add(key)
                    collected.append(source)
        return tuple(collected)

    @staticmethod
    def _safe(value: object) -> str:
        text = str(value).replace("\r", " ").replace("\n", " ")
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return re.sub(r"([\\`*_{}\[\]()#+.!|~-])", r"\\\1", text)

    @classmethod
    def _markdown(cls, itinerary: TravelPlanData, warnings: tuple[str, ...], degraded_agents: tuple[str, ...]) -> str:
        weather_data = itinerary.weather.data
        route_data = itinerary.route.data
        lodging_data = itinerary.lodging.data
        food_data = itinerary.food.data
        lines = [
            "# 旅行计划",
            "",
            "## 行程概览",
            f"- 目的地：{cls._safe(weather_data.destination if weather_data else '待核验')}",
            f"- 行程天数：{len(route_data.daily_areas) if route_data else 0} 天",
            "",
            "## 天气与出游风险",
        ]
        if weather_data and weather_data.daily:
            lines.extend(
                f"- {item.date.isoformat()}：{cls._safe(item.condition)}，风险等级 {cls._safe(item.risk_level.value)}。"
                for item in weather_data.daily
            )
        else:
            lines.append("- 暂无逐日天气数据，请出行前核验。")
        lines.extend(["", "## 每日路线"])
        daily_itineraries = getattr(route_data, "daily_itineraries", None) if route_data else None
        if daily_itineraries:
            for daily in daily_itineraries:
                lines.append(f"### 第 {daily.day} 天 · {cls._safe(route_data.destination)}")
                lines.append("### 今日出游提醒")
                lines.append(f"- {cls._safe(daily.weather_reminder)}")
                if daily.attractions:
                    for index, attraction in enumerate(daily.attractions):
                        poi = attraction.poi
                        lines.append(f"### {cls._safe(attraction.time_slot)} · {cls._safe(poi.name)}")
                        lines.append(f"- 建议游玩约 {attraction.suggested_duration_minutes} 分钟。")
                        lines.append(f"- 地址：{cls._safe(poi.address or '地址待核验')}。")
                        if attraction.activity_note:
                            lines.append(f"- {cls._safe(attraction.activity_note)}")
                        if attraction.travel_to_next:
                            lines.append(f"- 驾车约 {attraction.travel_to_next.duration_minutes} 分钟、约 {attraction.travel_to_next.distance_meters} 米。")
                        elif index < len(daily.attractions) - 1:
                            lines.append("- 下一段交通信息待核验，请以官方或地图信息为准。")
                else:
                    lines.append("- 暂无景点安排，请核验路线。")
        elif route_data:
            lines.extend(f"- 第 {item.day} 天：{cls._safe(item.area)}。" for item in route_data.daily_areas)
        else:
            lines.append("- 暂无路线数据，请核验活动区域。")
        lines.extend(["", "## 住宿建议"])
        if lodging_data:
            lines.append(f"- 推荐区域：{cls._safe(lodging_data.recommended_area)}。")
            if lodging_data.candidates:
                lines.extend(f"- 候选：{cls._safe(candidate.poi.name)}（{cls._safe(candidate.poi.address or '地址待核验')}）。" for candidate in lodging_data.candidates)
            else:
                lines.append("- 暂无住宿候选，请按区域筛选并核验。")
        else:
            lines.append("- 暂无住宿数据，请核验。")
        lines.extend(["", "## 餐饮建议"])
        if food_data:
            for daily in food_data.daily_food:
                if daily.meal_period:
                    nearby = cls._safe(daily.nearby_attraction_name or daily.area)
                    lines.append(f"### 第 {daily.day} 天 · {cls._safe(daily.meal_period)} · {nearby}附近")
                    if daily.candidates:
                        for candidate in daily.candidates:
                            lines.append(f"- {cls._safe(candidate.poi.name)}：{cls._safe(candidate.poi.address or '地址待核验')}。")
                            if candidate.specialties:
                                lines.append(f"- 推荐菜品：{cls._safe('、'.join(candidate.specialties))}。")
                    elif daily.filter_suggestions:
                        lines.extend(f"- {cls._safe(suggestion)}" for suggestion in daily.filter_suggestions)
                    else:
                        lines.append("- 暂无候选。")
                    lines.append("- 营业时间、菜品与服务安排请以商家官方信息为准。")
                else:
                    names = "、".join(candidate.poi.name for candidate in daily.candidates)
                    lines.append(f"- 第 {daily.day} 天 {cls._safe(daily.area)}：{cls._safe(names or '暂无候选，请按区域筛选')}。")
        else:
            lines.append("- 暂无餐饮数据，请核验。")
        lines.extend(["", "## 待核验事项"])
        if warnings:
            lines.extend(f"- {cls._safe(warning)}" for warning in warnings)
        else:
            lines.append("- 暂无额外核验事项。")
        missing_fields = tuple(
            field
            for result in (itinerary.weather, itinerary.route, itinerary.lodging, itinerary.food)
            for field in result.missing_fields
        )
        if missing_fields:
            lines.extend(f"- 待补字段：{cls._safe(field)}。" for field in missing_fields)
        lines.extend(["", "## 来源与更新时间"])
        if itinerary.weather.sources or itinerary.route.sources or itinerary.lodging.sources or itinerary.food.sources:
            for source in SummaryAgent._sources((itinerary.weather, itinerary.route, itinerary.lodging, itinerary.food)):
                updated = source.source_updated_at.isoformat() if source.source_updated_at else "未提供"
                lines.append(f"- {cls._safe(source.name)}（{cls._safe(source.type.value)}）：来源更新时间 {cls._safe(updated)}，获取时间 {cls._safe(source.retrieved_at.isoformat())}。")
        else:
            lines.append("- 暂无来源记录。")
        lines.extend(["", "## 降级说明"])
        failed_results = tuple(
            result for result in (itinerary.weather, itinerary.route, itinerary.lodging, itinerary.food)
            if result.status is AgentStatus.failed
        )
        if failed_results:
            for result in failed_results:
                error_text = ""
                if result.error is not None:
                    error_text = f"错误码 {cls._safe(result.error.code)}：{cls._safe(result.error.message)}；"
                missing = "、".join(cls._safe(field) for field in result.missing_fields) or "无"
                lines.append(f"- {cls._safe(result.agent.value)} Agent 失败；{error_text}缺失字段：{missing}。")
        elif degraded_agents:
            lines.append(f"- 以下专业结果已降级：{cls._safe('、'.join(agent.value if hasattr(agent, 'value') else agent for agent in degraded_agents))}。")
        elif any(result.status is AgentStatus.partial for result in (itinerary.weather, itinerary.route, itinerary.lodging, itinerary.food)):
            lines.append("- 部分专业结果不完整，请根据待核验事项补充确认。")
        else:
            lines.append("- 各专业结果均已完成。")
        return "\n".join(lines)

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
