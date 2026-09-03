from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.main import create_app


FRONTEND_DIR = Path(__file__).parents[2] / "frontend"


def test_frontend_prompts_only_the_first_missing_travel_field():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "const field = [...new Set(missing)][0]" in script
    assert '"请补充"' in script
    assert "throw new Error(`${prefix}${labels[field] || field}`)" in script
    assert "以下字段是必填项或信息不明确" not in script


def test_frontend_sends_original_travel_query_in_json_body_not_headers():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "X-Travel-Query" not in script
    assert "delete body.query;" in script
    assert "JSON.stringify({ ...body, profile: parsed.profile, original_query: queryInput.value.trim() })" in script


def test_frontend_maps_controlled_knowledge_empty_reasons_without_exposing_backend_errors():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    for reason in ("no_ready_documents", "no_region_documents", "no_matching_chunks"):
        assert reason in script
    assert "暂无可检索资料，请先上传文档并等待处理完成。" in script
    assert "目标地区暂无已处理资料，请更换地区或上传相关攻略。" in script
    assert "未找到相关内容，请尝试更具体的景点、玩法或主题关键词。" in script
    assert "检索引擎暂时不可用，请稍后重试。" in script


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


def test_frontend_uses_ticket_query_view():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "门票查询" in html
    assert 'id="view-ticket"' in html
    assert 'id="ticket-form"' in html
    assert 'class="ticket-query-card"' in html
    assert 'class="ticket-query-fields"' in html
    assert 'class="ticket-query-actions"' in html
    assert 'class="ticket-query-field scenic"' in html
    assert '"/api/fliggy/status"' in script
    assert "sessionStorage" in script
    assert "预订" not in html


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
    assert "sessionStorage" in script
    assert "FLIGGY_CONSENT_KEY" in script


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


def test_document_library_adds_only_approved_navigation_and_search_scope_ui():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
    styles = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")

    for marker in (
        'id="nav-library"',
        "showView('library')",
        'id="view-library"',
        'id="document-upload"',
        'id="document-upload" type="file" accept=".docx,.pdf,application/pdf" multiple',
        'id="library-status"',
        'id="library-list"',
        'id="library-detail"',
        "检索范围：全部已处理文档",
        'id="knowledge-results"',
    ):
        assert marker in html

    for marker in (
        "async function loadDocuments(isPolling = false, preserveStatus = false)",
        "if (!preserveStatus) setLibraryStatus",
        "文档库服务不可用：${documentErrorMessage(requestError, \"请稍后重试。\")}",
        'fetch("/api/documents")',
        'formData.append("files", file)',
        'fetch("/api/documents/batch", { method: "POST", body: formData })',
        "result.index",
        "file.name",
        "summaries.join(\"\\n\")",
        "documentUpload.value = \"\"",
        "if (!Array.isArray(payload.items))",
        "cancelDocumentPolling();",
        "await loadDocuments(false, true)",
        'fetch(`/api/documents/${documentId}`, { method: "DELETE" })',
        'fetch("/api/knowledge-search"',
        "textContent",
        "documentPollAttempts < 30",
        "2000",
        "let documentRequestGeneration = 0",
        "function cancelDocumentPolling()",
        "window.clearTimeout(documentPollTimer)",
        "const generation = ++documentRequestGeneration",
        "if (generation !== documentRequestGeneration || activeView !== \"library\") return;",
        "if (name !== \"library\") cancelLibraryRequests();",
        "const locations = [",
        "locations.join(\" · \")",
        "source.table ? `表 ${source.table}` : \"\"",
        'source.document_name || "未知来源"',
    ):
        assert marker in script

    load_documents_start = script.index("async function loadDocuments")
    upload_document_start = script.index("async function uploadDocument")
    load_documents = script[load_documents_start:upload_document_start]
    assert "documents = [];" not in load_documents
    assert "renderDocuments();" not in load_documents[load_documents.index("catch (requestError)"):]

    for selector in (
        ".library-head",
        ".library-list",
        ".library-card",
        ".library-upload",
        ".library-chunk",
        ".knowledge-results",
        ".knowledge-result",
        ".search-scope",
    ):
        assert selector in styles

    # 现有功能页保持统一双栏布局和关键卡片样式。
    assert "grid-template-columns: minmax(0, 1fr) minmax(320px, .92fr)" in styles
    assert ".travel-window {\n    position: relative; height: 210px;" in styles
    assert ".digital-human-card { min-height: 220px;" in styles
    assert ".digital-human-card, .search-card {\n    background: linear-gradient(180deg, #ffffff, #f8fbff); border: 1px solid var(--border); border-radius: 18px;\n    padding: 22px;" in styles
    assert ".search-card .knowledge-results" not in styles
    assert ".search-card .search-scope" not in styles

    # 检索提示与结果必须是搜索卡的独立同级区域，不能撑高既有搜索卡。
    search_card_start = html.index('<div class="search-card">')
    knowledge_panel_start = html.index('<section class="knowledge-panel">', search_card_start)
    search_card_html = html[search_card_start:knowledge_panel_start]
    assert "knowledge-results" not in search_card_html
    assert "search-scope" not in search_card_html
    assert 'class="knowledge-panel"' in html


