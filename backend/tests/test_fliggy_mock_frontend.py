from pathlib import Path


FRONTEND_DIR = Path(__file__).parents[2] / "frontend"


def test_frontend_renders_ticket_price_stock_and_mock_warning():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "renderTicketResults" in script
    assert "price_amount" in script
    assert "stock_status" in script
    assert "当前为演示数据" in script
    assert "库存为 0" in script
    assert "价格信息暂不可用" in script
