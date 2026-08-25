from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
import respx

from app.errors import FliggyHotelNotConfigured, FliggyHotelUpstreamError
from app.main import create_app
from app.models.fliggy_hotel import (
    FliggyHotel,
    FliggyHotelSearchResponse,
    FliggyHotelSource,
)


class FakeHotelService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def search(self, payload, trace_id):
        self.calls.append((payload, trace_id))
        if self.error is not None:
            raise self.error
        return self.result


def hotel_response(trace_id: str) -> FliggyHotelSearchResponse:
    return FliggyHotelSearchResponse(
        source=FliggyHotelSource(retrieved_at=datetime(2026, 8, 25, tzinfo=timezone.utc)),
        hotels=(FliggyHotel(hotel_id="100", name="西湖酒店", low_price=Decimal("88.50")),),
        total=1,
        page_no=1,
        page_size=20,
        trace_id=trace_id,
    )


def payload() -> dict:
    return {
        "city_name": "杭州",
        "check_in": "2099-09-01",
        "check_out": "2099-09-02",
    }


@pytest.mark.asyncio
async def test_hotel_search_returns_response_and_decimal_as_json_number():
    trace_id = str(uuid4())
    service = FakeHotelService(result=hotel_response(trace_id))
    app = create_app(fliggy_hotel_service=service)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/fliggy/hotels/search", json=payload(), headers={"X-Request-Id": trace_id})

    assert response.status_code == 200
    assert response.json()["hotels"][0]["low_price"] == 88.5
    assert isinstance(response.json()["hotels"][0]["low_price"], float)


@pytest.mark.asyncio
async def test_hotel_search_passes_request_id_as_trace_id():
    trace_id = str(uuid4())
    service = FakeHotelService(result=hotel_response(trace_id))
    app = create_app(fliggy_hotel_service=service)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/fliggy/hotels/search", json=payload(), headers={"X-Request-Id": trace_id})

    assert response.status_code == 200
    assert service.calls[0][1] == trace_id


@pytest.mark.asyncio
async def test_hotel_search_generates_uuid4_trace_id_when_request_state_is_missing():
    trace_id = str(uuid4())
    service = FakeHotelService(result=hotel_response(trace_id))
    app = create_app(fliggy_hotel_service=service)
    app.user_middleware.clear()
    app.middleware_stack = app.build_middleware_stack()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/fliggy/hotels/search", json=payload())

    assert response.status_code == 200
    generated_trace_id = service.calls[0][1]
    assert UUID(generated_trace_id).version == 4


@pytest.mark.asyncio
async def test_hotel_search_returns_fixed_503_when_not_configured():
    app = create_app(fliggy_hotel_service=FakeHotelService(error=FliggyHotelNotConfigured()))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/fliggy/hotels/search", json=payload())

    assert response.status_code == 503
    assert response.json() == {"detail": "飞猪酒店查询服务尚未配置"}


@pytest.mark.asyncio
async def test_hotel_search_returns_safe_502_with_controlled_error_and_trace_id():
    trace_id = str(uuid4())
    service = FakeHotelService(
        error=FliggyHotelUpstreamError("AUTH_ERROR", "PROVIDER_1", retryable=False)
    )
    app = create_app(fliggy_hotel_service=service)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/fliggy/hotels/search", json=payload(), headers={"X-Request-Id": trace_id})

    assert response.status_code == 502
    assert response.json() == {
        "detail": {"code": "AUTH_ERROR", "provider_code": "PROVIDER_1", "trace_id": trace_id}
    }
    assert "secret" not in response.text.lower()
    assert "body" not in response.text.lower()


@pytest.mark.asyncio
async def test_hotel_search_rejects_unknown_fields_with_422():
    app = create_app(fliggy_hotel_service=FakeHotelService(result=hotel_response(str(uuid4()))))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/fliggy/hotels/search", json={**payload(), "unexpected": "value"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_hotel_search_disabled_does_not_call_external_request():
    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://eco.taobao.com/router/rest").respond(status_code=500)
        app = create_app()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
            response = await client.post("/api/fliggy/hotels/search", json=payload())

        assert response.status_code == 503
        assert not mock.calls
