from httpx import ASGITransport, AsyncClient
import pytest

from app.config import Settings
from app.main import create_app
from app.services.fliggy import DisabledFliggyTicketService, FlyAIFliggyTicketService
from app.services.fliggy_flyai_client import FlyAIUpstreamError


@pytest.mark.asyncio
async def test_fliggy_status_is_unavailable_by_default():
    # 显式注入关闭服务，隔离本地 .env 可能开启的 provider。
    app = create_app(fliggy_ticket_service=DisabledFliggyTicketService())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.get("/api/fliggy/status")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "message": "飞猪门票查询服务尚未配置",
    }


@pytest.mark.asyncio
async def test_ticket_search_is_closed_without_fliggy_request():
    app = create_app(fliggy_ticket_service=DisabledFliggyTicketService())

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
    app = create_app(fliggy_ticket_service=DisabledFliggyTicketService())

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


class _StubFlyAIClient:
    def __init__(self, text: str = "西湖门票文本摘要", raise_error: bool = False) -> None:
        self.text = text
        self.raise_error = raise_error

    async def search(self, scenic_keyword, entry_date) -> str:
        if self.raise_error:
            raise FlyAIUpstreamError("TIMEOUT")
        return self.text


@pytest.mark.asyncio
async def test_flyai_provider_with_key_reports_available_without_key_leak():
    settings = Settings(
        _env_file=None,
        fliggy_ticket_provider="flyai",
        flyai_api_key="test-server-key",
    )
    app = create_app(settings=settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.get("/api/fliggy/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert "test-server-key" not in payload["message"]


@pytest.mark.asyncio
async def test_flyai_provider_without_key_stays_disabled():
    settings = Settings(_env_file=None, fliggy_ticket_provider="flyai", flyai_api_key="")
    app = create_app(settings=settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.get("/api/fliggy/status")
        search_response = await client.post(
            "/api/fliggy/tickets/search",
            json={
                "scenic_keyword": "西湖",
                "entry_date": "2099-09-01",
                "visitor_count": 2,
            },
        )

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert search_response.status_code == 503


@pytest.mark.asyncio
async def test_flyai_text_result_endpoint():
    service = FlyAIFliggyTicketService(_StubFlyAIClient())
    app = create_app(fliggy_ticket_service=service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            "/api/fliggy/tickets/search",
            json={
                "scenic_keyword": "西湖",
                "entry_date": "2099-09-01",
                "visitor_count": 2,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_status"] == "flyai_text"
    assert payload["source_name"] == "飞猪 AI 开放平台"
    assert payload["summary"] == "西湖门票文本摘要"
    assert payload["tickets"] == []


@pytest.mark.asyncio
async def test_flyai_upstream_error_maps_to_controlled_503():
    service = FlyAIFliggyTicketService(_StubFlyAIClient(raise_error=True))
    app = create_app(fliggy_ticket_service=service)

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
    assert "TIMEOUT" not in response.text
    assert "FlyAI" not in response.text
