from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.agents.summary import SummaryAgent
from app.models.travel import (
    AgentResult,
    AgentStatus,
    DailyArea,
    DailyWeather,
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
    weather = result("weather", statuses[0], WeatherPlanData(destination="杭州", daily=(DailyWeather(date=date(2026, 9, 1), condition="晴", risk_level="low"),)), (source("天气", SourceType.weather_api),), ("天气提醒",))
    route = result("route", statuses[1], RoutePlanData(origin="上海", destination="杭州", daily_areas=(DailyArea(day=1, area="西湖"),), weather_adjusted=False), (source("高德", SourceType.map_api),), ("路线提醒",))
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
        WeatherPlanData(destination="杭州\n## 伪造", daily=(DailyWeather(date=date(2026, 9, 1), condition="晴\n## 伪造", risk_level="low"),)),
        (source("天气\n## 伪造", SourceType.weather_api),),
        ("提醒\n## 伪造",),
    )
    values = results()
    document = SummaryAgent().run(weather, values[1], values[2], values[3], request_id=REQUEST_ID, trace_id=REQUEST_ID)

    assert document.markdown.count("## ") == 8
    assert "杭州 \\#\\# 伪造" in document.markdown
    assert "## 伪造" not in document.markdown.replace("## 伪造", "", 1)


def test_summary_rejects_mismatched_tracking_ids():
    values = results()
    with pytest.raises(ValueError, match="请求追踪标识无效"):
        SummaryAgent().run(*values, request_id=REQUEST_ID, trace_id=str(uuid4()))
