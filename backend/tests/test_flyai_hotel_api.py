from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.models.flyai_hotel import CombinedHotelResult
from app.services.flyai_hotel_client import FlyAIHotelError
from app.services.flyai_hotel_recommendation import HotelRecommendationResults


class FakeRecommendationService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def recommend(self, request):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.result


def recommendation_result() -> HotelRecommendationResults:
    return HotelRecommendationResults(
        (
            CombinedHotelResult(
                hotel_name="西湖饭店",
                flyai_price=Decimal("280"),
                flyai_score=Decimal("4.5"),
                flyai_star=4,
                flyai_main_pic="https://example.com/main.jpg",
                detail_url="https://example.com/hotel",
                amap_address="西湖边",
                amap_location="120.1,30.2",
                price_source="flyai",
                poi_source="amap",
                match_status="matched",
            ),
        ),
        flyai_retrieved_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        amap_retrieved_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        poi_unavailable=False,
    )


def payload(**overrides) -> dict:
    body = {
        "city_name": "杭州",
        "check_in": "2099-09-01",
        "check_out": "2099-09-02",
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_recommendation_merges_flyai_price_and_amap_address():
    service = FakeRecommendationService(result=recommendation_result())
    app = create_app(flyai_hotel_recommendation_service=service)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/fliggy/hotels/recommend", json=payload())

    assert response.status_code == 200
    item = response.json()["hotels"][0]
    assert item["hotel_name"] == "西湖饭店"
    assert item["flyai_price"] == 280
    assert isinstance(item["flyai_price"], int)
    assert item["amap_address"] == "西湖边"
    assert item["price_source"] == "flyai"
    assert item["poi_source"] == "amap"
    assert item["match_status"] == "matched"


@pytest.mark.asyncio
async def test_recommendation_returns_fixed_503_when_disabled():
    app = create_app(settings=Settings(_env_file=None))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/fliggy/hotels/recommend", json=payload())

    assert response.status_code == 503
    assert response.json() == {"detail": "飞猪酒店查询服务尚未配置"}


@pytest.mark.asyncio
async def test_recommendation_returns_503_when_key_missing_but_enabled():
    app = create_app(settings=Settings(_env_file=None, flyai_hotel_enabled=True))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/fliggy/hotels/recommend", json=payload())

    assert response.status_code == 503
    assert response.json() == {"detail": "飞猪酒店查询服务尚未配置"}


@pytest.mark.asyncio
async def test_recommendation_returns_safe_502_with_controlled_error_and_trace_id():
    trace_id = str(uuid4())
    service = FakeRecommendationService(error=FlyAIHotelError("TIMEOUT"))
    app = create_app(flyai_hotel_recommendation_service=service)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            "/api/fliggy/hotels/recommend", json=payload(), headers={"X-Request-Id": trace_id}
        )

    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "TIMEOUT", "trace_id": trace_id}}
    assert "secret" not in response.text.lower()


@pytest.mark.asyncio
async def test_recommendation_502_generates_uuid4_trace_id_when_request_state_missing():
    service = FakeRecommendationService(error=FlyAIHotelError("CLI_ERROR"))
    app = create_app(flyai_hotel_recommendation_service=service)
    app.user_middleware.clear()
    app.middleware_stack = app.build_middleware_stack()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/fliggy/hotels/recommend", json=payload())

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "CLI_ERROR"
    assert UUID(detail["trace_id"]).version == 4


@pytest.mark.asyncio
async def test_recommendation_rejects_unknown_fields_with_422():
    service = FakeRecommendationService(result=recommendation_result())
    app = create_app(flyai_hotel_recommendation_service=service)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            "/api/fliggy/hotels/recommend", json={**payload(), "unexpected": "value"}
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_recommendation_caps_request_limit_to_server_setting():
    settings = Settings(_env_file=None, flyai_hotel_limit=5)
    service = FakeRecommendationService(result=recommendation_result())
    app = create_app(flyai_hotel_recommendation_service=service, settings=settings)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/fliggy/hotels/recommend", json=payload(limit=20))

    assert response.status_code == 200
    assert service.calls[0].limit == 5
