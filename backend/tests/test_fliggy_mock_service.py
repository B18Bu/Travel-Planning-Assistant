from datetime import date

from app.models.fliggy import TicketSearchRequest
from app.services.fliggy import MockFliggyTicketService


def test_mock_service_resolves_scenic_and_returns_all_ticket_products() -> None:
    service = MockFliggyTicketService()
    response = service.search_tickets(
        TicketSearchRequest(
            scenic_keyword="西湖",
            entry_date=date(2099, 9, 1),
            visitor_count=2,
        )
    )

    assert response.data_status == "mock"
    assert response.source_name == "演示数据"
    assert len(response.tickets) == 2
    assert {item.ticket_type for item in response.tickets} == {"成人票", "儿童票"}
    assert all(item.entry_date == date(2099, 9, 1) for item in response.tickets)


def test_mock_service_returns_empty_for_unknown_scenic() -> None:
    service = MockFliggyTicketService()
    response = service.search_tickets(
        TicketSearchRequest(
            scenic_keyword="不存在的景点",
            entry_date=date(2099, 9, 1),
            visitor_count=1,
        )
    )

    assert response.tickets == ()
    assert "未找到" in response.warnings[0]
