from datetime import date
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.models.travel import (
    AgentResult,
    DailyArea,
    DailyFoodPlan,
    DailyWeather,
    FoodPlanData,
    LodgingPlanData,
    RoutePlanData,
    TravelPlanData,
    TravelPlanDocument,
    WeatherPlanData,
)


def valid_document(request_id: str) -> TravelPlanDocument:
    weather = AgentResult(
        agent="weather", status="success", summary="天气完成",
        data=WeatherPlanData(
            destination="杭州",
            daily=(DailyWeather(date=date(2026, 9, 1), condition="晴", risk_level="low"),),
        ), request_id=request_id, trace_id=request_id,
    )
    route = AgentResult(
        agent="route", status="success", summary="路线完成",
        data=RoutePlanData(
            origin="上海", destination="杭州", daily_areas=(DailyArea(day=1, area="西湖"),),
            weather_adjusted=False,
        ), request_id=request_id, trace_id=request_id,
    )
    lodging = AgentResult(
        agent="lodging", status="success", summary="住宿完成",
        data=LodgingPlanData(nights=0, recommended_area="西湖"), request_id=request_id, trace_id=request_id,
    )
    food = AgentResult(
        agent="food", status="success", summary="餐饮完成",
        data=FoodPlanData(daily_food=(DailyFoodPlan(day=1, area="西湖"),)),
        request_id=request_id, trace_id=request_id,
    )
    return TravelPlanDocument(
        request_id=request_id, trace_id=request_id, status="success",
        itinerary=TravelPlanData(weather=weather, route=route, lodging=lodging, food=food),
        markdown="# 旅行计划",
    )


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
async def test_travel_plan_validates_payload_and_uses_request_id():
    request_id = str(uuid4())
    orchestrator = AsyncMock()
    orchestrator.run.return_value = valid_document(request_id)
    app = create_app(orchestrator=orchestrator)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        response = await client.post(
            "/api/travel-plans",
            headers={"X-Request-Id": request_id},
            json={
                "origin": "上海",
                "destination": "杭州",
                "departure_date": "2026-09-01",
                "travelers": 2,
                "days": 1,
            },
        )

    assert response.status_code == 200
    assert response.json()["markdown"] == "# 旅行计划"
    assert response.json()["itinerary"]["route"]["data"]["daily_areas"][0]["area"] == "西湖"
    orchestrator.run.assert_awaited_once_with(
        ANY, request_id, trace_id=request_id
    )


@pytest.mark.asyncio
async def test_travel_plan_rejects_invalid_payload_with_422():
    app = create_app(orchestrator=AsyncMock())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/travel-plans", json={"origin": "上海"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_travel_plan_hides_unexpected_errors():
    orchestrator = AsyncMock()
    orchestrator.run.side_effect = RuntimeError("secret backend detail")
    app = create_app(orchestrator=orchestrator)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            "/api/travel-plans",
            json={
                "origin": "上海", "destination": "杭州", "departure_date": "2026-09-01", "travelers": 2,
            },
        )
    assert response.status_code == 500
    assert "secret backend detail" not in response.text


@pytest.mark.asyncio
async def test_create_app_injects_settings_into_orchestrator_builder(monkeypatch):
    from app.config import Settings
    import app.main as main_module
    settings = Settings(heweather_api_key="weather", amap_api_key="amap")
    from unittest.mock import Mock
    builder = Mock()
    monkeypatch.setattr(main_module, "build_orchestrator", builder)
    builder.return_value = AsyncMock()
    app = main_module.create_app(settings=settings)
    builder.assert_called_once_with(settings)
    assert app.state.settings is settings


@pytest.mark.asyncio
async def test_ready_uses_injected_settings():
    from app.config import Settings
    settings = Settings(heweather_api_key="", amap_api_key="")
    app = create_app(orchestrator=AsyncMock(), settings=settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.get("/api/ready")
    assert response.status_code == 503


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
