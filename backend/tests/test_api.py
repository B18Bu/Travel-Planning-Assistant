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
async def test_health_replaces_uuid_v6_request_id_with_new_uuid():
    app = create_app()
    uuid_v6 = "550e8400-e29b-61d4-a716-446655440000"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        response = await client.get("/api/health", headers={"X-Request-Id": uuid_v6})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != uuid_v6
    assert len(response.headers["x-request-id"]) == 36
    assert response.headers["x-request-id"][14] == "4"


@pytest.mark.asyncio
async def test_health_normalizes_and_preserves_uuid_v4_request_id():
    app = create_app()
    uuid_v4 = "550E8400-E29B-41D4-A716-446655440000"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        response = await client.get("/api/health", headers={"X-Request-Id": uuid_v4})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == uuid_v4.lower()


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
