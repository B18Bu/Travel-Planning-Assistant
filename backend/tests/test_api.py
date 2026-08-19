import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_health_returns_request_id_and_security_headers():
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


@pytest.mark.asyncio
async def test_health_does_not_allow_untrusted_cross_origin_request():
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        response = await client.get(
            "/api/health", headers={"Origin": "https://untrusted.example"}
        )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_ready_returns_generic_error_without_external_service_keys(monkeypatch):
    monkeypatch.setenv("HEWEATHER_API_KEY", "")
    monkeypatch.setenv("AMAP_API_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        response = await client.get("/api/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "外部数据服务尚未配置"}
    assert "HEWEATHER_API_KEY" not in response.text
    assert "AMAP_API_KEY" not in response.text