def test_frontend_prevents_stale_document_detail_and_knowledge_search_renders():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "let documentDetailGeneration = 0" in script
    assert "let knowledgeRequestGeneration = 0" in script
    assert "const generation = ++documentDetailGeneration" in script
    assert "const generation = ++knowledgeRequestGeneration" in script
    assert "generation !== documentDetailGeneration || activeView !== \"library\"" in script
    assert "generation !== knowledgeRequestGeneration || activeView !== \"guide\"" in script
    assert "let activeDocumentDetailId = null" in script
    assert "function cancelLibraryRequests()" in script
    assert 'if (name !== "library") cancelLibraryRequests();' in script
    assert 'if (activeView === "library") cancelLibraryRequests();' in script
    assert 'if (documentId === activeDocumentDetailId)' in script
    assert 'activeDocumentDetailId !== documentData.id' in script
    assert 'activeDocumentDetailId = null;' in script
    assert 'activeView = "intro";' in script


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


def test_frontend_submits_model_extracted_preference_profile_with_plan_request():
    app_js = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "profile: parsed.profile" in app_js


def test_frontend_safely_displays_non_2xx_details_without_raw_serialization():
    app_js = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "response.json()" in app_js
    assert "detail" in app_js
    assert "请求参数不符合要求" in app_js
    assert "response.status" in app_js
    assert "textContent" in app_js
    assert "JSON.stringify(documentData)" not in app_js
    assert "JSON.stringify({ query, document_ids: [] })" in app_js
    assert "JSON.stringify({ query: task.query, document_ids: [], generate_markdown: true, record_id: task.id })" in app_js
    assert "JSON.stringify({ rating })" in app_js
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


def test_frontend_answers_markdown_via_modal_and_persists_knowledge_records():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
    styles = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")

    for marker in (
        'id="answer-mask"',
        'id="answer-query-note"',
        'id="answer-content"',
        "closeAnswerModal",
        'id="records-mask"',
        'id="records-list"',
        "openRecordsModal",
        "管理记录 →",
    ):
        assert marker in html

    for marker in (
        "openAnswerModal",
        "closeAnswerModal",
        "generate_markdown",
        "answer_status",
        "answer-markdown",
        'fetch("/api/knowledge-records"',
        "loadKnowledgeRecords",
        "addKnowledgeTask",
        "deleteKnowledgeRecord",
        "clearKnowledgeRecords",
        "matched_by",
        "查看完整回答",
        "生成完整回答",
        "generateAnswer",
        "openRecordsModal",
        "closeRecordsModal",
        "deleteRecordFromManage",
        "tasks.slice(-3)",
        "record_id",
    ):
        assert marker in script

    for selector in (
        ".modal-answer",
        ".answer-markdown",
        ".answer-open-btn",
        ".answer-hint",
        ".match-badge",
        ".modal-records",
        ".records-list",
        ".record-manage-item",
    ):
        assert selector in styles

    assert ".modal {" in styles and "overflow: hidden" in styles
    assert ".modal-body" in styles and "overflow-y: auto" in styles
    assert "showModal(mask)" in script
    assert "modalStackLevel" in script


