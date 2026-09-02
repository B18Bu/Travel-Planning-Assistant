from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.models.planning import TravelQueryParseResponse


def test_parse_response_represents_missing_required_fields():
    response = TravelQueryParseResponse(
        origin="上海", destination="成都", missing_fields=("departure_date", "travelers", "days")
    )
    assert response.departure_date is None
    assert response.missing_fields == ("departure_date", "travelers", "days")


@pytest.mark.asyncio
async def test_parse_endpoint_returns_controlled_missing_fields(monkeypatch):
    app = create_app()

    class Parser:
        async def parse(self, query):
            return TravelQueryParseResponse(
                origin=None,
                destination="成都",
                departure_date=date(2026, 9, 10),
                travelers=2,
                days=3,
                missing_fields=("origin",),
            )

    app.state.query_parser = Parser()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/travel-plans/parse", json={"query": "去成都玩三天"})

    assert response.status_code == 200
    assert response.json()["missing_fields"] == ["origin"]
