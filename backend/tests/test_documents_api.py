import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.models.documents import DocumentChunk, DocumentRecord, DocumentStatus
from app.services.document_store import DocumentStore


class FakeChroma:
    def __init__(self, hits=()):
        self.hits = hits
        self.deleted = []

    def upsert(self, _chunks):
        return None

    def query(self, query, *, document_ids=(), limit=5):
        self.last_query = (query, tuple(document_ids), limit)
        if not document_ids:
            return self.hits[:limit]
        return tuple(hit for hit in self.hits if hit.document_id in document_ids)[:limit]

    def delete_document(self, document_id):
        self.deleted.append(document_id)


class FakePolisher:
    def __init__(self, answer="完整的润色回答。" * 8):
        self.answer = answer

    async def polish(self, _query, _results):
        return self.answer


class FakeProcessor:
    def __init__(self):
        from contextlib import asynccontextmanager
        self._locks = {}
        self._asynccontextmanager = asynccontextmanager

    def lock_for(self, document_id):
        lock = self._locks.setdefault(str(document_id), asyncio.Lock())

        @self._asynccontextmanager
        async def guard():
            async with lock:
                yield

        return guard()

    async def process(self, _document_id):
        return None


def ready_document(store):
    document_id = uuid4()
    record = DocumentRecord(
        id=str(document_id), filename="成都调研.pdf", media_type="application/pdf",
        status=DocumentStatus.pending, created_at=datetime.now(timezone.utc),
    )
    store.create_document(record, b"%PDF-1.7\n")
    chunk = DocumentChunk(
        id=str(uuid4()), document_id=str(document_id), content="成都亲子游适合博物馆。",
        chunk_type="text", document_name=record.filename, source_page=2,
    )
    ready = record.model_copy(update={
        "status": DocumentStatus.ready, "updated_at": datetime.now(timezone.utc),
        "chunk_count": 1, "text_chunk_count": 1,
    })
    store.save_processed_document(ready, [chunk])
    return ready, chunk


def app_with_documents(tmp_path):
    store = DocumentStore(tmp_path)
    record, chunk = ready_document(store)
    from app.services.chroma_store import ChromaSearchHit
    chroma = FakeChroma((ChromaSearchHit(chunk_id=chunk.id, document_id=record.id, score=0.8),))
    app = create_app(settings=Settings(_env_file=None), document_store=store, document_processor=FakeProcessor(), chroma_store=chroma)
    return app, record, chunk, chroma


@pytest.mark.asyncio
async def test_document_io_routes_dispatch_store_operations_through_to_thread(tmp_path, monkeypatch):
    import app.api.documents as documents_api

    app, record, _chunk, _chroma = app_with_documents(tmp_path)
    calls = []

    async def immediate_to_thread(function, /, *args, **kwargs):
        calls.append(function.__name__)
        return function(*args, **kwargs)

    monkeypatch.setattr(documents_api.asyncio, "to_thread", immediate_to_thread)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        uploaded = await client.post(
            "/api/documents",
            files={"file": ("报告.pdf", b"%PDF-1.7\n", "application/pdf")},
        )
        listed = await client.get("/api/documents")
        detail = await client.get(f"/api/documents/{record.id}")
        chunks = await client.get(f"/api/documents/{record.id}/chunks")

    assert uploaded.status_code == 202
    assert listed.status_code == detail.status_code == chunks.status_code == 200
    assert {"create_document", "list_documents", "get_document", "get_chunks"} <= set(calls)