def test_frontend_restores_rating_feedback_and_real_dashboard_stats():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
    styles = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")

    for marker in (
        'id="dash-total"',
        'id="dash-good"',
        'id="dash-ai"',
        'id="dash-by-region"',
        'id="dash-by-document"',
        'id="bar-kb-fill"',
        'id="bar-ai-val"',
    ):
        assert marker in html

    for marker in (
        "renderFeedback",
        "submitFeedback",
        "knowledge-feedback",
        'fetch(`/api/knowledge-records/${task.id}/rating`',
        "loadDashboardStats",
        "renderStatsRows",
        "setStatNumber",
        "setBar",
        'fetch("/api/knowledge-stats"',
        "这个结果对你有帮助吗？",
        "renderFeedback(record, answerContent)",
        "record-manage-preview",
    ):
        assert marker in script

    for selector in (
        ".knowledge-feedback",
        ".feedback-label",
        ".record-manage-preview",
    ):
        assert selector in styles


def test_frontend_shows_travel_plan_result_in_independent_modal():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    for marker in (
        'id="travel-mask"',
        'id="travel-title"',
        'id="travel-content"',
        "closeTravelModal",
    ):
        assert marker in html

    for marker in (
        "travelMask",
        "travelTitle",
        "travelContent",
        "travelMask.classList.add(\"show\")",
        "closeTravelModal",
        "proc-steps",
    ):
        assert marker in script


def test_document_detail_sits_above_document_list_and_scrolls_to_top():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    detail_index = html.index('id="library-detail"')
    list_index = html.index('id="library-list"')
    assert detail_index < list_index
    assert "main.scrollTo" in script


def test_knowledge_results_collapse_full_content_by_default():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
    styles = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")

    for marker in (
        "knowledge-detail-btn",
        "查看详情 ▾",
        "收起 ▴",
        "content.hidden = true",
        "knowledge-result-header",
        "knowledge-result-content",
    ):
        assert marker in script

    for selector in (
        ".knowledge-result-header",
        ".knowledge-result-meta",
        ".knowledge-result-content",
        ".knowledge-detail-btn",
    ):
        assert selector in styles


def test_scroll_is_contained_to_inner_containers_with_adaptive_height():
    styles = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")

    assert ".main {" in styles
    assert "overscroll-behavior: contain" in styles
    assert ".knowledge-results {" in styles
    assert "max-height: 62vh" in styles
    assert "overflow-y: auto" in styles
    # 应用容器必须为固定视口高度（非 min-height），否则内容会撑高整页
    app_block_start = styles.index(".app {")
    app_block_end = styles.index("}", app_block_start)
    app_block = styles[app_block_start:app_block_end]
    assert "height: 100dvh" in app_block
    assert "height: 100vh" in app_block
    assert "min-height: 100dvh" not in app_block
    # 攻略结果区在功能页内部滚动，不撑高整个页面。
    knowledge_block_start = styles.index(".knowledge-results {")
    knowledge_block_end = styles.index("}", knowledge_block_start)
    knowledge_block = styles[knowledge_block_start:knowledge_block_end]
    assert "overflow-y: auto" in knowledge_block
    assert "flex: 1" in knowledge_block


def test_sidebar_knowledge_foot_loads_real_document_stats():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    for marker in (
        'id="kb-summary"',
        'id="kb-last-index"',
    ):
        assert marker in html

    for marker in (
        "updateKnowledgeFoot",
        "formatIndexTime",
        "kb-summary",
        "kb-last-index",
        "chunk_count",
        'fetch("/api/documents")',
    ):
        assert marker in script


