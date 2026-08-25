from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.models.fliggy import TicketPoiReference, TicketSearchRequest, TicketSearchResponse


def test_ticket_search_accepts_minimal_request() -> None:
    request = TicketSearchRequest(
        scenic_keyword="西湖",
        entry_date=date.today(),
        visitor_count=2,
    )

    assert request.scenic_keyword == "西湖"
    assert request.visitor_count == 2
    assert request.city_name == ""


def test_ticket_search_accepts_and_strips_city_name() -> None:
    request = TicketSearchRequest(
        scenic_keyword="八达岭长城",
        city_name=" 北京 ",
        entry_date=date.today(),
        visitor_count=2,
    )

    assert request.city_name == "北京"


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


def test_ticket_search_response_accepts_flyai_text_summary_without_products() -> None:
    response = TicketSearchResponse(
        source_name="FlyAI",
        retrieved_at="2026-08-25T12:00:00Z",
        data_status="flyai_text",
        scenic_keyword="西湖",
        visitor_count=2,
        summary="建议提前预约。",
    )

    assert response.data_status == "flyai_text"
    assert response.summary == "建议提前预约。"
    assert response.tickets == ()


def test_ticket_search_response_rejects_raw_response() -> None:
    with pytest.raises(ValidationError):
        TicketSearchResponse(
            source_name="FlyAI",
            retrieved_at="2026-08-25T12:00:00Z",
            data_status="flyai_text",
            scenic_keyword="西湖",
            visitor_count=2,
            summary="建议提前预约。",
            raw_response={"text": "建议提前预约。"},
        )


def test_ticket_search_response_accepts_poi_references_with_price() -> None:
    response = TicketSearchResponse(
        source_name="飞猪 AI 开放平台",
        retrieved_at="2026-08-25T12:00:00Z",
        data_status="flyai_text",
        scenic_keyword="八达岭长城",
        city_name="北京",
        visitor_count=2,
        poi_results=(
            TicketPoiReference(
                poi_name="八达岭长城",
                address="北京市延庆区G6京藏高速58号出口",
                category="历史古迹",
                ticket_name="夜场票 不限人群",
                price_text="¥198",
                description="八达岭长城历史景点之一。",
            ),
        ),
    )

    assert response.poi_results[0].price_text == "¥198"
    assert response.poi_results[0].address is not None
