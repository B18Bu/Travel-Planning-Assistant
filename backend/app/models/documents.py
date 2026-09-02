from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.models.travel import NonEmptyText, StrictModel, UUIDV1ToV5


PDF_MEDIA_TYPE = "application/pdf"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DocumentMediaType = Literal[PDF_MEDIA_TYPE, DOCX_MEDIA_TYPE]
# 文本块长度上限按 Unicode 字符数计算，而非字节数。
CHUNK_CONTENT_MAX_LENGTH = 800
ChunkContent = Annotated[str, Field(min_length=1, max_length=CHUNK_CONTENT_MAX_LENGTH)]
# 大模型润色后的完整 Markdown 回答长度上限。
AnswerText = Annotated[str, Field(min_length=1, max_length=40000)]


_FAILURE_MESSAGE_FORBIDDEN_PATTERNS = (
    "traceback",
    "authorization",
    "bearer",
    "api_key",
    "token=",
    "password",
    "secret",
    "raw_response",
    "raw_payload",
    "backend/",
    "uploads/",
    "extracted/",
    "chroma/",
    "documents.json",
)


def _validate_failure_message(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.lower()
    if any(pattern in normalized for pattern in _FAILURE_MESSAGE_FORBIDDEN_PATTERNS):
        raise ValueError("失败摘要包含敏感信息")
    if len(value) >= 3 and value[1] == ":" and value[2] in "/\\":
        raise ValueError("失败摘要不得包含绝对路径")
    if (
        value.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:[\\/]", value)
        or value.lower().startswith("file:")
        or "://" in value
    ):
        raise ValueError("失败摘要不得包含绝对路径或内部 URL")
    return value


def _validate_image_path(value: str | None) -> str | None:
    if value is None:
        return None
    windows_path = PureWindowsPath(value)
    if (
        not value
        or "\\" in value
        or windows_path.drive
        or windows_path.is_absolute()
        or PurePosixPath(value).is_absolute()
        or any(part == ".." for part in value.split("/"))
        or any(ord(character) < 32 for character in value)
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)
        or "://" in value
    ):
        raise ValueError("图片路径必须是相对预览路径")
    return value


class DocumentStatus(StrEnum):
    """文档处理状态。"""

    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class DocumentRecord(StrictModel):
    """文档元数据合同。"""

    id: UUIDV1ToV5
    filename: NonEmptyText
    media_type: DocumentMediaType
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime | None = None
    failure_message: NonEmptyText | None = None
    processing_message: NonEmptyText | None = None
    chunk_count: int = Field(default=0, ge=0)
    text_chunk_count: int = Field(default=0, ge=0)
    table_chunk_count: int = Field(default=0, ge=0)
    chart_ocr_chunk_count: int = Field(default=0, ge=0)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("文件名必须是安全基名")
        return value

    @model_validator(mode="after")
    def validate_document_contract(self) -> "DocumentRecord":
        """校验文件类型、失败摘要和状态统计合同。"""

        suffix = self.filename.rsplit(".", 1)[-1].lower() if "." in self.filename else ""
        expected_suffix = "pdf" if self.media_type == PDF_MEDIA_TYPE else "docx"
        if suffix != expected_suffix:
            raise ValueError("文件名后缀必须与 MIME 类型匹配")

        _validate_failure_message(self.failure_message)
        if self.status is DocumentStatus.failed and self.failure_message is None:
            raise ValueError("failed 文档必须包含失败摘要")
        if self.status is not DocumentStatus.failed and self.failure_message is not None:
            raise ValueError("非 failed 文档不得包含失败摘要")
        if self.status is not DocumentStatus.processing and self.processing_message is not None:
            raise ValueError("非 processing 文档不得包含处理摘要")
        if self.processing_message is not None:
            _validate_failure_message(self.processing_message)

        counts = (
            self.text_chunk_count,
            self.table_chunk_count,
            self.chart_ocr_chunk_count,
        )
        if self.status is DocumentStatus.ready:
            if self.chunk_count <= 0 or self.chunk_count != sum(counts):
                raise ValueError("ready 文档的块统计必须为正数且总数一致")
        elif self.chunk_count != 0 or any(counts):
            raise ValueError("未完成或失败文档的块统计必须为零")
        return self


