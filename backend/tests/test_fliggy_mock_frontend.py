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


def test_frontend_renders_flyai_text_summary_without_inner_html():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    # 前端能识别 flyai_text 状态并读取 summary 文本摘要。
    assert "flyai_text" in script
    assert "payload.summary" in script
    # 价格与库存固定显示不可用，不从自然语言猜测。
    assert "价格信息暂不可用" in script
    assert "库存信息暂不可用" in script
    # 同意弹窗改为 FlyAI 只读文案。
    assert "FlyAI" in html
    # renderTicketResults 区域使用 textContent 安全渲染，不使用 innerHTML。
    start = script.index("function renderTicketResults")
    block = script[start:start + 3500]
    assert "innerHTML" not in block


def test_show_view_declares_hotel_nav_before_using_it():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    # showView 在引用 hotel 前必须声明 nav-hotel，否则 ReferenceError 会中断
    # loadFliggyStatus，导致门票视图按钮保持禁用、点击无响应。
    start = script.index("function showView")
    block = script[start:start + 2000]
    assert 'const hotel = document.getElementById("nav-hotel")' in block
    assert "if (hotel)" in block
