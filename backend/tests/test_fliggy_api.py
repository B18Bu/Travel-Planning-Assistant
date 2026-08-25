from httpx import ASGITransport, AsyncClient
import pytest

from app.main import create_app


@pytest.mark.asyncio
async def test_fliggy_status_is_unavailable_by_default():
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.get("/api/fliggy/status")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "message": "飞猪门票查询服务尚未配置",
    }


@pytest.mark.asyncio
async def test_ticket_search_is_closed_without_fliggy_request():
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            "/api/fliggy/tickets/search",
            json={
                "scenic_keyword": "西湖",
                "entry_date": "2099-09-01",
                "visitor_count": 2,
            },
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "飞猪门票查询服务尚未配置"}


@pytest.mark.asyncio
async def test_ticket_search_rejects_unknown_client_fields():
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            "/api/fliggy/tickets/search",
            json={
                "scenic_keyword": "西湖",
                "entry_date": "2099-09-01",
                "visitor_count": 2,
                "item_id": "client-controlled",
            },
        )

    assert response.status_code == 422