class DocumentBatchUploadItem(StrictModel):
    """单个批量上传结果；仅包含受控状态、文档记录或错误摘要。"""

    index: int = Field(ge=1)
    status: Literal["accepted", "rejected", "unavailable"]
    document: DocumentRecord | None = None
    error: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_batch_item_contract(self) -> "DocumentBatchUploadItem":
        if self.status == "accepted":
            if self.document is None or self.error is not None:
                raise ValueError("accepted 项必须且只能包含文档记录")
        elif self.document is not None or self.error is None:
            raise ValueError("非 accepted 项必须且只能包含错误摘要")
        if self.error is not None:
            _validate_failure_message(self.error)
            if ".pdf" in self.error.lower() or ".docx" in self.error.lower():
                raise ValueError("批量上传错误摘要不得包含文件名")
        return self


class DocumentBatchUploadResponse(StrictModel):
    """批量上传的顺序结果。"""

    items: tuple[DocumentBatchUploadItem, ...] = Field(min_length=1)


class DocumentChunk(StrictModel):
    """可检索的文档内容块合同。"""

    id: UUIDV1ToV5
    document_id: UUIDV1ToV5
    content: ChunkContent
    chunk_type: Literal["text", "table", "chart_ocr"]
    document_name: NonEmptyText
    source_page: int | None = Field(default=None, ge=1)
    source_section: NonEmptyText | None = None
    source_table: int | None = Field(default=None, ge=1)
    source_figure: int | None = Field(default=None, ge=1)
    image_path: str | None = None
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_character_range(self) -> "DocumentChunk":
        if self.char_start is not None and self.char_end is not None and self.char_end < self.char_start:
            raise ValueError("char_end 不得小于 char_start")
        return self

    @field_validator("image_path")
    @classmethod
    def validate_image_path(cls, value: str | None) -> str | None:
        return _validate_image_path(value)


class KnowledgeSearchRequest(StrictModel):
    """知识库检索请求；空文档列表代表全库。record_id 用于将润色结果更新到已有记录。"""

    query: NonEmptyText
    document_ids: tuple[UUIDV1ToV5, ...] = Field(default=(), max_length=20)
    generate_markdown: bool = False
    record_id: UUIDV1ToV5 | None = None


class SourceLocation(StrictModel):
    """知识库结果的受控来源定位。"""

    document_name: NonEmptyText
    page: int | None = Field(default=None, ge=1)
    section: NonEmptyText | None = None
    table: int | None = Field(default=None, ge=1)
    figure: int | None = Field(default=None, ge=1)


class KnowledgeSearchResult(StrictModel):
    """知识库检索结果及来源定位。"""

    content: ChunkContent
    chunk_type: Literal["text", "table", "chart_ocr"]
    score: float = Field(ge=0)
    source: SourceLocation
    matched_by: Literal["semantic", "keyword", "both"] = "semantic"


class KnowledgeSearchResponse(StrictModel):
    """知识库检索响应；answer 为大模型润色后的完整回答，record_id 为本次检索保存/更新的记录。"""

    query: NonEmptyText
    results: tuple[KnowledgeSearchResult, ...] = ()
    answer: AnswerText | None = None
    answer_status: Literal["none", "generated", "unavailable"] = "none"
    record_id: UUIDV1ToV5 | None = None
    empty_reason: Literal[
        "no_ready_documents", "no_region_documents", "no_matching_chunks"
    ] | None = None


class QueryRecord(StrictModel):
    """持久化的知识检索记录，可回看润色回答、原始检索结果与用户评价。"""

    id: UUIDV1ToV5
    query: NonEmptyText
    created_at: datetime
    answer: AnswerText | None = None
    answer_status: Literal["none", "generated", "unavailable"]
    results: tuple[KnowledgeSearchResult, ...] = ()
    rating: Literal["like", "dislike"] | None = None


class RatingRequest(StrictModel):
    """用户对检索记录的评价。"""

    rating: Literal["like", "dislike"]


class FeedbackCount(StrictModel):
    """按文档或地区聚合的评价计数。"""

    name: NonEmptyText
    like: int = Field(ge=0)
    dislike: int = Field(ge=0)
    total: int = Field(ge=0)


class KnowledgeStats(StrictModel):
    """知识检索评价统计；good_rate 为总体好评率，ai_good_rate 为含生成回答记录的好评率。"""

    total_feedback: int = Field(ge=0)
    like_count: int = Field(ge=0)
    dislike_count: int = Field(ge=0)
    good_rate: float = Field(ge=0, le=1)
    ai_good_rate: float = Field(ge=0, le=1)
    ai_like_count: int = Field(ge=0)
    ai_dislike_count: int = Field(ge=0)
    by_document: tuple[FeedbackCount, ...] = ()
    by_region: tuple[FeedbackCount, ...] = ()
