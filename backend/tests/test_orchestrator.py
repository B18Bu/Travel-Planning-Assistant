from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.travel import AgentResult, AgentStatus, TravelPlanRequest
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
    route = SimpleNamespace(data=SimpleNamespace(daily_areas=("西湖", "灵隐")))
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
    assert calls[1][1][1] == ("避开暴雨",)
    assert calls[2][1][1] == ("西湖", "灵隐")
    assert calls[3][1][1] == ("西湖", "灵隐")
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
        assert calls[1][1][1] == ()
    if failed_index == 1:
        assert all(area.area == request_payload.destination for area in calls[2][1][1])
        assert calls[2][1][1] == calls[3][1][1]


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
    assert fallback == calls[3][1][1]
    assert len(fallback) == request_payload.days
    assert all(area.area == request_payload.destination for area in fallback)
