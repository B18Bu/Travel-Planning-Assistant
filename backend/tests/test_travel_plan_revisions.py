from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.models.planning import TravelQueryParseResponse
from app.models.travel import TravelPlanRequest


class Parser:
    async def parse(self, query):
        return TravelQueryParseResponse(
            origin="上海",
            destination="杭州",
            departure_date=date(2026, 9, 10),
            travelers=2,
            days=2,
            preferences=(),
        )


class Orchestrator:
    async def run(self, request, request_id, trace_id):
        return type("Document", (), {"model_dump": lambda self, mode=None: {"markdown": "修订结果"}})()


@pytest.mark.asyncio
async def test_revision_accepts_parser_tuple_preferences_and_increments_version(tmp_path):
    app = create_app()
    app.state.query_parser = Parser()
    app.state.orchestrator = Orchestrator()
    app.state.travel_plan_store.path = tmp_path / "travel_plans.json"
    app.state.travel_plan_store.path.parent.mkdir(parents=True, exist_ok=True)
    app.state.travel_plan_store._write([])
    request = TravelPlanRequest(
        origin="上海", destination="杭州", departure_date=date(2026, 9, 10), travelers=2, days=2
    )
    document = await app.state.orchestrator.run(request, "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000001")
    record = app.state.travel_plan_store.save("上海到杭州", request, document)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            f"/api/travel-plans/saved/{record['plan_id']}/revisions",
            json={"query": "第二天安排室内活动", "version": 1},
        )

    assert response.status_code == 200
    assert response.json()["version"] == 2
