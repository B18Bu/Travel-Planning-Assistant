from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.travel import AgentResult, AgentName, AgentStatus, DailyItinerary, ErrorDetail, TravelPlanRequest
from app.orchestration.sequential import SequentialTravelOrchestrator


class RecordingAgent:
    def __init__(self, name, result, calls, *, raises=False):
        self.name = name
        self.result = result
        self.calls = calls
        self.raises = raises

    async def run(self, *args, **kwargs):
        self.calls.append((self.name, args, kwargs))
        if self.raises:
            raise RuntimeError(f"{self.name} exploded")
        return self.result


class RecordingSummary:
    def __init__(self, calls):
        self.calls = calls

    def run(self, *args):
        self.calls.append(("summary", args, {}))
        return "document"


@pytest.fixture
def request_payload():
    return TravelPlanRequest(
        origin="上海", destination="杭州", departure_date=date(2026, 9, 1), travelers=2, days=2
    )


@pytest.mark.asyncio
async def test_orchestrator_runs_agents_in_order_and_passes_contract_values(request_payload):
    calls = []
    weather = SimpleNamespace(constraints=("避开暴雨",), data=SimpleNamespace(constraints=("避开暴雨",)))
    route_itineraries = (DailyItinerary(day=1, weather_reminder="晴", attractions=(), missing_fields=("attractions",)),)
    route = SimpleNamespace(data=SimpleNamespace(daily_areas=("西湖", "灵隐"), daily_itineraries=route_itineraries))
    agents = [
        RecordingAgent("weather", weather, calls),
        RecordingAgent("route", route, calls),
        RecordingAgent("lodging", "lodging-result", calls),
        RecordingAgent("food", "food-result", calls),
    ]
    summary = RecordingSummary(calls)
    orchestrator = SequentialTravelOrchestrator(*agents, summary)

    result = await orchestrator.run(request_payload, "request-id", "trace-id")

    assert result == "document"
    assert [call[0] for call in calls] == ["weather", "route", "lodging", "food", "summary"]
    assert calls[1][1][1] is weather
    assert calls[2][1][1] == ("西湖", "灵隐")
    assert calls[3][1][1] == route_itineraries
    assert calls[0][1][1:] == ("request-id", "trace-id")
    assert calls[1][1][2:] == ("request-id", "trace-id")
    assert calls[4][1][-2:] == ("request-id", "trace-id")


@pytest.mark.asyncio
async def test_orchestrator_continues_after_controlled_agent_failure(request_payload):
    calls = []
    weather = SimpleNamespace(constraints=(), data=None, status="failed")
    route = SimpleNamespace(data=None, status="failed")
    agents = [
        RecordingAgent("weather", weather, calls),
        RecordingAgent("route", route, calls),
        RecordingAgent("lodging", "lodging-result", calls),
        RecordingAgent("food", "food-result", calls),
    ]
    summary = RecordingSummary(calls)
    orchestrator = SequentialTravelOrchestrator(*agents, summary)

    result = await orchestrator.run(request_payload, "request-id", "trace-id")

    assert result == "document"
    assert [call[0] for call in calls] == ["weather", "route", "lodging", "food", "summary"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_index", range(4))
async def test_orchestrator_wraps_agent_exception_and_runs_remaining_agents(request_payload, failed_index):
    calls = []
    results = [
        SimpleNamespace(constraints=("避开暴雨",), data=None),
        SimpleNamespace(data=None),
        "lodging-result",
        "food-result",
    ]
    agents = [
        RecordingAgent(name, result, calls, raises=index == failed_index)
        for index, (name, result) in enumerate(zip(("weather", "route", "lodging", "food"), results))
    ]
    summary = RecordingSummary(calls)
    orchestrator = SequentialTravelOrchestrator(*agents, summary)

    request_id = str(uuid4())
    result = await orchestrator.run(request_payload, request_id, request_id)

    assert result == "document"
    assert [call[0] for call in calls] == ["weather", "route", "lodging", "food", "summary"]
    summary_args = calls[-1][1]
    failed_result = summary_args[failed_index]
    assert isinstance(failed_result, AgentResult)
    assert failed_result.agent.value == ("weather", "route", "lodging", "food")[failed_index]
    assert failed_result.status is AgentStatus.failed
    assert failed_result.data is None
    assert failed_result.request_id == request_id
    assert failed_result.trace_id == request_id
    assert failed_result.error is not None
    assert failed_result.error.code == "agent_execution_failed"
    assert "exploded" not in failed_result.error.message
    assert failed_result.missing_fields
    assert calls[-1][1][-2:] == (request_id, request_id)
    if failed_index == 0:
        assert isinstance(calls[1][1][1], AgentResult)
        assert calls[1][1][1].status is AgentStatus.failed
    if failed_index == 1:
        assert all(area.area == request_payload.destination for area in calls[2][1][1])
        assert all(not item.attractions for item in calls[3][1][1])
        assert all(item.missing_fields == ("attractions",) for item in calls[3][1][1])


@pytest.mark.asyncio
async def test_orchestrator_preserves_failed_route_result_for_summary(request_payload):
    calls = []
    weather = SimpleNamespace(constraints=(), data=None)
    request_id = str(uuid4())
    route = AgentResult(
        agent=AgentName.route,
        status=AgentStatus.failed,
        summary="路线规划失败",
        missing_fields=("route_result",),
        error=ErrorDetail(code="route_failed", message="路线服务不可用", retryable=True),
        request_id=request_id,
        trace_id=request_id,
    )
    agents = [
        RecordingAgent("weather", weather, calls),
        RecordingAgent("route", route, calls),
        RecordingAgent("lodging", "lodging-result", calls),
        RecordingAgent("food", "food-result", calls),
    ]
    summary = RecordingSummary(calls)
    orchestrator = SequentialTravelOrchestrator(*agents, summary)

    await orchestrator.run(request_payload, request_id, request_id)

    summary_route = calls[-1][1][1]
    assert summary_route is route
    assert summary_route.data is None
    assert summary_route.missing_fields == ("route_result",)
    assert summary_route.error.code == "route_failed"
    assert len(calls[2][1][1]) == request_payload.days
    assert len(calls[3][1][1]) == request_payload.days


@pytest.mark.asyncio
async def test_orchestrator_uses_safe_fallback_areas_when_route_has_no_data(request_payload):
    calls = []
    weather = SimpleNamespace(constraints=(), data=None)
    route = SimpleNamespace(data=None)
    agents = [
        RecordingAgent("weather", weather, calls),
        RecordingAgent("route", route, calls),
        RecordingAgent("lodging", "lodging-result", calls),
        RecordingAgent("food", "food-result", calls),
    ]
    summary = RecordingSummary(calls)
    orchestrator = SequentialTravelOrchestrator(*agents, summary)

    await orchestrator.run(request_payload, "request-id", "trace-id")

    fallback = calls[2][1][1]
    assert len(fallback) == request_payload.days
    assert all(area.area == request_payload.destination for area in fallback)
    food_fallback = calls[3][1][1]
    assert len(food_fallback) == request_payload.days
    assert all(not item.attractions for item in food_fallback)
    assert all(item.missing_fields == ("attractions",) for item in food_fallback)