@pytest.mark.asyncio
async def test_upload_validates_filename_mime_and_signature_then_returns_pending_without_storage_detail(tmp_path):
    app, _record, _chunk, _chroma = app_with_documents(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        rejected = await client.post("/api/documents", files={"file": ("bad.pdf", b"not pdf", "application/pdf")})
        accepted = await client.post("/api/documents", files={"file": ("报告.pdf", b"%PDF-1.7\n", "application/pdf")})

    assert rejected.status_code == 422
    assert rejected.json() == {"detail": "文档文件内容无效"}
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "pending"
    assert "path" not in accepted.text.lower()
    assert "key" not in accepted.text.lower()


@pytest.mark.asyncio
async def test_batch_upload_starts_accepted_processors_concurrently(tmp_path):
    class BarrierProcessor:
        def __init__(self):
            self.entered = 0
            self.both_entered = asyncio.Event()

        async def process(self, _document_id):
            self.entered += 1
            if self.entered == 2:
                self.both_entered.set()
            await self.both_entered.wait()

    app, _record, _chunk, _chroma = app_with_documents(tmp_path)
    processor = BarrierProcessor()
    app.state.document_processor = processor
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await asyncio.wait_for(
            client.post(
                "/api/documents/batch",
                files=[
                    ("files", ("一.pdf", b"%PDF-1.7\n", "application/pdf")),
                    ("files", ("二.pdf", b"%PDF-1.7\n", "application/pdf")),
                ],
            ),
            timeout=0.5,
        )

    assert response.status_code == 202
    assert processor.entered == 2


@pytest.mark.asyncio
async def test_batch_upload_returns_indexed_controlled_results_and_keeps_processing_independent(tmp_path):
    app, _record, _chunk, _chroma = app_with_documents(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            "/api/documents/batch",
            files=[
                ("files", ("报告.pdf", b"%PDF-1.7\n", "application/pdf")),
                ("files", ("坏文件.pdf", b"not pdf", "application/pdf")),
                ("files", ("报告.docx", b"PK\x03\x04word", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
            ],
        )

    assert response.status_code == 202
    body = response.json()
    assert [item["index"] for item in body["items"]] == [1, 2, 3]
    assert [item["status"] for item in body["items"]] == ["accepted", "rejected", "accepted"]
    assert body["items"][1] == {"index": 2, "status": "rejected", "error": "文档文件内容无效"}
    assert "坏文件.pdf" not in response.text
    assert len(app.state.document_store.list_documents()) == 3


def test_batch_upload_declares_documented_outer_statuses():
    import app.api.documents as documents_api

    route = next(route for route in documents_api.router.routes if route.path == "/api/documents/batch")
    assert route.status_code == 202
    assert {422, 503} <= set(route.responses)


@pytest.mark.asyncio
async def test_batch_upload_continues_after_file_read_exception(tmp_path, monkeypatch):
    import app.api.documents as documents_api

    app, _record, _chunk, _chroma = app_with_documents(tmp_path)
    original = documents_api._read_and_validate_upload
    calls = 0

    async def read_with_second_file_failure(file, max_upload_bytes):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("private upload stream failure")
        return await original(file, max_upload_bytes)

    monkeypatch.setattr(documents_api, "_read_and_validate_upload", read_with_second_file_failure)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            "/api/documents/batch",
            files=[
                ("files", ("一.pdf", b"%PDF-1.7\n", "application/pdf")),
                ("files", ("二.pdf", b"%PDF-1.7\n", "application/pdf")),
                ("files", ("三.pdf", b"%PDF-1.7\n", "application/pdf")),
            ],
        )

    assert response.status_code == 202
    assert response.json()["items"][1] == {
        "index": 2, "status": "unavailable", "error": "文档上传服务暂不可用"
    }
    assert response.json()["items"][2]["status"] == "accepted"
    assert "private" not in response.text


@pytest.mark.asyncio
async def test_batch_upload_uses_request_level_errors_and_controlled_unavailability(tmp_path):
    app, _record, _chunk, _chroma = app_with_documents(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        missing_files = await client.post("/api/documents/batch")
        empty_multipart = await client.post(
            "/api/documents/batch",
            content=b"--empty-boundary--\r\n",
            headers={"Content-Type": "multipart/form-data; boundary=empty-boundary"},
        )
        overflow = await client.post(
            "/api/documents/batch",
            files=[
                ("files", (f"{index}.pdf", b"%PDF-1.7\n", "application/pdf"))
                for index in range(11)
            ],
        )
        app.state.document_processor = None
        unavailable = await client.post(
            "/api/documents/batch",
            files={"files": ("报告.pdf", b"%PDF-1.7\n", "application/pdf")},
        )

    assert missing_files.status_code == empty_multipart.status_code == overflow.status_code == 422
    assert missing_files.json() == empty_multipart.json() == {"detail": "请至少上传一份文档"}
    assert unavailable.status_code == 503
    assert unavailable.json() == {
        "items": [{"index": 1, "status": "unavailable", "error": "文档处理服务暂不可用"}]
    }


@pytest.mark.asyncio
async def test_list_detail_chunks_and_search_return_document_store_content_only(tmp_path):
    app, record, chunk, _chroma = app_with_documents(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        listed = await client.get("/api/documents")
        detail = await client.get(f"/api/documents/{record.id}")
        chunks = await client.get(f"/api/documents/{record.id}/chunks")
        searched = await client.post("/api/knowledge-search", json={"query": "成都亲子游", "document_ids": []})

    assert listed.status_code == detail.status_code == chunks.status_code == searched.status_code == 200
    assert detail.json()["id"] == str(record.id)
    assert chunks.json()[0]["content"] == chunk.content
    result = searched.json()["results"][0]
    assert result == {"content": chunk.content, "chunk_type": "text", "score": 0.8, "source": {"document_name": "成都调研.pdf", "page": 2, "section": None, "table": None, "figure": None}, "matched_by": "both"}
    assert "raw_payload" not in searched.text


@pytest.mark.asyncio
async def test_knowledge_search_reads_document_store_once_for_multiple_hits(tmp_path, monkeypatch):
    app, record, chunk, _chroma = app_with_documents(tmp_path)
    from app.services.chroma_store import ChromaSearchHit
    second_chunk = DocumentChunk(id=str(uuid4()), document_id=str(record.id), content="第二段正文", chunk_type="text", document_name=record.filename, source_page=3)
    ready = app.state.document_store.get_document(record.id).model_copy(update={"chunk_count": 2, "text_chunk_count": 2})
    app.state.document_store.save_processed_document(ready, [chunk, second_chunk])
    app.state.chroma_store.hits = (
        ChromaSearchHit(chunk_id=chunk.id, document_id=record.id, score=0.1),
        ChromaSearchHit(chunk_id=second_chunk.id, document_id=record.id, score=0.2),
    )
    calls = 0
    original = app.state.document_store.get_documents_with_chunks

    def counted(document_ids):
        nonlocal calls
        calls += 1
        return original(document_ids)

    monkeypatch.setattr(app.state.document_store, "get_documents_with_chunks", counted)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/knowledge-search", json={"query": "正文", "document_ids": []})

    assert response.status_code == 200
    assert len(response.json()["results"]) == 2
    assert calls == 1


@pytest.mark.asyncio
async def test_knowledge_search_hides_controlled_chroma_failures(tmp_path):
    class FailingChroma(FakeChroma):
        def query(self, *_args, **_kwargs):
            raise RuntimeError(r"C:\\private\\chroma failure")

    app, _record, _chunk, _chroma = app_with_documents(tmp_path)
    app.state.chroma_store = FailingChroma()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/knowledge-search", json={"query": "成都", "document_ids": []})

    assert response.status_code == 503
    assert response.json() == {"detail": "知识检索服务暂不可用"}
    assert "private" not in response.text


@pytest.mark.asyncio
async def test_knowledge_search_excludes_processing_document_even_when_chroma_returns_stale_hit(tmp_path):
    app, record, _chunk, _chroma = app_with_documents(tmp_path)
    processing = app.state.document_store.get_document(record.id).model_copy(
        update={"status": DocumentStatus.processing, "chunk_count": 0, "text_chunk_count": 0, "table_chunk_count": 0, "chart_ocr_chunk_count": 0}
    )
    with app.state.document_store._lock:
        state = app.state.document_store._read_state()
        index = app.state.document_store._find_document_index(state, record.id)
        state["documents"][index] = processing.model_dump(mode="json")
        app.state.document_store._write_state(state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/knowledge-search", json={"query": "成都", "document_ids": []})

    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.asyncio
async def test_document_api_exposes_controlled_vector_cleanup_processing_summary(tmp_path):
    app, record, _chunk, _chroma = app_with_documents(tmp_path)
    app.state.document_store.mark_processing(record.id)
    app.state.document_store.mark_vector_cleanup_required(record.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.get(f"/api/documents/{record.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "processing"
    assert response.json()["processing_message"] == "向量清理待重试"
    assert "path" not in response.text.lower()


@pytest.mark.asyncio
async def test_delete_waits_for_the_same_document_processor_lock_before_removing_document(tmp_path):
    import asyncio

    app, record, _chunk, chroma = app_with_documents(tmp_path)
    lock = app.state.document_processor.lock_for(record.id)
    async with lock:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
            delete_task = asyncio.create_task(client.delete(f"/api/documents/{record.id}"))
            await asyncio.sleep(0)
            assert not delete_task.done()
            assert app.state.document_store.get_document(record.id).status is DocumentStatus.ready
    response = await delete_task

    assert response.status_code == 204
    assert chroma.deleted == [UUID(str(record.id))]


@pytest.mark.asyncio
async def test_delete_cascades_chroma_and_hides_missing_document_details(tmp_path):
    app, record, _chunk, chroma = app_with_documents(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        deleted = await client.delete(f"/api/documents/{record.id}")
        missing = await client.get(f"/api/documents/{record.id}")

    assert deleted.status_code == 204
    assert chroma.deleted == [UUID(str(record.id))]
    assert missing.status_code == 404
    assert "uploads" not in missing.text


def ready_sanya_document(store):
    document_id = uuid4()
    record = DocumentRecord(
        id=str(document_id), filename="三亚玩法.pdf", media_type="application/pdf",
        status=DocumentStatus.pending, created_at=datetime.now(timezone.utc),
    )
    store.create_document(record, b"%PDF-1.7\n")
    chunk = DocumentChunk(
        id=str(uuid4()), document_id=str(document_id), content="三亚海鲜烧烤美食推荐",
        chunk_type="text", document_name=record.filename, source_page=1,
    )
    ready = record.model_copy(update={
        "status": DocumentStatus.ready, "updated_at": datetime.now(timezone.utc),
        "chunk_count": 1, "text_chunk_count": 1,
    })
    store.save_processed_document(ready, [chunk])
    return ready, chunk


@pytest.mark.asyncio
async def test_knowledge_search_hybrid_filters_other_city_results(tmp_path):
    from app.services.chroma_store import ChromaSearchHit

    app, record, chunk, chroma = app_with_documents(tmp_path)
    sanya_record, sanya_chunk = ready_sanya_document(app.state.document_store)
    chroma.hits = (
        ChromaSearchHit(chunk_id=chunk.id, document_id=record.id, score=0.9),
        ChromaSearchHit(chunk_id=sanya_chunk.id, document_id=sanya_record.id, score=0.8),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/knowledge-search", json={"query": "成都美食推荐", "document_ids": []})

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["source"]["document_name"] == "成都调研.pdf"
    assert results[0]["matched_by"] == "semantic"


@pytest.mark.asyncio
async def test_knowledge_search_marks_answer_unavailable_without_deepseek_key(tmp_path):
    app, _record, _chunk, _chroma = app_with_documents(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            "/api/knowledge-search",
            json={"query": "成都美食推荐", "document_ids": [], "generate_markdown": True},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] is None
    assert body["answer_status"] == "unavailable"
    assert body["results"]


@pytest.mark.asyncio
async def test_knowledge_search_returns_record_id_and_generation_updates_same_record(tmp_path):
    app, _record, _chunk, _chroma = app_with_documents(tmp_path)
    app.state.knowledge_polisher = FakePolisher()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        search = await client.post("/api/knowledge-search", json={"query": "成都亲子游", "document_ids": []})
        search_body = search.json()
        record_id = search_body["record_id"]

        assert search.status_code == 200
        assert search_body["answer_status"] == "none"
        assert record_id

        generation = await client.post(
            "/api/knowledge-search",
            json={"query": "成都亲子游", "document_ids": [], "generate_markdown": True, "record_id": record_id},
        )
        generation_body = generation.json()

        assert generation.status_code == 200
        assert generation_body["record_id"] == record_id
        assert generation_body["answer_status"] == "generated"

        listed = await client.get("/api/knowledge-records")

    records = listed.json()
    assert len(records) == 1
    assert records[0]["id"] == record_id
    assert records[0]["answer_status"] == "generated"


@pytest.mark.asyncio
async def test_knowledge_search_without_results_returns_no_record_id(tmp_path):
    app, _record, chunk, chroma = app_with_documents(tmp_path)
    processing = app.state.document_store.get_document(_record.id).model_copy(
        update={"status": DocumentStatus.processing, "chunk_count": 0, "text_chunk_count": 0, "table_chunk_count": 0, "chart_ocr_chunk_count": 0}
    )
    with app.state.document_store._lock:
        state = app.state.document_store._read_state()
        index = app.state.document_store._find_document_index(state, _record.id)
        state["documents"][index] = processing.model_dump(mode="json")
        app.state.document_store._write_state(state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/knowledge-search", json={"query": "成都", "document_ids": []})

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["record_id"] is None


@pytest.mark.asyncio
async def test_knowledge_rating_and_stats_reflect_votes(tmp_path):
    app, _record, _chunk, _chroma = app_with_documents(tmp_path)
    app.state.knowledge_polisher = FakePolisher()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        search = await client.post("/api/knowledge-search", json={"query": "成都亲子游", "document_ids": [], "generate_markdown": True})
        record_id = search.json()["record_id"]

        rated = await client.post(f"/api/knowledge-records/{record_id}/rating", json={"rating": "like"})
        stats = await client.get("/api/knowledge-stats")

    assert rated.status_code == 200
    body = stats.json()
    assert body["total_feedback"] == 1
    assert body["like_count"] == 1
    assert body["dislike_count"] == 0
    assert body["good_rate"] == 1.0
    assert body["by_document"][0]["name"] == "成都调研.pdf"
    assert body["by_document"][0]["like"] == 1
    assert body["by_region"][0]["name"] == "四川"


@pytest.mark.asyncio
async def test_knowledge_rating_rejects_invalid_rating(tmp_path):
    app, _record, _chunk, _chroma = app_with_documents(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        search = await client.post("/api/knowledge-search", json={"query": "成都亲子游", "document_ids": []})
        record_id = search.json()["record_id"]
        invalid = await client.post(f"/api/knowledge-records/{record_id}/rating", json={"rating": "neutral"})
        missing = await client.post("/api/knowledge-records/00000000-0000-0000-0000-000000000000/rating", json={"rating": "like"})

    assert invalid.status_code == 422
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_knowledge_stats_deduplicate_documents_per_record(tmp_path):
    from app.services.chroma_store import ChromaSearchHit

    app, record, chunk, chroma = app_with_documents(tmp_path)
    app.state.knowledge_polisher = FakePolisher()
    second_chunk = DocumentChunk(
        id=str(uuid4()), document_id=str(record.id), content="第二段正文",
        chunk_type="text", document_name=record.filename, source_page=3,
    )
    ready = app.state.document_store.get_document(record.id).model_copy(
        update={"chunk_count": 2, "text_chunk_count": 2}
    )
    app.state.document_store.save_processed_document(ready, [chunk, second_chunk])
    chroma.hits = (
        ChromaSearchHit(chunk_id=chunk.id, document_id=record.id, score=0.9),
        ChromaSearchHit(chunk_id=second_chunk.id, document_id=record.id, score=0.8),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        search = await client.post("/api/knowledge-search", json={"query": "成都亲子游", "document_ids": [], "generate_markdown": True})
        record_id = search.json()["record_id"]
        assert len(search.json()["results"]) == 2
        await client.post(f"/api/knowledge-records/{record_id}/rating", json={"rating": "like"})
        stats = await client.get("/api/knowledge-stats")

    body = stats.json()
    assert body["total_feedback"] == 1
    assert body["like_count"] == 1
    assert body["by_document"][0]["name"] == "成都调研.pdf"
    assert body["by_document"][0]["like"] == 1


@pytest.mark.asyncio
async def test_knowledge_stats_empty_when_no_votes(tmp_path):
    app, _record, _chunk, _chroma = app_with_documents(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        stats = await client.get("/api/knowledge-stats")

    body = stats.json()
    assert body["total_feedback"] == 0
    assert body["like_count"] == 0
    assert body["good_rate"] == 0.0
    assert body["by_document"] == []
    assert body["by_region"] == []


@pytest.mark.asyncio
async def test_knowledge_records_are_listed_deleted_and_cleared(tmp_path):
    app, _record, _chunk, _chroma = app_with_documents(tmp_path)
    app.state.knowledge_polisher = FakePolisher()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        search = await client.post("/api/knowledge-search", json={"query": "成都亲子游", "document_ids": [], "generate_markdown": True})
        listed = await client.get("/api/knowledge-records")

    assert search.status_code == 200
    records = listed.json()
    assert len(records) == 1
    assert records[0]["query"] == "成都亲子游"
    assert records[0]["answer_status"] == "generated"

    record_id = records[0]["id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        deleted = await client.delete(f"/api/knowledge-records/{record_id}")
        after_delete = await client.get("/api/knowledge-records")
        missing = await client.delete(f"/api/knowledge-records/{record_id}")

    assert deleted.status_code == 204
    assert after_delete.json() == []
    assert missing.status_code == 404

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        await client.post("/api/knowledge-search", json={"query": "三亚亲子游", "document_ids": [], "generate_markdown": True})
        cleared = await client.delete("/api/knowledge-records")
        after_clear = await client.get("/api/knowledge-records")

    assert cleared.status_code == 204
    assert after_clear.json() == []


@pytest.mark.asyncio
async def test_knowledge_search_fetches_three_times_the_configured_limit_and_returns_it(tmp_path):
    """候选池必须大于最终结果数，融合排序才有取舍空间。"""
    from app.services.chroma_store import ChromaSearchHit

    app, record, chunk, chroma = app_with_documents(tmp_path)
    store = app.state.document_store
    extra = [
        DocumentChunk(
            id=str(uuid4()), document_id=str(record.id), content=f"成都亲子游第 {index} 段正文",
            chunk_type="text", document_name=record.filename, source_page=index,
        )
        for index in range(1, 15)
    ]
    all_chunks = [chunk, *extra]
    ready = store.get_document(record.id).model_copy(
        update={"chunk_count": len(all_chunks), "text_chunk_count": len(all_chunks)}
    )
    store.save_processed_document(ready, all_chunks)
    chroma.hits = tuple(
        ChromaSearchHit(chunk_id=item.id, document_id=record.id, score=0.9 - index * 0.01)
        for index, item in enumerate(all_chunks)
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/knowledge-search", json={"query": "成都亲子游", "document_ids": []})

    limit = app.state.settings.knowledge_search_result_limit
    assert chroma.last_query[2] == limit * 3
    assert len(response.json()["results"]) == limit == 12


@pytest.mark.asyncio
async def test_knowledge_search_scopes_keyword_route_to_requested_documents(tmp_path, monkeypatch):
    """关键词路不传文档范围会让被排除的文档重新进入结果，破坏用户选择的检索边界。"""
    import app.api.documents as documents_api

    app, record, _chunk, chroma = app_with_documents(tmp_path)
    other_record, _other_chunk = ready_sanya_document(app.state.document_store)
    captured = {}
    original = documents_api.search_chunks

    def capture(chunks, parsed, *, document_ids=(), limit=5):
        captured["document_ids"] = tuple(document_ids)
        captured["limit"] = limit
        return original(chunks, parsed, document_ids=document_ids, limit=limit)

    monkeypatch.setattr(documents_api, "search_chunks", capture)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            "/api/knowledge-search",
            json={"query": "美食", "document_ids": [str(record.id)]},
        )

    assert captured["document_ids"] == (record.id,)
    assert captured["limit"] == app.state.settings.knowledge_search_result_limit * 3
    assert all(
        result["source"]["document_name"] != other_record.filename
        for result in response.json()["results"]
    )


@pytest.mark.asyncio
async def test_knowledge_search_rejects_whitespace_only_query_before_calling_backends(tmp_path):
    """纯空白查询无法命中任何内容，必须在调用检索后端前拒绝。"""
    app, _record, _chunk, chroma = app_with_documents(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/knowledge-search", json={"query": "   ", "document_ids": []})

    assert response.status_code == 422
    assert not hasattr(chroma, "last_query")


@pytest.mark.asyncio
async def test_knowledge_search_records_and_returns_the_normalized_query(tmp_path):
    """记录与响应必须与真正检索的内容一致，否则复盘会误判召回质量。"""
    app, _record, _chunk, _chroma = app_with_documents(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            "/api/knowledge-search",
            json={"query": "  成都亲子游  ", "document_ids": []},
        )

    assert response.json()["query"] == "成都亲子游"


@pytest.mark.asyncio
async def test_knowledge_search_deduplicates_whitespace_equivalent_chunks(tmp_path):
    from app.services.chroma_store import ChromaSearchHit

    app, record, chunk, chroma = app_with_documents(tmp_path)
    primary = chunk.model_copy(update={"content": "成都 亲子游 攻略"})
    duplicate = chunk.model_copy(update={"id": str(uuid4()), "content": "成都\n亲子游  攻略"})
    distinct = chunk.model_copy(
        update={"id": str(uuid4()), "content": "成都室内亲子场所攻略", "source_page": 3}
    )
    ready = app.state.document_store.get_document(record.id).model_copy(
        update={"chunk_count": 3, "text_chunk_count": 3}
    )
    app.state.document_store.save_processed_document(ready, [primary, duplicate, distinct])
    chroma.hits = tuple(
        ChromaSearchHit(chunk_id=item.id, document_id=record.id, score=0.9 - index * 0.1)
        for index, item in enumerate([primary, duplicate, distinct])
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/knowledge-search", json={"query": "成都亲子游", "document_ids": []})

    assert response.status_code == 200
    assert [item["content"] for item in response.json()["results"]] == [
        "成都 亲子游 攻略",
        "成都室内亲子场所攻略",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("三亚亲子游", "no_region_documents"),
        ("成都夜游", "no_matching_chunks"),
    ],
)
async def test_knowledge_search_returns_controlled_empty_reason_for_ready_documents(
    tmp_path, query, reason
):
    app, _record, _chunk, chroma = app_with_documents(tmp_path)
    chroma.hits = ()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/knowledge-search", json={"query": query, "document_ids": []})

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["empty_reason"] == reason


@pytest.mark.asyncio
async def test_knowledge_search_returns_no_ready_documents_reason(tmp_path):
    app = create_app(
        settings=Settings(_env_file=None),
        document_store=DocumentStore(tmp_path),
        document_processor=FakeProcessor(),
        chroma_store=FakeChroma(),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/knowledge-search", json={"query": "成都亲子游", "document_ids": []})

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["empty_reason"] == "no_ready_documents"