def test_workbench_scales_down_to_fit_viewport():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
    styles = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")

    # 当前工作台使用固定视口和功能页响应式布局，不再依赖旧首页缩放逻辑。
    assert ".shell" in styles
    assert "@media (max-width: 768px)" in styles


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


def test_frontend_adds_hotel_recommendation_view():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
    styles = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")

    for marker in (
        'id="view-hotel"',
        'id="nav-hotel"',
        "showView('hotel')",
        'id="hotel-form"',
        'id="hotel-city"',
        'id="hotel-check-in"',
        'id="hotel-check-out"',
        'id="hotel-submit"',
        'id="hotel-service-status"',
        'id="hotel-results"',
    ):
        assert marker in html

    for marker in (
        'fetch("/api/fliggy/hotels/recommend"',
        "hotelForm.addEventListener",
        "submitHotelSearch",
        "renderHotelResults",
        "buildHotelBody",
        "isHttpsUrl",
        "位置暂无匹配",
        "价格暂不可用",
        "官方详情",
    ):
        assert marker in script

    for selector in (
        ".hotel-query-card",
        ".hotel-query-fields",
        ".hotel-card",
        ".hotel-tag",
        ".hotel-detail-link",
        ".hotel-results",
    ):
        assert selector in styles


def test_frontend_hotel_cards_use_safe_dom_rendering_and_https_links():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    # 供应商字段用 textContent/createElement 渲染，不拼接 innerHTML。
    assert "detailLink.textContent = \"官方详情\"" in script
    assert "target = \"_blank\"" in script
    assert "rel = \"noopener noreferrer\"" in script
    assert 'new URL(value, window.location.href).protocol === "https:"' in script
    assert "image.addEventListener(\"error\", () => image.remove())" in script
    assert "hotel.amap_address || \"位置暂无匹配\"" in script
    assert "hotel.flyai_price == null ? \"价格暂不可用\"" in script
    # 不允许出现 http://，也不允许把空价格兜底为 0。
    assert "http://" not in script
    assert "flyai_price || 0" not in script


def test_frontend_hotel_failures_distinguish_closed_and_upstream():
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "response.status === 503" in script
    assert "response.status === 502" in script
    assert "酒店推荐服务尚未配置" in script
    assert "上游酒店查询服务暂不可用" in script


def test_frontend_hotel_does_not_promise_booking_or_inventory():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    # 酒店推荐渲染逻辑不展示可预订承诺。
    assert "可预订" not in script
    # 酒店视图区域不含库存 / 下单 / 预订字样（门票视图不在此检查范围）。
    hotel_start = html.index('id="view-hotel"')
    hotel_end = html.index("<!-- 任务结果视图 -->", hotel_start)
    hotel_html = html[hotel_start:hotel_end]
    assert "库存" not in hotel_html
    assert "预订" not in hotel_html
    assert "下单" not in hotel_html


def test_frontend_saved_plans_require_selection_before_revision_and_offer_deletion():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="selected-plan-summary"' in html
    assert 'id="plan-revision-panel"' in html
    assert 'id="plan-delete-mask"' in html
    assert 'id="plan-revision-submit"' in html
    assert "function selectSavedPlan(plan)" in script
    assert "function confirmSavedPlanDelete(plan)" in script
    assert "window.closeSavedPlanDelete = closeSavedPlanDelete;" in script
    assert "window.deleteSavedPlan = deleteSavedPlan;" in script
    assert 'method: "DELETE"' in script
    revision_block = script[script.index("async function submitPlanRevision"):script.index("function renderNav")]
    assert 'showView("task")' not in revision_block


def test_saved_plan_management_uses_flat_rows_instead_of_white_cards():
    styles = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")

    assert ".plan-management-page .saved-plan-item { background: transparent; border: 0;" in styles
    assert ".plan-management-page .plan-revision-panel { background: transparent; border: 0;" in styles
    assert "border-left: 3px solid var(--accent);" in styles
