from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.models.fliggy import TicketSearchRequest


def test_ticket_search_accepts_minimal_request() -> None:
    request = TicketSearchRequest(
        scenic_keyword="西湖",
        entry_date=date.today(),
        visitor_count=2,
    )

    assert request.scenic_keyword == "西湖"
    assert request.visitor_count == 2


def test_ticket_search_rejects_past_date_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TicketSearchRequest(
            scenic_keyword="西湖",
            entry_date=date.today() - timedelta(days=1),
            visitor_count=2,
            item_id="must-not-be-client-controlled",
        )


def test_ticket_search_rejects_invalid_visitor_count() -> None:
    with pytest.raises(ValidationError):
        TicketSearchRequest(
            scenic_keyword="西湖",
            entry_date=date.today(),
            visitor_count=21,
        )
