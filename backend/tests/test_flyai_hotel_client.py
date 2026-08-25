from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.flyai_hotel import FlyAIHotel, FlyAIHotelSearchRequest
from app.services.flyai_hotel_client import FlyAIHotelClient, FlyAIHotelError


@pytest.fixture
def hotel_request() -> FlyAIHotelSearchRequest:
    check_in = date.today() + timedelta(days=1)
    return FlyAIHotelSearchRequest(
        city_name="杭州",
        poi_name="西湖",
        check_in=check_in,
        check_out=check_in + timedelta(days=1),
        sort="price_desc",
        max_price=Decimal("500"),
        limit=5,
    )


@pytest.mark.asyncio
async def test_search_hotels_builds_safe_cli_args_and_projects_whitelist(hotel_request):
    calls = []

    async def fake_run(command, args, timeout):
        calls.append((command, args, timeout))
        return '{"data":{"itemList":[{"name":"酒店A","address":"西湖边","lat":30.2,"lon":120.1,"mainPic":"https://example.com/a.jpg","detailUrl":"https://example.com/a","price":280,"score":4.5,"star":4,"shId":123,"secret":"discard"}]}}'

    result = await FlyAIHotelClient("test-secret", runner=fake_run).search_hotels(hotel_request)

    assert calls == [
        (
            "flyai",
            [
                "search-hotel", "--dest-name", "杭州", "--poi-name", "西湖",
                "--check-in-date", hotel_request.check_in.isoformat(),
                "--check-out-date", hotel_request.check_out.isoformat(),
                "--sort", "price_desc", "--limit", "5", "--max-price", "500",
            ],
            30.0,
        )
    ]
    assert result == [
        FlyAIHotel(
            hotel_id=123, name="酒店A", address="西湖边", latitude=30.2,
            longitude=120.1, main_pic="https://example.com/a.jpg",
            detail_url="https://example.com/a", price=280, score=4.5, star=4,
        )
    ]
    assert all("test-secret" not in arg for arg in calls[0][1])


@pytest.mark.asyncio
async def test_search_hotels_prefers_official_coordinates_and_falls_back_to_aliases(hotel_request):
    async def fake_run(command, args, timeout):
        return '{"data":{"itemList":[{"name":"官方坐标","shId":1,"latitude":31.1,"longitude":121.2,"lat":30.1,"lon":120.2},{"name":"兼容坐标","shId":2,"lat":30.3,"lon":120.4}]}}'

    result = await FlyAIHotelClient("secret", runner=fake_run).search_hotels(hotel_request)

    assert result[0].latitude == Decimal("31.1")
    assert result[0].longitude == Decimal("121.2")
    assert result[1].latitude == Decimal("30.3")
    assert result[1].longitude == Decimal("120.4")


@pytest.mark.asyncio
async def test_missing_price_stays_none_and_non_https_links_are_not_projected(hotel_request):
    async def fake_run(command, args, timeout):
        return '{"data":{"itemList":[{"name":"无价酒店","shId":"x1","mainPic":"http://bad/p.jpg","detailUrl":"not-a-url"}]}}'

    result = await FlyAIHotelClient("secret", runner=fake_run).search_hotels(hotel_request)

    assert result[0].price is None
    assert result[0].main_pic is None
    assert result[0].detail_url is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "runner_result, code",
    [
        ((1, "", "private API key leaked"), "CLI_ERROR"),
        ("not-json", "INVALID_RESPONSE"),
        ('{"data":{}}', "INVALID_RESPONSE"),
    ],
)
async def test_cli_failures_are_mapped_to_fixed_safe_errors(hotel_request, runner_result, code):
    async def fake_run(command, args, timeout):
        return runner_result

    with pytest.raises(FlyAIHotelError) as exc:
        await FlyAIHotelClient("super-secret", runner=fake_run).search_hotels(hotel_request)

    assert exc.value.code == code
    assert "super-secret" not in str(exc.value)
    assert "private API key leaked" not in str(exc.value)


@pytest.mark.asyncio
async def test_timeout_is_a_fixed_safe_error(hotel_request):
    async def fake_run(command, args, timeout):
        raise TimeoutError("secret timeout details")

    with pytest.raises(FlyAIHotelError) as exc:
        await FlyAIHotelClient("secret", timeout_seconds=2, runner=fake_run).search_hotels(hotel_request)

    assert exc.value.code == "TIMEOUT"
    assert "secret timeout details" not in repr(exc.value)
