from __future__ import annotations

from datetime import date

import pytest

from app.models.fliggy import TicketSearchRequest
from app.services.fliggy import FlyAIFliggyTicketService
from app.services.fliggy_flyai_client import FlyAIUpstreamError


class _StubFlyAIClient:
    def __init__(self, text: str = "西湖门票摘要", raise_error: bool = False) -> None:
        self.text = text
        self.raise_error = raise_error
        self.calls: list[tuple[str, date]] = []

    async def search(self, scenic_keyword: str, entry_date: date) -> str:
        self.calls.append((scenic_keyword, entry_date))
        if self.raise_error:
            raise FlyAIUpstreamError("TIMEOUT")
        return self.text


def _request() -> TicketSearchRequest:
    return TicketSearchRequest(
        scenic_keyword="西湖",
        entry_date=date(2099, 9, 1),
        visitor_count=2,
    )


@pytest.mark.asyncio
async def test_flyai_service_returns_text_summary_without_fabricating_fields() -> None:
    service = FlyAIFliggyTicketService(_StubFlyAIClient(text="西湖门票文本摘要"))
    response = await service.search_tickets(_request())

    assert response.data_status == "flyai_text"
    assert response.source_name == "飞猪 AI 开放平台"
    assert response.summary == "西湖门票文本摘要"
    assert response.tickets == ()
    assert any("不代表实时可售状态" in warning for warning in response.warnings)
    assert any("价格信息暂不可用" in warning for warning in response.warnings)
    assert any("库存信息暂不可用" in warning for warning in response.warnings)


@pytest.mark.asyncio
async def test_flyai_service_returns_empty_for_blank_text() -> None:
    service = FlyAIFliggyTicketService(_StubFlyAIClient(text="   "))
    response = await service.search_tickets(_request())

    assert response.data_status == "flyai_text"
    assert response.summary is None
    assert response.tickets == ()
    assert any("调整关键词" in warning for warning in response.warnings)


@pytest.mark.asyncio
async def test_flyai_service_passes_scenic_and_date_to_client() -> None:
    stub = _StubFlyAIClient()
    service = FlyAIFliggyTicketService(stub)
    await service.search_tickets(_request())

    assert stub.calls == [("西湖", date(2099, 9, 1))]


@pytest.mark.asyncio
async def test_flyai_service_propagates_controlled_upstream_error() -> None:
    service = FlyAIFliggyTicketService(_StubFlyAIClient(raise_error=True))

    with pytest.raises(FlyAIUpstreamError) as exc_info:
        await service.search_tickets(_request())

    assert exc_info.value.code == "TIMEOUT"
