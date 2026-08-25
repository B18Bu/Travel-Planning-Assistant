from httpx import ASGITransport, AsyncClient
import pytest

from app.main import create_app
from app.services.fliggy import MockFliggyTicketService


@pytest.mark.asyncio
async def test_mock_ticket_search_returns_displayable_products():
    app = create_app(fliggy_ticket_service=MockFliggyTicketService())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            "/api/fliggy/tickets/search",
            json={"scenic_keyword": "西湖", "entry_date": "2099-09-01", "visitor_count": 2},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_status"] == "mock"
    assert payload["source_name"] == "演示数据"
    assert len(payload["tickets"]) == 2
    assert payload["tickets"][0]["price_amount"] == 1234
