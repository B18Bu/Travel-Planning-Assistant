from datetime import date, datetime, timezone
import re
from uuid import uuid4

import pytest

from app.agents.summary import SummaryAgent
from app.models.travel import (
    AgentResult,
    AgentStatus,
    DailyArea,
    DailyItinerary,
    DailyFoodPlan,
    DailyWeather,
    FoodCandidate,
    PoiCandidate,
    RouteEstimate,
    TimedAttraction,
    DataStatus,
    FoodPlanData,
    LodgingPlanData,
    RoutePlanData,
    Source,
    SourceType,
    TravelPlanRequest,
    WeatherPlanData,
)

REQUEST_ID = str(uuid4())
STAMP = datetime(2026, 8, 21, tzinfo=timezone.utc)


def source(name, source_type, status="realtime", retrieved_at=STAMP, updated=None):
    return Source(name=name, type=source_type, data_status=status, retrieved_at=retrieved_at, source_updated_at=updated)


def result(agent, status, data, sources=(), warnings=(), missing_fields=()):
    return AgentResult(
        agent=agent,
        status=status,
        summary=f"{agent} result",
        data=data,
        sources=sources,
        warnings=warnings,
        missing_fields=missing_fields,
        request_id=REQUEST_ID,
        trace_id=REQUEST_ID,
    )


def results(statuses=(AgentStatus.success,) * 4):
    weather = result("weather", statuses[0], WeatherPlanData(destination="杭州", daily=(DailyWeather(date=date(2026, 9, 1), condition="晴", risk_level="low", travel_reminder="天气适宜出行", indoor_preferred=False),)), (source("天气", SourceType.weather_api),), ("天气提醒",))
    route = result("route", statuses[1], RoutePlanData(origin="上海", destination="杭州", daily_areas=(DailyArea(day=1, area="西湖"),), daily_itineraries=({"day": 1, "weather_reminder": "天气适宜出行", "attractions": ({"time_slot": "上午", "poi": {"name": "断桥", "category": "景点", "location": "120,30", "source_ids": ("amap:attraction",)}, "suggested_duration_minutes": 90},)},), weather_adjusted=False), (source("高德", SourceType.map_api),), ("路线提醒",))
    lodging = result("lodging", statuses[2], LodgingPlanData(nights=1, recommended_area="西湖"), (source("高德", SourceType.poi_api),), ("住宿提醒",), ("lodging_candidates",) if statuses[2] in {AgentStatus.partial, AgentStatus.degraded} else ())
    food = result("food", statuses[3], FoodPlanData(daily_food=({"day": 1, "area": "西湖"},)), (), ("餐饮提醒",), ("food_day_1_candidates",) if statuses[3] is AgentStatus.partial else ())
    return weather, route, lodging, food


def test_summary_aggregates_sources_first_seen_and_warnings_in_slot_order():
    document = SummaryAgent().run(*results(), request_id=REQUEST_ID, trace_id=REQUEST_ID)

    assert document.status is AgentStatus.success
    assert [(item.name, item.type) for item in document.sources] == [("天气", SourceType.weather_api), ("高德", SourceType.map_api), ("高德", SourceType.poi_api)]
    assert document.warnings == ("天气提醒", "路线提醒", "住宿提醒", "餐饮提醒")
    assert document.degraded_agents == ()


def test_summary_marks_degraded_for_degraded_result_but_not_partial_only_agent():
    values = results((AgentStatus.success, AgentStatus.success, AgentStatus.partial, AgentStatus.success))
    document = SummaryAgent().run(*values, request_id=REQUEST_ID, trace_id=REQUEST_ID)

    assert document.status is AgentStatus.degraded
    assert document.degraded_agents == ()


def test_summary_marks_degraded_agent_only_for_degraded_status():
    values = results((AgentStatus.success, AgentStatus.success, AgentStatus.degraded, AgentStatus.success))
    document = SummaryAgent().run(*values, request_id=REQUEST_ID, trace_id=REQUEST_ID)

    assert document.status is AgentStatus.degraded
    assert document.degraded_agents == ("lodging",)


def test_summary_marks_failed_when_any_result_failed():
    error_result = AgentResult(
        agent="food", status=AgentStatus.failed, summary="food failed",
        missing_fields=("food_plan",), error={"code": "UPSTREAM", "message": "unavailable", "retryable": True},
        request_id=REQUEST_ID, trace_id=REQUEST_ID,
    )
    values = results()
    document = SummaryAgent().run(values[0], values[1], values[2], error_result, request_id=REQUEST_ID, trace_id=REQUEST_ID)

    assert document.status is AgentStatus.failed
    assert document.degraded_agents == ()


