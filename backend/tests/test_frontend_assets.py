from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.main import create_app


FRONTEND_DIR = Path(__file__).parents[2] / "frontend"


@pytest.mark.parametrize(
    "asset",
    ["index.html", "app.js", "styles.css", "vendor/marked.min.js", "vendor/purify.min.js"],
)
def test_frontend_assets_are_present_and_non_empty(asset: str):
    asset_path = FRONTEND_DIR / asset
    assert asset_path.is_file()
    assert asset_path.stat().st_size > 0


@pytest.mark.asyncio
async def test_root_serves_same_origin_frontend_page():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "旅行规划" in response.text
    assert "<script" in response.text
    assert 'name="departure_date"' in response.text


def test_frontend_has_intro_and_real_workspace_views():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    assert 'id="intro"' in html
    assert 'id="workspace"' in html
    assert 'id="start-experience"' in html
    assert 'id="new-plan"' in html
    assert 'id="travel-form"' in html


def test_frontend_matches_prototype_views_and_removes_quick_regions():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    styles = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    for marker in (
        'class="intro-inner"',
        'class="topbar"',
        'class="shell"',
        'id="history-panel"',
        'id="view-home"',
        'id="view-task"',
        'id="view-dashboard"',
        'id="settings-mask"',
        'id="confirm-mask"',
        'class="travel-window"',
        'id="home-origin"',
        'id="home-dest"',
    ):
        assert marker in html
    assert "quick-row" not in html
    assert "region-chip" not in html
    assert "quickRegion" not in script
    for animation in ("viewIn", "waveBeat", "pulse", "growBar", "fadeRow", "introRise", "introFeatureIn", "routeIn", "nodeBreath", "fadeUp"):
        assert f"@keyframes {animation}" in styles


def test_frontend_marks_unavailable_prototype_capabilities_as_non_interactive():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    assert "数字人讲解占位" in html
    assert "/api/knowledge" not in html
    assert "/api/dashboard" not in html


def test_frontend_switches_intro_and_resets_real_plan_without_network_side_effects():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "startExperience" in script
    assert "startNewPlan" in script
    assert "workspace.hidden" in script
    assert 'intro.classList.add("hidden")' in script
    assert "form.reset" in script


def test_frontend_isolates_cancelled_requests_and_handles_abort_silently():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "AbortController" in script
    assert "requestGeneration" in script
    assert "signal: controller.signal" in script
    assert "requestError.name === \"AbortError\"" in script
    assert "generation !== requestGeneration" in script


def test_frontend_brand_returns_to_intro_with_button_event():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="back-to-intro"' in html
    assert 'href="#intro"' not in html
    assert "backToIntroButton.addEventListener" in script
    assert "showIntro" in script


def test_frontend_uses_relative_api_and_local_security_dependencies():
    app_js = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
    index_html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")

    assert 'fetch("/api/travel-plans"' in app_js or "fetch('/api/travel-plans'" in app_js
    assert "https://" not in app_js
    assert "cdn" not in index_html.lower()
    assert "/vendor/marked.min.js" in index_html
    assert "/vendor/purify.min.js" in index_html


def test_frontend_preserves_safe_rendering_inside_workbench():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "startExperienceButton.addEventListener" in script
    assert "newPlanButton.addEventListener" in script
    assert "result = taskView" in script
    assert "DOMPurify.sanitize" in script
    assert "body.innerHTML = safeMarkdown" in script
    assert "JSON.stringify(documentData)" not in script
    assert 'fetch("/api/knowledge"' not in script
    assert 'fetch("/api/dashboard"' not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


def test_frontend_makes_api_failures_visible_without_serializing_response_json():
    app_js = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "response.ok" in app_js
    assert "replaceChildren" in app_js
    assert "textContent" in app_js
    assert "JSON.stringify(body)" in app_js
    assert "JSON.stringify(documentData)" not in app_js
    assert "innerHTML" in app_js
    assert "DOMPurify.sanitize" in app_js
    assert "FORBID_TAGS" in app_js
    assert "FORBID_ATTR" in app_js


def test_frontend_has_two_column_desktop_and_single_column_narrow_layout():
    styles = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")

    assert "grid-template-columns" in styles
    assert "768px" in styles
    assert "grid-template-columns: 1fr" in styles


def test_frontend_uses_standard_json_encoding_and_validates_numeric_fields():
    app_js = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "JSON.stringify(body)" in app_js
    assert "Number.isInteger" in app_js
    assert "Number.isFinite" in app_js
    assert "travelers" in app_js and "days" in app_js
    assert "setError" in app_js
    assert "encodeRequest" not in app_js


def test_frontend_safely_displays_non_2xx_details_without_raw_serialization():
    app_js = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "response.json()" in app_js
    assert "detail" in app_js
    assert "请求参数不符合要求" in app_js
    assert "response.status" in app_js
    assert "textContent" in app_js
    assert "JSON.stringify" not in app_js.replace("JSON.stringify(body)", "")
    assert "response.text()" not in app_js


def test_frontend_distinguishes_failed_documents_and_rejects_past_dates():
    app_js = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert 'documentData.status === "failed"' in app_js
    assert 'documentData.status === "success"' in app_js
    assert "规划生成失败" in app_js
    assert 'documentData.status === "failed" ? "规划生成失败，以下内容仅供核验。"' in app_js
    assert "departure_date" in app_js
    assert "new Date" in app_js
    assert "出行日期不得早于今天" in app_js


@pytest.mark.asyncio
async def test_health_api_starts_when_frontend_directory_is_missing(monkeypatch, tmp_path):
    missing_frontend = tmp_path / "missing-frontend"
    monkeypatch.setattr(main_module, "_frontend_dir", lambda: missing_frontend)
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.get("/api/health")
        root_response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert root_response.status_code == 404
    assert not any(getattr(route, "name", "") == "frontend" for route in app.routes)
