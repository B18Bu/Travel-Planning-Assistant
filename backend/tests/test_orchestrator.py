from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.travel import TravelPlanRequest
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