def test_summary_markdown_has_fixed_sections_and_no_transactional_or_raw_fields():
    document = SummaryAgent().run(*results(), request_id=REQUEST_ID, trace_id=REQUEST_ID)
    for heading in ("行程概览", "天气与出游风险", "每日路线", "住宿建议", "餐饮建议", "待核验事项", "来源与更新时间", "降级说明"):
        assert f"## {heading}" in document.markdown
    for forbidden in ("price", "inventory", "rating", "queue", "password", "{'", "AgentResult("):
        assert forbidden not in document.markdown


def test_summary_markdown_renders_daily_itinerary_and_food_details_without_raw_fields():
    poi_morning = PoiCandidate(name="故宫", address="故宫地址", category="景点", source_ids=("x",))
    poi_afternoon = PoiCandidate(name="天坛", address="天坛地址", category="景点", source_ids=("y",))
    route_data = RoutePlanData(
        origin="上海", destination="北京", daily_areas=(DailyArea(day=1, area="故宫"),),
        daily_itineraries=(DailyItinerary(day=1, weather_reminder="午后有雨，携带雨具", attractions=(
            TimedAttraction(time_slot="上午", poi=poi_morning, suggested_duration_minutes=120),
            TimedAttraction(time_slot="下午", poi=poi_afternoon, suggested_duration_minutes=120,
                            travel_to_next=RouteEstimate(duration_minutes=18, distance_meters=4200)),
        )),), weather_adjusted=True,
    )
    food_data = FoodPlanData(daily_food=(
        DailyFoodPlan(day=1, area="故宫", meal_period="午餐", nearby_attraction_name="故宫",
                      candidates=(FoodCandidate(poi=PoiCandidate(name="宫廷菜", address="午餐地址", category="餐馆", source_ids=("f",)), specialties=("东坡肉", "龙井虾仁")),)),
        DailyFoodPlan(day=1, area="天坛", meal_period="晚餐", nearby_attraction_name="天坛",
                      filter_suggestions=("请核验官方信息",)),
        DailyFoodPlan(day=2, area="颐和园", meal_period="午餐", nearby_attraction_name="颐和园",
                      filter_suggestions=("请核验第二天午餐官方信息",)),
        DailyFoodPlan(day=2, area="颐和园", meal_period="晚餐", nearby_attraction_name="颐和园",
                      filter_suggestions=("请核验第二天晚餐官方信息",)),
    ))
    values = results()
    route = result("route", AgentStatus.success, route_data)
    food = result("food", AgentStatus.success, food_data)
    document = SummaryAgent().run(values[0], route, values[2], food, request_id=REQUEST_ID, trace_id=REQUEST_ID)
    markdown = document.markdown
    for text in ("### 今日出游提醒", "午后有雨，携带雨具", "## 第 1 天 · 北京", "### 上午 · 故宫", "建议游玩约 120 分钟", "故宫地址", "### 下午 · 天坛", "驾车约 18 分钟、约 4200 米", "### 第 1 天 · 午餐 · 故宫附近", "宫廷菜", "午餐地址", "推荐菜品：东坡肉、龙井虾仁", "### 第 1 天 · 晚餐 · 天坛附近", "### 第 2 天 · 午餐 · 颐和园附近", "### 第 2 天 · 晚餐 · 颐和园附近", "营业时间、菜品与服务安排请以商家官方信息为准。"):
        assert text in markdown
    assert markdown.count("营业时间、菜品与服务安排请以商家官方信息为准。") == 4
    for forbidden in ("rating", "score", "开放时间"):
        assert forbidden not in markdown


def test_summary_only_prompts_missing_transport_between_attractions():
    attractions = (
        TimedAttraction(
            time_slot="上午",
            poi=PoiCandidate(name="上午景点", address="上午地址", category="景点", source_ids=("a",)),
            suggested_duration_minutes=60,
            travel_to_next=RouteEstimate(duration_minutes=10, distance_meters=1000),
        ),
        TimedAttraction(
            time_slot="下午",
            poi=PoiCandidate(name="下午景点", address="下午地址", category="景点", source_ids=("b",)),
            suggested_duration_minutes=60,
        ),
        TimedAttraction(
            time_slot="傍晚",
            poi=PoiCandidate(name="傍晚景点", address="傍晚地址", category="景点", source_ids=("c",)),
            suggested_duration_minutes=60,
        ),
    )
    values = results()
    route = result("route", AgentStatus.success, RoutePlanData(
        origin="上海", destination="北京", daily_areas=(DailyArea(day=1, area="北京"),),
        daily_itineraries=(DailyItinerary(day=1, weather_reminder="天气提醒", attractions=attractions),),
        weather_adjusted=True,
    ))
    document = SummaryAgent().run(values[0], route, values[2], values[3], request_id=REQUEST_ID, trace_id=REQUEST_ID)
    assert "驾车约 10 分钟、约 1000 米" in document.markdown
    assert document.markdown.count("下一段交通信息待核验") == 1
    evening_block = document.markdown.split("### 傍晚 · 傍晚景点", 1)[1].split("## 住宿建议", 1)[0]
    assert "下一段交通信息待核验" not in evening_block


