from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.models.documents import DocumentRecord, DocumentStatus, PDF_MEDIA_TYPE
from app.services.document_store import DocumentStore
from app.services.document_processor import DocumentProcessor


class FakeChroma:
    def __init__(self):
        self.upserted = []
        self.deleted = []
        self.ready_documents = []

    def upsert(self, chunks, *, ready=False):
        self.upserted.extend(chunks)

    def mark_document_ready(self, document_id):
        self.ready_documents.append(document_id)

    def delete_document(self, document_id):
        self.deleted.append(document_id)


class FakeQwen:
    async def recognize_chart(self, image_bytes, media_type):
        return {"text": "横轴：月份；图例：客流", "degraded": False, "failure_message": None}


class FailingQwen:
    async def recognize_chart(self, image_bytes, media_type):
        return {"text": None, "degraded": True, "failure_message": "Qwen-VL 图表识别失败"}


class RaisingQwen:
    async def recognize_chart(self, image_bytes, media_type):
        raise RuntimeError("Qwen-VL 服务不可用")


class NoMinerU:
    async def submit_task(self, _url):
        raise AssertionError("没有受控公开 URL 时不应提交 MinerU")


def make_record(document_id):
    return DocumentRecord(
        id=str(document_id),
        filename="成都调研.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        status=DocumentStatus.pending,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_processor_marks_ready_only_after_chunks_are_saved_and_vectors_upserted(tmp_path, monkeypatch):
    store = DocumentStore(tmp_path)
    document_id = uuid4()
    store.create_document(make_record(document_id), b"docx")
    monkeypatch.setattr(
        "app.services.document_processor.extract_docx",
        lambda *_args: [
            {"content": "成都亲子游正文", "chunk_type": "text", "source_section": "摘要"},
            {"content": "景点 | 客流", "chunk_type": "table", "source_table": 1},
            {"content": "", "chunk_type": "chart_ocr", "source_figure": 1, "image_path": "figure-1.png", "image_bytes": b"png"},
        ],
    )
    chroma = FakeChroma()

    await DocumentProcessor(store, NoMinerU(), FakeQwen(), chroma).process(document_id)

    saved = store.get_document(document_id)
    assert saved.status is DocumentStatus.ready
    assert (saved.text_chunk_count, saved.table_chunk_count, saved.chart_ocr_chunk_count) == (1, 1, 1)
    assert len(chroma.upserted) == saved.chunk_count == 3
    assert chroma.ready_documents == [document_id]
    assert {chunk.chunk_type for chunk in store.get_chunks(document_id)} == {"text", "table", "chart_ocr"}


@pytest.mark.asyncio
async def test_processor_does_not_mark_vectors_ready_when_document_save_fails(tmp_path, monkeypatch):
    store = DocumentStore(tmp_path)
    document_id = uuid4()
    store.create_document(make_record(document_id), b"docx")
    monkeypatch.setattr("app.services.document_processor.extract_docx", lambda *_args: [{"content": "正文", "chunk_type": "text"}])
    chroma = FakeChroma()
    monkeypatch.setattr(store, "save_processed_document", lambda *_args: (_ for _ in ()).throw(RuntimeError("metadata save failed")))

    await DocumentProcessor(store, NoMinerU(), FakeQwen(), chroma).process(document_id)

    assert chroma.ready_documents == []
    assert chroma.deleted == [document_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("image_path", ["../outside.png", "/absolute.png", "C:\\private\\chart.png", "https://evil.example/chart.png"])
async def test_processor_never_reads_or_sends_chart_with_unsafe_image_path(tmp_path, monkeypatch, image_path):
    class RejectingQwen:
        async def recognize_chart(self, *_args):
            raise AssertionError("不应发送未验证图片")

    store = DocumentStore(tmp_path)
    document_id = uuid4()
    store.create_document(make_record(document_id), b"docx")
    monkeypatch.setattr(
        "app.services.document_processor.extract_docx",
        lambda *_args: [
            {"content": "正文", "chunk_type": "text"},
            {"content": "", "chunk_type": "chart_ocr", "image_path": image_path, "image_bytes": b"png"},
        ],
    )
    chroma = FakeChroma()

    await DocumentProcessor(store, NoMinerU(), RejectingQwen(), chroma).process(document_id)

    assert store.get_document(document_id).status is DocumentStatus.ready
    assert [chunk.chunk_type for chunk in chroma.upserted] == ["text"]


@pytest.mark.asyncio
async def test_pdf_processor_always_uses_local_fallback_without_external_public_url(tmp_path, monkeypatch):
    class NoExternalMinerU:
        async def submit_task(self, _url):
            raise AssertionError("v1 不应提交 MinerU")

    store = DocumentStore(tmp_path)
    document_id = uuid4()
    record = DocumentRecord(id=str(document_id), filename="成都调研.pdf", media_type=PDF_MEDIA_TYPE, status=DocumentStatus.pending, created_at=datetime.now(timezone.utc))
    store.create_document(record, b"%PDF-1.7")
    monkeypatch.setattr("app.services.document_processor.extract_pdf_with_pymupdf", lambda *_args: [{"content": "本地 PDF 正文", "chunk_type": "text", "source_page": 1}])
    chroma = FakeChroma()

    await DocumentProcessor(store, NoExternalMinerU(), FakeQwen(), chroma).process(document_id)

    assert store.get_document(document_id).status is DocumentStatus.ready
    assert chroma.upserted[0].content == "本地 PDF 正文"


@pytest.mark.asyncio
async def test_processor_keeps_text_chunks_when_chart_ocr_degrades(tmp_path, monkeypatch):
    store = DocumentStore(tmp_path)
    document_id = uuid4()
    store.create_document(make_record(document_id), b"docx")
    monkeypatch.setattr(
        "app.services.document_processor.extract_docx",
        lambda *_args: [
            {"content": "成都亲子游正文", "chunk_type": "text"},
            {"content": "", "chunk_type": "chart_ocr", "source_figure": 1, "image_path": "figure-1.png", "image_bytes": b"png"},
        ],
    )
    chroma = FakeChroma()

    await DocumentProcessor(store, NoMinerU(), FailingQwen(), chroma).process(document_id)

    saved = store.get_document(document_id)
    assert saved.status is DocumentStatus.ready
    assert saved.text_chunk_count == 1
    assert saved.chart_ocr_chunk_count == 0
    assert [chunk.chunk_type for chunk in chroma.upserted] == ["text"]


@pytest.mark.asyncio
async def test_processor_retains_processing_state_when_partial_vector_cleanup_fails_then_recovers_on_retry(tmp_path, monkeypatch):
    class PartialThenCleanupChroma:
        def __init__(self):
            self.searchable = []
            self.delete_calls = 0
            self.upsert_calls = 0

        def upsert(self, chunks, *, ready=False):
            self.upsert_calls += 1
            if self.upsert_calls == 1:
                self.searchable.append("partial-vector")
                raise RuntimeError("partial upsert")
            self.searchable.extend(chunks)

        def mark_document_ready(self, _document_id):
            return None

        def delete_document(self, _document_id):
            self.delete_calls += 1
            if self.delete_calls == 1:
                raise RuntimeError("cleanup unavailable")
            self.searchable.clear()

    store = DocumentStore(tmp_path)
    document_id = uuid4()
    store.create_document(make_record(document_id), b"docx")
    monkeypatch.setattr("app.services.document_processor.extract_docx", lambda *_args: [{"content": "正文", "chunk_type": "text"}])
    chroma = PartialThenCleanupChroma()
    processor = DocumentProcessor(store, NoMinerU(), FakeQwen(), chroma)

    await processor.process(document_id)

    assert store.get_document(document_id).status is DocumentStatus.processing
    assert store.get_processing_state(document_id) == {"task_id": "", "phase": "vector_cleanup"}
    assert chroma.searchable == ["partial-vector"]

    await processor.process(document_id)

    saved = store.get_document(document_id)
    assert saved.status is DocumentStatus.ready
    assert chroma.delete_calls == 2
    assert all(getattr(item, "content", "") != "partial-vector" for item in chroma.searchable)


@pytest.mark.asyncio
async def test_processor_normalizes_string_and_uuid_lock_keys_and_releases_lock_after_processing(tmp_path, monkeypatch):
    store = DocumentStore(tmp_path)
    document_id = uuid4()
    store.create_document(make_record(document_id), b"docx")
    monkeypatch.setattr("app.services.document_processor.extract_docx", lambda *_args: [{"content": "正文", "chunk_type": "text"}])
    processor = DocumentProcessor(store, NoMinerU(), FakeQwen(), FakeChroma())

    assert processor.document_key(str(document_id).upper()) == str(document_id)
    await processor.process(str(document_id).upper())

    assert processor._locks == {}


@pytest.mark.asyncio
async def test_processor_cleans_vectors_and_records_controlled_failure_when_chroma_fails(tmp_path, monkeypatch):
    class FailingChroma(FakeChroma):
        def upsert(self, _chunks):
            raise RuntimeError(r"C:\\private\\chroma failure")

    store = DocumentStore(tmp_path)
    document_id = uuid4()
    store.create_document(make_record(document_id), b"docx")
    monkeypatch.setattr("app.services.document_processor.extract_docx", lambda *_args: [{"content": "正文", "chunk_type": "text"}])
    chroma = FailingChroma()

    await DocumentProcessor(store, NoMinerU(), FakeQwen(), chroma).process(document_id)

    saved = store.get_document(document_id)
    assert saved.status is DocumentStatus.failed
    assert saved.failure_message == "文档内容无法处理"
    assert chroma.deleted == [document_id]
    assert r"C:\\private" not in saved.failure_message


@pytest.mark.asyncio
async def test_processor_keeps_text_and_table_chunks_when_single_chart_ocr_raises(tmp_path, monkeypatch):
    store = DocumentStore(tmp_path)
    document_id = uuid4()
    store.create_document(make_record(document_id), b"docx")
    monkeypatch.setattr(
        "app.services.document_processor.extract_docx",
        lambda *_args: [
            {"content": "成都亲子游正文", "chunk_type": "text"},
            {"content": "章节：正文\n表格 1\n表头：日期\n第 1 行：日期=第一天", "chunk_type": "table", "source_table": 1},
            {"content": "", "chunk_type": "chart_ocr", "source_figure": 1, "image_path": "figure-1.png", "image_bytes": b"png"},
        ],
    )
    chroma = FakeChroma()

    await DocumentProcessor(store, NoMinerU(), RaisingQwen(), chroma).process(document_id)

    saved = store.get_document(document_id)
    assert saved.status is DocumentStatus.ready
    assert (saved.text_chunk_count, saved.table_chunk_count, saved.chart_ocr_chunk_count) == (1, 1, 0)
    assert [chunk.chunk_type for chunk in chroma.upserted] == ["text", "table"]
