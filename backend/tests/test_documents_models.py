from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models.documents import (
    DocumentChunk,
    DocumentRecord,
    DocumentStatus,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    SourceLocation,
)


PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCUMENT_ID = "5f6bb8f6-0b24-4630-9f43-8a9a0d1c410d"
CHUNK_ID = "f4e14ce5-11c1-4c42-bbdf-83edcd8fd739"


def document_record_payload(**overrides):
    payload = {
        "id": DOCUMENT_ID,
        "filename": "成都调研.pdf",
        "media_type": PDF,
        "status": DocumentStatus.pending,
        "created_at": "2026-08-22T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def test_document_record_accepts_supported_statuses_and_controls_failure_message():
    record = DocumentRecord(
        id=DOCUMENT_ID,
        filename="成都调研.pdf",
        media_type=PDF,
        status=DocumentStatus.pending,
        created_at="2026-08-22T00:00:00Z",
    )
    assert record.status is DocumentStatus.pending
    assert record.failure_message is None

    failed = DocumentRecord(
        id=DOCUMENT_ID,
        filename="成都调研.pdf",
        media_type=PDF,
        status=DocumentStatus.failed,
        created_at=datetime(2026, 8, 22),
        failure_message="解析服务暂不可用",
    )
    assert failed.failure_message == "解析服务暂不可用"

    with pytest.raises(ValidationError):
        DocumentRecord(
            id=DOCUMENT_ID,
            filename="成都调研.pdf",
            media_type=PDF,
            status=DocumentStatus.ready,
            created_at=datetime(2026, 8, 22),
            failure_message="内部异常堆栈",
        )


def test_document_record_rejects_illegal_mime():
    with pytest.raises(ValidationError):
        DocumentRecord(
            id=DOCUMENT_ID,
            filename="成都调研.exe",
            media_type="application/x-msdownload",
            status=DocumentStatus.ready,
            created_at="2026-08-22T00:00:00Z",
        )


@pytest.mark.parametrize("filename", ["evil.exe", "dir/report.pdf", r"dir\\report.pdf"])
def test_document_record_rejects_unsafe_filenames(filename):
    with pytest.raises(ValidationError):
        DocumentRecord(**document_record_payload(filename=filename))


def test_document_record_requires_filename_suffix_to_match_mime():
    with pytest.raises(ValidationError):
        DocumentRecord(**document_record_payload(filename="evil.exe", media_type=PDF))

    with pytest.raises(ValidationError):
        DocumentRecord(
            **document_record_payload(
                filename="报告.pdf",
                media_type=DOCX,
            )
        )


def test_document_record_rejects_sensitive_or_path_like_failure_messages():
    for message in [
        "Traceback (most recent call last)",
        "Authorization: Bearer secret",
        "Bearer secret",
        "api_key=secret",
        "token=secret",
        "password=secret",
        "secret=secret",
        "{\"raw_response\": \"upstream\"}",
        "backend/data/documents.json",
        "uploads/report.pdf",
        "extracted/figure.png",
        "chroma/index",
        "documents.json",
        r"C:\\private\\document.pdf",
        "C:/private/document.pdf",
        "file:/private/document.pdf",
        "file://private/document.pdf",
        "http://localhost:8000/internal",
        "https://internal.service.local/error",
        "/var/lib/app/document.pdf",
    ]:
        with pytest.raises(ValidationError):
            DocumentRecord(**document_record_payload(status=DocumentStatus.failed, failure_message=message))

    record = DocumentRecord(
        **document_record_payload(status=DocumentStatus.failed, failure_message="解析服务暂不可用")
    )
    assert record.failure_message == "解析服务暂不可用"


def test_document_record_enforces_status_statistics_invariants():
    with pytest.raises(ValidationError):
        DocumentRecord(**document_record_payload(status=DocumentStatus.ready))

    with pytest.raises(ValidationError):
        DocumentRecord(
            **document_record_payload(
                status=DocumentStatus.ready,
                chunk_count=2,
                text_chunk_count=1,
                table_chunk_count=0,
                chart_ocr_chunk_count=0,
            )
        )

    with pytest.raises(ValidationError):
        DocumentRecord(
            **document_record_payload(status=DocumentStatus.pending, chunk_count=1)
        )

    with pytest.raises(ValidationError):
        DocumentRecord(
            **document_record_payload(
                status=DocumentStatus.failed,
                failure_message="解析失败",
                text_chunk_count=1,
            )
        )

    ready = DocumentRecord(
        **document_record_payload(
            status=DocumentStatus.ready,
            chunk_count=3,
            text_chunk_count=1,
            table_chunk_count=1,
            chart_ocr_chunk_count=1,
        )
    )
    assert ready.chunk_count == 3


@pytest.mark.parametrize("status", list(DocumentStatus))
def test_document_record_accepts_all_document_statuses(status):
    record = DocumentRecord(
        id=DOCUMENT_ID,
        filename="报告.docx",
        media_type=DOCX,
        status=status,
        created_at="2026-08-22T00:00:00Z",
        failure_message="处理失败" if status is DocumentStatus.failed else None,
        chunk_count=1 if status is DocumentStatus.ready else 0,
        text_chunk_count=1 if status is DocumentStatus.ready else 0,
    )
    assert record.status is status


def test_document_chunk_accepts_content_up_to_800_characters():
    chunk = DocumentChunk(
        id=CHUNK_ID,
        document_id=DOCUMENT_ID,
        content="x" * 800,
        chunk_type="text",
        document_name="成都调研.docx",
    )
    assert len(chunk.content) == 800


def test_document_chunk_rejects_content_over_800_characters():
    with pytest.raises(ValidationError):
        DocumentChunk(
            id=CHUNK_ID,
            document_id=DOCUMENT_ID,
            content="x" * 801,
            chunk_type="text",
            document_name="成都调研.docx",
        )


@pytest.mark.parametrize(
    "image_path",
    [
        "/var/lib/app/figure.png",
        r"C:\\images\\figure.png",
        "../figure.png",
        "images/../figure.png",
        "file://images/figure.png",
        "file:/images/figure.png",
        "https://example.com/figure.png",
        "C:/images/figure.png",
        "C:images/figure.png",
        r"..\figure.png",
        r"images\..\figure.png",
        r"images\figure.png",
        "",
        "images/figure\n.png",
    ],
)
def test_document_chunk_rejects_unsafe_image_paths(image_path):
    with pytest.raises(ValidationError):
        DocumentChunk(
            id=CHUNK_ID,
            document_id=DOCUMENT_ID,
            content="图表 OCR",
            chunk_type="chart_ocr",
            document_name="报告.docx",
            image_path=image_path,
        )


def test_document_chunk_accepts_relative_image_path():
    chunk = DocumentChunk(
        id=CHUNK_ID,
        document_id=DOCUMENT_ID,
        content="图表 OCR",
        chunk_type="chart_ocr",
        document_name="报告.docx",
        image_path="images/figure-1.png",
    )
    assert chunk.image_path == "images/figure-1.png"


def test_document_chunk_rejects_char_end_before_char_start():
    with pytest.raises(ValidationError):
        DocumentChunk(
            id=CHUNK_ID,
            document_id=DOCUMENT_ID,
            content="文本",
            chunk_type="text",
            document_name="报告.docx",
            char_start=10,
            char_end=9,
        )


def test_source_location_is_whitelisted_and_result_does_not_duplicate_chunk_content():
    source = SourceLocation(document_name="报告.docx", page=3, section="亲子资源", table=2)
    assert source.page == 3
    with pytest.raises(ValidationError):
        SourceLocation(document_name="报告.docx", path="/private/report.docx")


def test_document_chunk_limits_to_known_types_and_safe_metadata():
    chunk = DocumentChunk(
        id=CHUNK_ID,
        document_id=DOCUMENT_ID,
        content="表 3：成都亲子游资源",
        chunk_type="table",
        document_name="成都调研.docx",
        source_table=3,
    )
    assert chunk.chunk_type == "table"

    with pytest.raises(ValidationError):
        DocumentChunk(
            id=CHUNK_ID,
            document_id=DOCUMENT_ID,
            content="x",
            chunk_type="raw_supplier_payload",
            document_name="报告.docx",
        )

    with pytest.raises(ValidationError):
        DocumentChunk(
            id=CHUNK_ID,
            document_id=DOCUMENT_ID,
            content="x",
            chunk_type="text",
            document_name="报告.docx",
            raw_response="secret",
        )


def test_document_chunk_accepts_unicode_content_up_to_800_characters():
    chunk = DocumentChunk(
        id=CHUNK_ID,
        document_id=DOCUMENT_ID,
        content="中" * 800,
        chunk_type="text",
        document_name="报告.docx",
    )
    assert len(chunk.content) == 800


def test_knowledge_search_defaults_to_global_library_and_response_is_typed():
    request = KnowledgeSearchRequest(query="成都室内亲子场所")
    assert request.document_ids == ()

    response = KnowledgeSearchResponse(query=request.query, results=[])
    assert response.results == ()


def test_batch_upload_item_only_allows_controlled_status_and_payload_shape():
    from app.models.documents import DocumentBatchUploadItem

    accepted = DocumentBatchUploadItem(
        index=1,
        status="accepted",
        document=DocumentRecord(**document_record_payload()),
    )
    assert accepted.index == 1

    rejected = DocumentBatchUploadItem(
        index=2,
        status="rejected",
        error="文档文件内容无效",
    )
    assert rejected.error == "文档文件内容无效"

    with pytest.raises(ValidationError):
        DocumentBatchUploadItem(index=0, status="rejected", error="C:/private/report.pdf")
    with pytest.raises(ValidationError):
        DocumentBatchUploadItem(index=1, status="rejected", error="坏文件.pdf")
    with pytest.raises(ValidationError):
        DocumentBatchUploadItem(index=1, status="accepted", error="文档文件内容无效")
    with pytest.raises(ValidationError):
        DocumentBatchUploadItem(index=1, status="rejected", document=DocumentRecord(**document_record_payload()))