def test_summary_markdown_renders_warning_without_empty_notice():
    document = SummaryAgent().run(*results(), request_id=REQUEST_ID, trace_id=REQUEST_ID)

    assert "- 天气提醒" in document.markdown
    assert "暂无额外核验事项" not in document.markdown
    assert "来源更新时间" in document.markdown
    assert "## 降级说明" in document.markdown


def test_summary_dedupes_sources_ignoring_retrieved_at_and_keeps_first_source():
    first = source("天气", SourceType.weather_api, retrieved_at=STAMP)
    second = source("天气", SourceType.weather_api, retrieved_at=datetime(2026, 8, 22, tzinfo=timezone.utc))
    values = results()
    weather = result("weather", AgentStatus.success, values[0].data, (first, second), ("天气提醒",))

    document = SummaryAgent().run(weather, values[1], values[2], values[3], request_id=REQUEST_ID, trace_id=REQUEST_ID)

    assert len([item for item in document.sources if item.name == "天气"]) == 1
    assert document.sources[0].retrieved_at == STAMP


def test_summary_failed_takes_precedence_over_partial():
    values = results((AgentStatus.success, AgentStatus.success, AgentStatus.partial, AgentStatus.success))
    failed = AgentResult(
        agent="food", status=AgentStatus.failed, summary="food failed",
        missing_fields=("food_plan",), error={"code": "UPSTREAM", "message": "unavailable", "retryable": True},
        request_id=REQUEST_ID, trace_id=REQUEST_ID,
    )

    document = SummaryAgent().run(values[0], values[1], values[2], failed, request_id=REQUEST_ID, trace_id=REQUEST_ID)

    assert document.status is AgentStatus.failed
    assert "food failed" not in document.markdown
    assert "food\\_plan" in document.markdown


def test_summary_failed_only_markdown_names_failed_agent_and_reason():
    values = results()
    failed = AgentResult(
        agent="food", status=AgentStatus.failed, summary="food failed",
        missing_fields=("food_plan",), error={"code": "UPSTREAM", "message": "餐饮服务不可用", "retryable": True},
        request_id=REQUEST_ID, trace_id=REQUEST_ID,
    )

    document = SummaryAgent().run(values[0], values[1], values[2], failed, request_id=REQUEST_ID, trace_id=REQUEST_ID)

    assert "food" in document.markdown
    assert "UPSTREAM" in document.markdown
    assert "food\\_plan" in document.markdown
    assert "各专业结果均已完成" not in document.markdown


def test_summary_escapes_external_newlines_without_extra_heading():
    weather = result(
        "weather", AgentStatus.success,
        WeatherPlanData(destination="杭州\n## 伪造", daily=(DailyWeather(date=date(2026, 9, 1), condition="晴\n## 伪造", risk_level="low", travel_reminder="天气适宜出行", indoor_preferred=False),)),
        (source("天气\n## 伪造", SourceType.weather_api),),
        ("提醒\n## 伪造",),
    )
    values = results()
    document = SummaryAgent().run(weather, values[1], values[2], values[3], request_id=REQUEST_ID, trace_id=REQUEST_ID)

    assert document.markdown.count("## ") == 11
    assert "杭州 \\#\\# 伪造" in document.markdown
    assert "## 伪造" not in document.markdown.replace("## 伪造", "", 1)


def test_summary_escapes_html_markup_and_ampersands_in_external_text():
    values = results()
    weather = result(
        "weather",
        AgentStatus.success,
        WeatherPlanData(
            destination="<script>alert(1)</script> & 城市",
            daily=(DailyWeather(date=date(2026, 9, 1), condition="晴 & <b>危险</b>", risk_level="low", travel_reminder="天气适宜出行", indoor_preferred=False),),
        ),
        (source("天气 & <script>", SourceType.weather_api),),
        ("提醒 & <em>检查</em>",),
    )

    document = SummaryAgent().run(
        weather, values[1], values[2], values[3], request_id=REQUEST_ID, trace_id=REQUEST_ID
    )

    assert "<script>" not in document.markdown
    assert "</script>" not in document.markdown
    assert "<b>" not in document.markdown
    assert "<em>" not in document.markdown
    assert re.search(r"&(?!amp;|lt;|gt;)", document.markdown) is None
    assert "&amp; 城市" in document.markdown


def test_summary_safe_uses_html_entities_without_backslash_bypass():
    safe = SummaryAgent._safe("<script>alert(1)</script> & value")

    assert "&lt;script&gt;" in safe
    assert "&amp; value" in safe
    assert "<script" not in safe
    assert "\\\\<" not in safe


def test_summary_rejects_mismatched_tracking_ids():
    values = results()
    with pytest.raises(ValueError, match="请求追踪标识无效"):
        SummaryAgent().run(*values, request_id=REQUEST_ID, trace_id=str(uuid4()))
